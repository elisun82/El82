import os
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import requests
import streamlit as st

HISTORY_FILE_LOCAL_BACKUP = "history_accum_v3.csv"
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]

st.set_page_config(page_title="ChefBrain", layout="wide")

# --- Стилизация ---
st.markdown("""
<style>
.block-container {padding-top:1rem; padding-bottom:2rem; max-width:1450px;}
.hero-box {
    background: linear-gradient(180deg, #101828 0%, #0B1220 100%);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px;
    padding: 18px 22px;
    margin-bottom: 16px;
}
.hero-title {font-size:30px; font-weight:800; color:#F9FAFB; margin-bottom:4px;}
.hero-subtitle {color:#9CA3AF; font-size:13px;}
.summary-box {border-radius:12px; padding:12px 14px; margin-bottom:10px; font-size:15px;}
.small-note {font-size:12px; color:#94A3B8; margin-top:-6px; margin-bottom:12px;}
.kpi-warning {border-left:4px solid #991B1B; background:#FEE2E2; color:#991B1B; border-radius:12px; padding:12px 14px; margin-bottom:10px; font-size:15px;}
.kpi-caution {border-left:4px solid #92400E; background:#FEF3C7; color:#92400E; border-radius:12px; padding:12px 14px; margin-bottom:10px; font-size:15px;}
.kpi-good {border-left:4px solid #166534; background:#DCFCE7; color:#166534; border-radius:12px; padding:12px 14px; margin-bottom:10px; font-size:15px;}
</style>
""", unsafe_allow_html=True)

# --- Вспомогательные функции парсинга ---
NUM_PATTERN = re.compile(r"\d{1,3}(?:[ \u00A0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
DATE_PATTERNS = [
    re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b"),
    re.compile(r"\b(\d{2}/\d{2}/\d{4})\b"),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
]

def normalize_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "")

def split_lines(text: str):
    return [line.strip() for line in text.splitlines() if line.strip()]

def detect_hotel(text: str) -> str:
    upper = text.upper()
    for hotel in HOTELS:
        if hotel in upper:
            return hotel
    return "UNKNOWN"

def parse_number(value):
    if value is None: return None
    s = str(value).replace("RUR", "").replace("%", "").replace("\xa0", " ").strip()
    if not s: return None
    if " " in s and "," not in s and "." not in s:
        try: return float(s.replace(" ", ""))
        except: return None
    if "," in s and "." in s: s = s.replace(",", "")
    elif "," in s: s = s.replace(",", ".")
    try: return float(s)
    except: return None

def extract_tokens(line: str):
    cleaned = line.replace("RUR", "").replace("%", "").replace("\xa0", " ").strip()
    return [m.group(0).strip() for m in NUM_PATTERN.finditer(cleaned)]

def safe_pct(actual, reference):
    if actual is None or reference is None or pd.isna(actual) or pd.isna(reference) or reference == 0:
        return None
    return round((actual / reference - 1.0) * 100, 1)

# --- Форматирование ---
def format_value(metric_name: str, value):
    if value is None or pd.isna(value): return "нет данных"
    return f"{value:,.0f}".replace(",", " ")

def format_pct(value):
    if value is None or pd.isna(value): return "нет данных"
    return f"{value:+.1f}%"

def fmt_pct(x):
    if x is None or pd.isna(x): return "—"
    return f"{x:+.1f}%"

def fmt_date(value):
    if value is None or pd.isna(value): return "—"
    dt = pd.to_datetime(value, errors="coerce", utc=True)
    return dt.strftime("%d.%m.%y") if not pd.isna(dt) else str(value)

def get_color_for_delta(value):
    if value is None or pd.isna(value): return "#9CA3AF"
    return "#EF4444" if value < 0 else "#22C55E"

# --- Логика извлечения из PDF ---
def get_section_lines(text, start_keywords, end_keywords=None):
    lines = split_lines(text)
    start_idx = None
    for i, line in enumerate(lines):
        if all(k.lower() in line.lower() for k in start_keywords):
            start_idx = i
            break
    if start_idx is None: return []
    if not end_keywords: return lines[start_idx:]
    for j in range(start_idx + 1, len(lines)):
        low = lines[j].lower()
        if any(all(k.lower() in low for k in group) if isinstance(group, list) else group.lower() in low for group in end_keywords):
            return lines[start_idx:j]
    return lines[start_idx:]

def find_first_line(lines, includes=None):
    if not includes: return None
    includes = [x.lower() for x in includes]
    for line in lines:
        if all(x in line.lower() for x in includes): return line
    return None

