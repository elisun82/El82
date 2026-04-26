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
    if " " in s and "," not in s and "." not in s:
        try:
            return float(s.replace(" ", ""))
        except Exception:
            return None
    if "," in s and "." not in s:
        parts = s.split(",")
        if len(parts) > 1 and all(p.isdigit() for p in parts) and all(len(p) == 3 for p in parts[1:]):
            try:
                return float("".join(parts))
            except Exception:
                return None
        try:
            return float(s.replace(",", "."))
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None


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
    if pd.isna(dt):
        return str(value)
    return dt.strftime("%d.%m.%y")


def get_color_for_delta(value):
    if value is None or pd.isna(value):
        return "#9CA3AF"
    if value < 0:
        return "#EF4444"
    if value == 0:
        return "#F59E0B"
    return "#22C55E"


def get_section_lines(text, start_keywords, end_keywords=None):
    lines = split_lines(text)
    start_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if all(k.lower() in low for k in start_keywords):
            start_idx = i
            break
    if start_idx is None:
        return []
    if not end_keywords:
        return lines[start_idx:]
    for j in range(start_idx + 1, len(lines)):
        low = lines[j].lower()
        if all(k.lower() in low for k in end_keywords):
            return lines[start_idx:j]
    return lines[start_idx:]


def find_first_line(lines, includes=None, startswith=None):
    includes = [x.lower() for x in (includes or [])]
    startswith = startswith.lower() if startswith else None
    for line in lines:
        low = line.lower()
        if startswith and not low.startswith(startswith):
            continue
        if includes and not all(x in low for x in includes):
            continue
        return line
    return None


def extract_month_accum_values(line: str):
    if not line:
        return None, None, None, None, None
    tokens = extract_tokens(line)
    if len(tokens) < 8:
        return None, None, None, None, None
    actual = parse_number(tokens[5])
    budget = parse_number(tokens[6])
    ly = parse_number(tokens[7])
    return actual, budget, ly, safe_pct(actual, budget), safe_pct(actual, ly)


def extract_doc_date(first_page_text: str):
    lines = split_lines(first_page_text)
    for line in lines[:8]:
        for pattern in DATE_PATTERNS:
            m = pattern.search(line)
            if m:
                raw = m.group(1)
                for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        pass
    return datetime.now().strftime("%Y-%m-%d")


