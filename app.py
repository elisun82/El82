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
    if value is None:
        return None
    s = str(value).replace("RUR", "").replace("%", "").replace("\xa0", " ").strip()
    if not s: return None
    
    if " " in s and "," not in s and "." not in s:
        try: return float(s.replace(" ", ""))
        except: return None
        
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
        
    try: return float(s)
    except: return None

def extract_tokens(line: str):
    cleaned = line.replace("RUR", "").replace("%", "").replace("\xa0", " ").strip()
    return [m.group(0).strip() for m in NUM_PATTERN.finditer(cleaned)]

def safe_pct(actual, reference):
    if actual is None or reference is None or pd.isna(actual) or pd.isna(reference) or reference == 0:
        return None
    return round((actual / reference - 1.0) * 100, 1)

def format_value(metric_name: str, value):
    if value is None or pd.isna(value):
        return "нет данных"
    return f"{value:,.0f}".replace(",", " ")

def format_pct(value):
    if value is None or pd.isna(value):
        return "нет данных"
    return f"{value:+.1f}%"

def fmt_pct(x):
    if x is None or pd.isna(x):
        return "—"
    return f"{x:+.1f}%"

def fmt_date(value):
    if value is None or pd.isna(value):
        return "—"
    dt = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(dt): return str(value)
    return dt.strftime("%d.%m.%y")

def get_color_for_delta(value):
    if value is None or pd.isna(value): return "#9CA3AF"
    if value < 0: return "#EF4444"
    if value == 0: return "#F59E0B"
    return "#22C55E"

def get_section_lines(text, start_keywords, end_keywords=None):
    lines = split_lines(text)
    start_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if all(k.lower() in low for k in start_keywords):
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
        low = line.lower()
        if all(x in low for x in includes):
            return line
    return None

def extract_month_accum_values(line: str):
    if not line:
        return None, None, None, None, None
    tokens = extract_tokens(line)
    
    # В отчете Accum: 0-2 (Day), 3-5 (MTD/Accum), 6-8 (YTD)
    # Если чисел >= 6, берем блок MTD (индексы 3, 4, 5)
    if len(tokens) >= 6:
        actual = parse_number(tokens[3])
        budget = parse_number(tokens[4])
        ly = parse_number(tokens[5])
        return actual, budget, ly, safe_pct(actual, budget), safe_pct(actual, ly)
    # Если чисел всего 3 (редкий случай), берем их как актуальные
    elif len(tokens) >= 3:
        actual = parse_number(tokens[0])
        budget = parse_number(tokens[1])
        ly = parse_number(tokens[2])
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
                    try:
                        return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                    except ValueError: pass
    return datetime.now().strftime("%Y-%m-%d")

def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = [normalize_spaces(p.extract_text() or "") for p in pdf.pages]
        first_page_text = pages[0] if pages else ""
        text = "\n".join(pages)

    doc_date = extract_doc_date(first_page_text)
    hotel = detect_hotel(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast", "total f&b"])
    total_fb_lines = get_section_lines(text, ["total f&b", "revenue"], ["total spa", "hotel total"])
    hotel_total_lines = get_section_lines(text, ["hotel total"], ["year-to-date"])

    data = {}
    data["revpar"] = extract_month_accum_values(find_first_line(accommodation_lines, ["revpar"]))
    data["fb_total_revenue"] = extract_month_accum_values(find_first_line(total_fb_lines, ["total revenue"]))
    # Упрощаем поиск для сервиса и кухни (ищем без жестких точек)
    data["service_hour"] = extract_month_accum_values(find_first_line(total_fb_lines, ["wtrs", "hour"]))
    data["kitchen_hour"] = extract_month_accum_values(find_first_line(total_fb_lines, ["ktch", "hour"]))
    data["hotel_total_revenue"] = extract_month_accum_values(find_first_line(hotel_total_lines, ["total revenue"]))

    return doc_date, hotel, data

def flatten_history_row(doc_date, hotel, data):
    row = {"date": doc_date, "hotel": hotel}
    for metric_key, values in data.items():
        actual, budget, ly, vs_budget, vs_ly = values
        row[f"{metric_key}_actual"] = actual
        row[f"{metric_key}_budget"] = budget
        row[f"{metric_key}_ly"] = ly
        row[f"{metric_key}_vs_budget"] = vs_budget
        row[f"{metric_key}_vs_ly"] = vs_ly
    return row

def load_history():
    try:
        response = requests.get(st.secrets["GOOGLE_SCRIPT_URL"], params={"key": st.secrets["CHEFBRAIN_SECRET_KEY"]}, timeout=20)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"): return pd.DataFrame()
        df = pd.DataFrame(result.get("rows", []))
        for col in df.columns:
            if col not in ["date", "hotel"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except: return pd.DataFrame()

def save_full_history_to_google(df):
    try:
        df = df.copy().where(pd.notna(df), None)
        payload = {"key": st.secrets["CHEFBRAIN_SECRET_KEY"], "rows": df.to_dict(orient="records")}
        response = requests.post(st.secrets["GOOGLE_SCRIPT_URL"], json=payload, timeout=30)
        return response.json().get("ok", False)
    except: return False

def save_history(doc_date, hotel, data):
    new_df = pd.DataFrame([flatten_history_row(doc_date, hotel, data)])
    history = load_history()
    if history.empty:
        final_df = new_df
    else:
        history = history[~((history["date"].astype(str) == str(doc_date)) & (history["hotel"] == hotel))]
        final_df = pd.concat([history, new_df], ignore_index=True)
    if save_full_history_to_google(final_df):
        st.success("История обновлена.")

def normalize_date_sort(df):
    df = df.copy()
    df["_dt"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("_dt")

# --- UI LOGIC ---
st.markdown("""<div class="hero-box"><div class="hero-title">ChefBrain</div><div class="hero-subtitle">Analytics & Trends</div></div>""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Загрузи PDF отчёт", type=["pdf"])
if uploaded_file:
    doc_date, hotel, data = parse_pdf(uploaded_file)
    save_history(doc_date, hotel, data)
    st.info(f"Обработан отель: {hotel} за {doc_date}")

history = load_history()

if not history.empty:
    st.subheader("Графики по отелю")
    
    # Конвертация для графиков
    h_chart = normalize_date_sort(history)
    
    hotel_list = sorted(h_chart["hotel"].unique())
    sel_hotel = st.selectbox("Выбери отель", hotel_list)
    
    metrics = {
        "Hotel Total Revenue": "hotel_total_revenue_actual",
        "RevPAR": "revpar_actual",
        "F&B Total Revenue": "fb_total_revenue_actual",
        "Service Hour": "service_hour_actual",
        "Kitchen Hour": "kitchen_hour_actual"
    }
    sel_metric = st.selectbox("Показатель", list(metrics.keys()))
    col_name = metrics[sel_metric]
    
    df_plot = h_chart[h_chart["hotel"] == sel_hotel][["_dt", col_name]].dropna()
    
    if not df_plot.empty:
        df_plot = df_plot.set_index("_dt")
        st.line_chart(df_plot)
    else:
        st.warning(f"Нет данных для {sel_metric} по отелю {sel_hotel}. Проверьте парсинг.")
        # Debug info
        with st.expander("Debug: Raw Data"):
            st.write(h_chart[h_chart["hotel"] == sel_hotel][["date", "hotel", col_name]])

    st.subheader("История")
    st.dataframe(history.sort_values("date", ascending=False), use_container_width=True)