def extract_month_accum_values(line: str):
    if not line: return None, None, None, None, None
    tokens = extract_tokens(line)
    if len(tokens) >= 6:
        # Индексы 3,4,5 соответствуют Month Accum (MTD)
        actual = parse_number(tokens[3])
        budget = parse_number(tokens[4])
        ly = parse_number(tokens[5])
        return actual, budget, ly, safe_pct(actual, budget), safe_pct(actual, ly)
    return None, None, None, None, None

def extract_doc_date(first_page_text: str):
    lines = split_lines(first_page_text)
    for line in lines[:10]:
        for pattern in DATE_PATTERNS:
            m = pattern.search(line)
            if m:
                raw = m.group(1)
                for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
                    try: return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                    except: pass
    return datetime.now().strftime("%Y-%m-%d")

def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = [normalize_spaces(p.extract_text() or "") for p in pdf.pages]
        first_page_text = pages[0] if pages else ""
        text = "\n".join(pages)

    doc_date = extract_doc_date(first_page_text)
    hotel = detect_hotel(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], [["breakfast"], ["total f&b"]])
    total_fb_lines = get_section_lines(text, ["total f&b", "revenue"], [["total spa"], ["hotel total"]])
    hotel_total_lines = get_section_lines(text, ["hotel total"], [["month"], ["year"]])

    data = {
        "revpar": extract_month_accum_values(find_first_line(accommodation_lines, ["revpar"])),
        "fb_total_revenue": extract_month_accum_values(find_first_line(total_fb_lines, ["total revenue"])),
        "service_hour": extract_month_accum_values(find_first_line(total_fb_lines, ["wtrs", "hour"])),
        "kitchen_hour": extract_month_accum_values(find_first_line(total_fb_lines, ["ktch", "hour"])),
        "hotel_total_revenue": extract_month_accum_values(find_first_line(hotel_total_lines, ["total revenue"]))
    }
    return doc_date, hotel, data

# --- Работа с Google Sheets ---
def load_history():
    try:
        url = st.secrets["GOOGLE_SCRIPT_URL"]
        key = st.secrets["CHEFBRAIN_SECRET_KEY"]
        resp = requests.get(url, params={"key": key}, timeout=20)
        result = resp.json()
        if not result.get("ok"): return pd.DataFrame()
        df = pd.DataFrame(result.get("rows", []))
        for col in df.columns:
            if col not in ["date", "hotel"]: df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except: return pd.DataFrame()

def save_history(doc_date, hotel, data):
    row = {"date": doc_date, "hotel": hotel}
    for k, v in data.items():
        row.update({f"{k}_actual": v[0], f"{k}_budget": v[1], f"{k}_ly": v[2], f"{k}_vs_budget": v[3], f"{k}_vs_ly": v[4]})
    
    history = load_history()
    new_row_df = pd.DataFrame([row])
    if not history.empty:
        history = history[~((history["date"].astype(str) == str(doc_date)) & (history["hotel"] == hotel))]
        final_df = pd.concat([history, new_row_df], ignore_index=True)
    else:
        final_df = new_row_df
        
    payload = {"key": st.secrets["CHEFBRAIN_SECRET_KEY"], "rows": final_df.where(pd.notna(final_df), None).to_dict(orient="records")}
    requests.post(st.secrets["GOOGLE_SCRIPT_URL"], json=payload, timeout=30)

# --- Рендеринг блоков (из вашего оригинала) ---
def build_alerts(data):
    alerts = []
    checks = [
        (data["hotel_total_revenue"][3], "Отель ниже бюджета месяца.", "bad"),
        (data["hotel_total_revenue"][4], "Общая выручка отеля ниже прошлого года.", "bad"),
        (data["fb_total_revenue"][4], "F&B total revenue ниже прошлого года.", "bad"),
        (data["revpar"][4], "RevPAR ниже прошлого года.", "warn"),
    ]
    for val, txt, lvl in checks:
        if val is not None and val < 0: alerts.append((txt, lvl))
    if not alerts: alerts.append(("Критичных отклонений не найдено.", "good"))
    return alerts

def build_summary(data):
    notes = []
    ht_ly = data["hotel_total_revenue"][4]
    if ht_ly is not None:
        if ht_ly < 0: notes.append(("Общая выручка отеля ниже прошлого года.", "bad"))
        elif ht_ly < 8: notes.append(("Общая выручка отеля растёт, но слабее ожидаемого темпа.", "warn"))
        else: notes.append(("Общая выручка отеля показывает сильный рост.", "good"))
    return notes