def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        first_page_text = ""
        for i, page in enumerate(pdf.pages):
            txt = normalize_spaces(page.extract_text() or "")
            if i == 0:
                first_page_text = txt
            pages.append(txt)
        text = "\n".join(pages)

    doc_date = extract_doc_date(first_page_text)
    hotel = detect_hotel(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast"])
    total_fb_lines = get_section_lines(text, ["total f&b", "m&e revenue"], ["total spa"])
    hotel_total_lines = get_section_lines(text, ["hotel total"], ["month", "year"]) or get_section_lines(text, ["hotel total"])

    data = {}
    data["revpar"] = extract_month_accum_values(find_first_line(accommodation_lines, startswith="revpar"))
    data["fb_total_revenue"] = extract_month_accum_values(find_first_line(total_fb_lines, startswith="total revenue"))
    data["service_hour"] = extract_month_accum_values(find_first_line(total_fb_lines, includes=["rev.", "wtrs. hour"]))
    data["kitchen_hour"] = extract_month_accum_values(find_first_line(total_fb_lines, includes=["rev.", "ktch. hour"]))
    data["hotel_total_revenue"] = extract_month_accum_values(find_first_line(hotel_total_lines, startswith="total revenue"))

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


def get_script_url():
    return st.secrets["GOOGLE_SCRIPT_URL"]


def get_secret_key():
    return st.secrets["CHEFBRAIN_SECRET_KEY"]


def load_history():
    try:
        response = requests.get(get_script_url(), params={"key": get_secret_key()}, timeout=20)
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            st.error(f"Google Script error: {result.get('error')}")
            return pd.DataFrame()

        rows = result.get("rows", [])
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        for col in df.columns:
            if col not in ["date", "hotel"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["date"] = df["date"].astype(str)
        return df

    except Exception as e:
        st.error(f"Ошибка чтения истории из Google Sheets: {e}")
        return pd.DataFrame()


def save_full_history_to_google(df):
    try:
        df = df.copy()
        df = df.where(pd.notna(df), "")
        payload = {"key": get_secret_key(), "rows": df.to_dict(orient="records")}

        response = requests.post(get_script_url(), json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            st.error(f"Google Script error: {result.get('error')}")
            return False

        return True

    except Exception as e:
        st.error(f"Ошибка записи истории в Google Sheets: {e}")
        return False


def save_history(doc_date, hotel, data):
    new_df = pd.DataFrame([flatten_history_row(doc_date, hotel, data)])
    history = load_history()

    if history.empty:
        final_df = new_df
    else:
        for col in new_df.columns:
            if col not in history.columns:
                history[col] = pd.NA
        for col in history.columns:
            if col not in new_df.columns:
                new_df[col] = pd.NA

        history = history[~((history["date"].astype(str) == str(doc_date)) & (history["hotel"] == hotel))]
        final_df = pd.concat([history, new_df], ignore_index=True)

    if save_full_history_to_google(final_df):
        st.success("История сохранена в Google Sheets.")


def normalize_date_sort(df):
    df = df.copy()
    df["_date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    df["_date_sort"] = df["_date"].dt.strftime("%Y%m%d")
    df["_date_sort"] = pd.to_numeric(df["_date_sort"], errors="coerce").fillna(0)
    return df


def latest_rows_by_hotel(df):
    if df.empty or "date" not in df.columns or "hotel" not in df.columns:
        return pd.DataFrame()

    df = normalize_date_sort(df)

    return (
        df.sort_values(["_date_sort", "hotel"], ascending=[True, True])
          .groupby("hotel", as_index=False)
          .tail(1)
          .sort_values("hotel")
          .drop(columns=["_date", "_date_sort"], errors="ignore")
    )


def build_summary(data):
    notes = []

    hotel_total_vs_ly = data["hotel_total_revenue"][4]
    hotel_total_vs_budget = data["hotel_total_revenue"][3]
    revpar_vs_ly = data["revpar"][4]
    fb_total_vs_ly = data["fb_total_revenue"][4]
    service_vs_ly = data["service_hour"][4]
    kitchen_vs_ly = data["kitchen_hour"][4]

    if hotel_total_vs_ly is not None:
        if hotel_total_vs_ly < 0:
            notes.append(("Общая выручка отеля ниже прошлого года.", "bad"))
        elif hotel_total_vs_ly < 8:
            notes.append(("Общая выручка отеля растёт, но слабее ожидаемого темпа.", "warn"))
        else:
            notes.append(("Общая выручка отеля показывает сильный рост к прошлому году.", "good"))

    if hotel_total_vs_budget is not None:
        notes.append(("Факт отеля ниже бюджета месяца.", "bad") if hotel_total_vs_budget < 0 else ("Факт отеля держится выше бюджета месяца.", "good"))

    if revpar_vs_ly is not None:
        notes.append(("RevPAR ниже прошлого года.", "bad") if revpar_vs_ly < 0 else ("RevPAR выше прошлого года.", "good"))

    if fb_total_vs_ly is not None:
        notes.append(("F&B total revenue проседает к прошлому году.", "bad") if fb_total_vs_ly < 0 else ("F&B total revenue растёт к прошлому году.", "good"))

    if service_vs_ly is not None and kitchen_vs_ly is not None:
        if service_vs_ly > kitchen_vs_ly:
            notes.append(("Эффективность сервиса растёт быстрее кухни.", "good"))
        elif kitchen_vs_ly > service_vs_ly:
            notes.append(("Эффективность кухни растёт быстрее сервиса.", "good"))
        else:
            notes.append(("Кухня и сервис показывают схожую динамику.", "warn"))

    return notes


def build_alerts(data):
    alerts = []

    checks = [
        (data["hotel_total_revenue"][3], "Отель ниже бюджета месяца.", "bad"),
        (data["hotel_total_revenue"][4], "Общая выручка отеля ниже прошлого года.", "bad"),
        (data["fb_total_revenue"][4], "F&B total revenue ниже прошлого года.", "bad"),
        (data["revpar"][4], "RevPAR ниже прошлого года.", "warn"),
    ]

    for value, text, level in checks:
        if value is not None and value < 0:
            alerts.append((text, level))

    service_vs_ly = data["service_hour"][4]
    kitchen_vs_ly = data["kitchen_hour"][4]
    if service_vs_ly is not None and kitchen_vs_ly is not None and abs(service_vs_ly - kitchen_vs_ly) >= 10:
        alerts.append(("Сильный разрыв динамики между сервисом и кухней.", "warn"))

    if not alerts:
        alerts.append(("Критичных отклонений не найдено.", "good"))

    return alerts


def render_summary_block(notes):
    if not notes:
        return

    st.subheader("Вывод")

    color_map = {
        "good": ("#166534", "#DCFCE7"),
        "warn": ("#92400E", "#FEF3C7"),
        "bad": ("#991B1B", "#FEE2E2"),
    }

    for text, level in notes:
        color, bg = color_map.get(level, ("#374151", "#F3F4F6"))
        st.markdown(
            f"""<div class="summary-box" style="border-left:4px solid {color}; background:{bg}; color:{color};">{text}</div>""",
            unsafe_allow_html=True
        )


def render_alert_block(alerts):
    st.subheader("Красные зоны")

    for text, level in alerts:
        if level == "bad":
            st.markdown(f"<div class='kpi-warning'>{text}</div>", unsafe_allow_html=True)
        elif level == "warn":
            st.markdown(f"<div class='kpi-caution'>{text}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='kpi-good'>{text}</div>", unsafe_allow_html=True)


def show_metric_block(col, section_name, title, metric_name, values):
    actual, budget, ly, vs_budget, vs_ly = values

    with col:
        st.markdown(f"**{section_name}**")
        st.markdown(f"<div class='small-note'>{title}</div>", unsafe_allow_html=True)
        st.metric(label=" ", value=format_value(metric_name, actual))
        st.markdown(
            f"<span style='color:{get_color_for_delta(vs_budget)}; font-weight:700;'>vs Bu. Accum.: {format_pct(vs_budget)}</span>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<span style='color:{get_color_for_delta(vs_ly)}; font-weight:700;'>vs LY. Accum.: {format_pct(vs_ly)}</span>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<span class='small-note'>Bu: {format_value(metric_name, budget)} | LY: {format_value(metric_name, ly)}</span>",
            unsafe_allow_html=True
        )


def build_compare_table(latest):
    rows = []
    for _, row in latest.iterrows():
        rows.append({
            "Hotel": row["hotel"],
            "Date": fmt_date(row["date"]),
            "Hotel Total % LY": row.get("hotel_total_revenue_vs_ly"),
            "RevPAR % LY": row.get("revpar_vs_ly"),
            "F&B Total % LY": row.get("fb_total_revenue_vs_ly"),
            "Service % LY": row.get("service_hour_vs_ly"),
            "Kitchen % LY": row.get("kitchen_hour_vs_ly"),
        })
    return pd.DataFrame(rows)


def get_status_badge(row):
    checks = [
        row.get("hotel_total_revenue_vs_budget"),
        row.get("hotel_total_revenue_vs_ly"),
        row.get("revpar_vs_ly"),
        row.get("fb_total_revenue_vs_ly"),
        row.get("service_hour_vs_ly"),
        row.get("kitchen_hour_vs_ly"),
    ]

    negatives = sum(1 for x in checks if pd.notna(x) and x < 0)
    strong = sum(1 for x in checks if pd.notna(x) and x >= 8)

    if negatives >= 3:
        return "Критично", "#991B1B", "#FEE2E2"
    if negatives >= 1:
        return "Риск", "#92400E", "#FEF3C7"
    if strong >= 3:
        return "Рост", "#166534", "#DCFCE7"
    return "Норма", "#1D4ED8", "#DBEAFE"


def render_kpi_dashboard(latest_df):
    st.subheader("KPI-дэшборд")

    cols = st.columns(3)

    for i, (_, row) in enumerate(latest_df.iterrows()):
        status_text, status_color, status_bg = get_status_badge(row)
        date_text = fmt_date(row["date"])

        card_html = f"""<div style="border:1px solid rgba(255,255,255,0.08); border-radius:16px; padding:16px; background:linear-gradient(180deg,#111827 0%,#0B1220 100%); min-height:310px; margin-bottom:14px;">
<div style="font-size:20px; font-weight:800; color:#F9FAFB; margin-bottom:4px;">{row["hotel"]}</div>
<div style="font-size:12px; color:#9CA3AF; margin-bottom:10px;">Дата: {date_text}</div>
<div style="display:inline-block; padding:6px 10px; border-radius:999px; background:{status_bg}; color:{status_color}; font-size:12px; font-weight:700; margin-bottom:14px;">{status_text}</div>

<div style="font-size:13px; color:#9CA3AF;">Отель Total vs LY</div>
<div style="font-size:22px; font-weight:800; color:#F9FAFB; margin-bottom:8px;">{fmt_pct(row.get("hotel_total_revenue_vs_ly"))}</div>

<div style="font-size:13px; color:#9CA3AF;">RevPAR vs LY</div>
<div style="font-size:18px; font-weight:700; color:#F9FAFB; margin-bottom:8px;">{fmt_pct(row.get("revpar_vs_ly"))}</div>

<div style="font-size:13px; color:#9CA3AF;">F&B vs LY</div>
<div style="font-size:18px; font-weight:700; color:#F9FAFB; margin-bottom:8px;">{fmt_pct(row.get("fb_total_revenue_vs_ly"))}</div>

<div style="font-size:13px; color:#9CA3AF;">Сервис vs LY</div>
<div style="font-size:18px; font-weight:700; color:#F9FAFB; margin-bottom:8px;">{fmt_pct(row.get("service_hour_vs_ly"))}</div>

<div style="font-size:13px; color:#9CA3AF;">Кухня vs LY</div>
<div style="font-size:18px; font-weight:700; color:#F9FAFB;">{fmt_pct(row.get("kitchen_hour_vs_ly"))}</div>
</div>"""

        with cols[i % 3]:
            st.markdown(card_html, unsafe_allow_html=True)


def make_pretty_history(history):
    history = history.copy()

    display_df = pd.DataFrame({
        "Дата": history["date"].apply(fmt_date),
        "Отель": history["hotel"],

        "Отель Факт": history.get("hotel_total_revenue_actual"),
        "Отель vs LY %": history.get("hotel_total_revenue_vs_ly"),

        "RevPAR Факт": history.get("revpar_actual"),
        "RevPAR vs LY %": history.get("revpar_vs_ly"),

        "F&B Факт": history.get("fb_total_revenue_actual"),
        "F&B vs LY %": history.get("fb_total_revenue_vs_ly"),

        "Сервис Факт": history.get("service_hour_actual"),
        "Сервис vs LY %": history.get("service_hour_vs_ly"),

        "Кухня Факт": history.get("kitchen_hour_actual"),
        "Кухня vs LY %": history.get("kitchen_hour_vs_ly"),
    })

    for col in display_df.columns:
        if "%" in col:
            display_df[col] = display_df[col].apply(lambda x: "—" if pd.isna(x) else f"{x:+.1f}%")
        elif "Факт" in col:
            display_df[col] = display_df[col].apply(lambda x: "—" if pd.isna(x) else f"{x:,.0f}".replace(",", " "))

    return display_df


st.markdown("""
<div class="hero-box">
    <div class="hero-title">ChefBrain</div>
    <div class="hero-subtitle">Month → Accum. vs Bu. Accum. и LY. Accum. · Google Sheets History</div>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Загрузи PDF отчёт", type=["pdf"])

if uploaded_file:
    doc_date, hotel, data = parse_pdf(uploaded_file)
    save_history(doc_date, hotel, data)

    st.subheader(f"Отель: {hotel} · Дата документа: {fmt_date(doc_date)}")

    c1, c2, c3, c4, c5 = st.columns(5)

    show_metric_block(c1, "ACCOMMODATION", "RevPAR", "revpar", data["revpar"])
    show_metric_block(c2, "TOTAL F&B", "Total revenue", "fb_total_revenue", data["fb_total_revenue"])
    show_metric_block(c3, "SERVICE", "Rev. / wtrs. Hour", "service_hour", data["service_hour"])
    show_metric_block(c4, "KITCHEN", "Rev. / ktch. Hour", "kitchen_hour", data["kitchen_hour"])
    show_metric_block(c5, "HOTEL TOTAL", "Total revenue", "hotel_total_revenue", data["hotel_total_revenue"])

    render_alert_block(build_alerts(data))
    render_summary_block(build_summary(data))

history = load_history()

st.markdown("---")
st.subheader("Сравнение отелей")

if history.empty:
    st.write("Нет данных")
else:
    latest = latest_rows_by_hotel(history)

    if latest.empty:
        st.write("Недостаточно данных")
    else:
        render_kpi_dashboard(latest)
        compare_df = build_compare_table(latest)
        st.dataframe(compare_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.subheader("Графики по отелю")


def chart_to_number(value):
    if value is None or pd.isna(value):
        return None

    s = str(value).strip()
    s = s.replace("\xa0", " ")
    s = s.replace(" ", "")
    s = s.replace("RUR", "")
    s = s.replace("%", "")

    # вариант 4,114.34 — запятая как разделитель тысяч
    if "," in s and "." in s:
        s = s.replace(",", "")

    # вариант 4114,34 — запятая как десятичный разделитель
    elif "," in s and "." not in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except Exception:
        return None


if history.empty:
    st.write("Нет данных")
else:
    history_chart = history.copy()
    history_chart.columns = [str(c).strip() for c in history_chart.columns]

    required_columns = [
        "date",
        "hotel",
        "hotel_total_revenue_actual",
        "revpar_actual",
        "fb_total_revenue_actual",
        "service_hour_actual",
        "kitchen_hour_actual",
    ]

    missing = [c for c in required_columns if c not in history_chart.columns]

    if missing:
        st.error(f"В истории не хватает колонок: {missing}")
        st.write("Доступные колонки:", list(history_chart.columns))
    else:
        history_chart["_date"] = pd.to_datetime(
            history_chart["date"],
            errors="coerce",
            utc=True
        )

        history_chart = history_chart.dropna(subset=["_date"])

        metric_options = {
            "Hotel Total Revenue": "hotel_total_revenue_actual",
            "RevPAR": "revpar_actual",
            "F&B Total Revenue": "fb_total_revenue_actual",
            "Service / wtrs. hour": "service_hour_actual",
            "Kitchen / ktch. hour": "kitchen_hour_actual",
        }

        hotel_filter = st.selectbox(
            "Выбери отель",
            sorted(history_chart["hotel"].dropna().unique().tolist()),
            key="chart_hotel_filter_final"
        )

        selected_metric_name = st.selectbox(
            "Показатель",
            list(metric_options.keys()),
            index=0,
            key="chart_metric_filter_final"
        )

        chart_column = metric_options[selected_metric_name]

        filtered = history_chart[history_chart["hotel"] == hotel_filter].copy()

        filtered[chart_column] = filtered[chart_column].apply(chart_to_number)

        chart_df = filtered[["_date", chart_column]].dropna().copy()
        chart_df = chart_df.sort_values("_date")

        if chart_df.empty:
            st.warning(f"Нет числовых данных для графика: {selected_metric_name}")
            st.write(filtered[["date", "hotel", chart_column]].tail(20))
        else:
            chart_df = chart_df.set_index("_date")
            chart_df = chart_df.rename(columns={chart_column: selected_metric_name})

            st.markdown(f"**{selected_metric_name}**")
            st.line_chart(chart_df)

st.markdown("---")
st.subheader("Пополнить историю")

uploaded_history = st.file_uploader(
    "Загрузи CSV с историей для добавления в Google Sheets",
    type=["csv"],
    key="history_upload"
)

if uploaded_history:
    try:
        uploaded_df = pd.read_csv(uploaded_history)
        current_history = load_history()

        if current_history.empty:
            combined = uploaded_df
        else:
            combined = pd.concat([current_history, uploaded_df], ignore_index=True)

        if "date" in combined.columns and "hotel" in combined.columns:
            combined["date"] = combined["date"].astype(str)
            combined = combined.drop_duplicates(subset=["date", "hotel"], keep="last")

        if save_full_history_to_google(combined):
            st.success("История успешно пополнена и сохранена в Google Sheets.")
            history = load_history()

    except Exception as e:
        st.error(f"Ошибка при пополнении истории: {e}")

st.markdown("---")
st.subheader("История")

if history.empty:
    st.write("Нет данных")
else:
    history_for_display = normalize_date_sort(history)
    history_for_display = history_for_display.sort_values(
        by=["_date_sort", "hotel"],
        ascending=[True, True]
    )

    display_df = make_pretty_history(history_for_display)
    st.dataframe(display_df, use_container_width=True)

    csv = history.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 Скачать историю CSV",
        data=csv,
        file_name="chefbrain_history.csv",
        mime="text/csv"
    )

if os.path.exists(HISTORY_FILE_LOCAL_BACKUP):
    with open(HISTORY_FILE_LOCAL_BACKUP, "rb") as f:
        st.download_button(
            "📥 Скачать старую локальную историю",
            f,
            file_name=HISTORY_FILE_LOCAL_BACKUP,
            mime="text/csv"
        )