def render_metric_card(col, section, title, key, values):
    actual, budget, ly, vs_bu, vs_ly = values
    with col:
        st.markdown(f"**{section}**")
        st.markdown(f"<div class='small-note'>{title}</div>", unsafe_allow_html=True)
        st.metric(label=" ", value=format_value("", actual))
        st.markdown(f"<span style='color:{get_color_for_delta(vs_bu)}; font-weight:700;'>vs Bu: {format_pct(vs_bu)}</span>", unsafe_allow_html=True)
        st.markdown(f"<span style='color:{get_color_for_delta(vs_ly)}; font-weight:700;'>vs LY: {format_pct(vs_ly)}</span>", unsafe_allow_html=True)
        st.markdown(f"<div class='small-note'>Bu: {format_value('', budget)} | LY: {format_value('', ly)}</div>", unsafe_allow_html=True)

# --- MAIN APP ---
st.markdown('<div class="hero-box"><div class="hero-title">ChefBrain</div><div class="hero-subtitle">Month Accum. Analysis</div></div>', unsafe_allow_html=True)

uploaded = st.file_uploader("Загрузи PDF", type=["pdf"])
if uploaded:
    doc_date, hotel, data = parse_pdf(uploaded)
    save_history(doc_date, hotel, data)
    
    st.subheader(f"Отель: {hotel} · Дата: {fmt_date(doc_date)}")
    c1, c2, c3, c4, c5 = st.columns(5)
    render_metric_card(c1, "ACCOMMODATION", "RevPAR", "revpar", data["revpar"])
    render_metric_card(c2, "TOTAL F&B", "Total Revenue", "fb", data["fb_total_revenue"])
    render_metric_card(c3, "SERVICE", "Rev./Wtrs Hour", "srv", data["service_hour"])
    render_metric_card(c4, "KITCHEN", "Rev./Ktch Hour", "ktc", data["kitchen_hour"])
    render_metric_card(c5, "HOTEL TOTAL", "Total Revenue", "tot", data["hotel_total_revenue"])

    # Алерты и Выводы
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Красные зоны")
        for txt, lvl in build_alerts(data):
            cls = "kpi-warning" if lvl=="bad" else "kpi-caution" if lvl=="warn" else "kpi-good"
            st.markdown(f"<div class='{cls}'>{txt}</div>", unsafe_allow_html=True)
    with col_r:
        st.subheader("Вывод")
        for txt, lvl in build_summary(data):
            bg = "#FEE2E2" if lvl=="bad" else "#FEF3C7" if lvl=="warn" else "#DCFCE7"
            color = "#991B1B" if lvl=="bad" else "#92400E" if lvl=="warn" else "#166534"
            st.markdown(f"<div class='summary-box' style='background:{bg}; color:{color}; border-left:4px solid {color}'>{txt}</div>", unsafe_allow_html=True)

# --- История и Графики ---
history = load_history()
if not history.empty:
    st.markdown("---")
    st.subheader("Сравнение отелей (Последние данные)")
    
    # KPI Карточки отелей
    latest = history.sort_values("date").groupby("hotel").tail(1).sort_values("hotel")
    cols_kpi = st.columns(len(latest) if len(latest) > 0 else 1)
    for i, (_, r) in enumerate(latest.iterrows()):
        with cols_kpi[i % 3]:
            st.markdown(f"""
            <div style="background:#111827; padding:15px; border-radius:15px; border:1px solid #374151;">
                <div style="color:#9CA3AF; font-size:12px;">{fmt_date(r['date'])}</div>
                <div style="font-size:18px; font-weight:800; color:white;">{r['hotel']}</div>
                <hr style="margin:10px 0; border-color:#374151;">
                <div style="font-size:13px; color:#9CA3AF;">Отель vs LY</div>
                <div style="font-size:20px; font-weight:700; color:{get_color_for_delta(r.get('hotel_total_revenue_vs_ly'))};">{fmt_pct(r.get('hotel_total_revenue_vs_ly'))}</div>
                <div style="font-size:13px; color:#9CA3AF; margin-top:10px;">F&B vs LY</div>
                <div style="font-size:18px; font-weight:700; color:{get_color_for_delta(r.get('fb_total_revenue_vs_ly'))};">{fmt_pct(r.get('fb_total_revenue_vs_ly'))}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("Графики трендов")
    h_chart = history.copy()
    h_chart["_dt"] = pd.to_datetime(h_chart["date"])
    h_chart = h_chart.sort_values("_dt")
    
    sel_h = st.selectbox("Выберите отель для графиков", sorted(h_chart["hotel"].unique()))
    sel_m = st.selectbox("Выберите показатель", ["hotel_total_revenue_actual", "revpar_actual", "fb_total_revenue_actual", "service_hour_actual", "kitchen_hour_actual"])
    
    plot_df = h_chart[h_chart["hotel"] == sel_h][["_dt", sel_m]].dropna().set_index("_dt")
    if not plot_df.empty:
        st.line_chart(plot_df)

    st.subheader("Полная таблица истории")
    st.dataframe(history.sort_values("date", ascending=False), use_container_width=True)
