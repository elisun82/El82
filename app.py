import os
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

# =====================
# SETTINGS
# =====================
HISTORY_FILE = "history_accum_v2.csv"
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]

st.set_page_config(page_title="ChefBrain", layout="wide")

# =====================
# STYLES
# =====================
st.markdown("""
<style>
.block-container {
    padding-top: 1rem;
    padding-bottom: 2rem;
    max-width: 1450px;
}
.hero-box {
    background: linear-gradient(180deg, #101828 0%, #0B1220 100%);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px;
    padding: 18px 22px;
    margin-bottom: 16px;
}
.hero-title {
    font-size: 30px;
    font-weight: 800;
    color: #F9FAFB;
    margin-bottom: 4px;
}
.hero-subtitle {
    color: #9CA3AF;
    font-size: 13px;
}
.summary-box {
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 10px;
    font-size: 15px;
}
.small-note {
    font-size: 12px;
    color: #94A3B8;
    margin-top: -6px;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# =====================
# HELPERS
# =====================
NUM_PATTERN = re.compile(
    r"\d{1,3}(?:[ \u00A0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
)

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

    if "." in s:
        try:
            return float(s)
        except Exception:
            return None

    try:
        return float(s)
    except Exception:
        return None

def extract_tokens(line: str):
    cleaned = (
        line.replace("RUR", "")
            .replace("%", "")
            .replace("\xa0", " ")
            .strip()
    )
    return [m.group(0).strip() for m in NUM_PATTERN.finditer(cleaned)]

def safe_pct(actual, reference):
    if actual is None or reference is None or reference == 0:
        return None
    return round((actual / reference - 1.0) * 100, 1)

def format_value(metric_name: str, value):
    if value is None:
        return "нет данных"
    return f"{value:,.0f}".replace(",", " ")

def format_pct(value):
    if value is None:
        return "нет данных"
    return f"{value:+.1f}%"

def get_color_for_delta(value):
    if value is None:
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
    """
    Структура строки:
    Day: Act | Bu | LY | idx_bu | idx_ly
    Month: Accum | Bu.Accum | LY.Accum | idx_bu | idx_ly

    Нужно:
    [5] = Accum
    [6] = Bu.Accum
    [7] = LY.Accum
    """
    if not line:
        return None, None, None, None, None

    tokens = extract_tokens(line)

    if len(tokens) < 8:
        return None, None, None, None, None

    actual = parse_number(tokens[5])
    budget = parse_number(tokens[6])
    ly = parse_number(tokens[7])

    vs_budget = safe_pct(actual, budget)
    vs_ly = safe_pct(actual, ly)

    return actual, budget, ly, vs_budget, vs_ly

def extract_doc_date(first_page_text: str):
    """
    Дата из верхнего левого колонтитула:
    ищем только в первых строках первой страницы.
    """
    lines = split_lines(first_page_text)
    header_lines = lines[:8]

    for line in header_lines:
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

# =====================
# PARSER
# =====================
def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        first_page_text = ""
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            txt = normalize_spaces(txt)
            if i == 0:
                first_page_text = txt
            pages.append(txt)
        text = "\n".join(pages)

    doc_date = extract_doc_date(first_page_text)
    hotel = detect_hotel(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast"])
    total_fb_lines = get_section_lines(text, ["total f&b", "m&e revenue"], ["total spa"])
    hotel_total_lines = get_section_lines(text, ["hotel total"], ["month", "year"])
    if not hotel_total_lines:
        hotel_total_lines = get_section_lines(text, ["hotel total"])

    data = {}

    line = find_first_line(accommodation_lines, startswith="revpar")
    data["RevPAR"] = extract_month_accum_values(line)

    line = find_first_line(total_fb_lines, startswith="total revenue")
    data["FB_TotalRevenue"] = extract_month_accum_values(line)

    line = find_first_line(total_fb_lines, includes=["rev.", "wtrs. hour"])
    data["ServiceHour"] = extract_month_accum_values(line)

    line = find_first_line(total_fb_lines, includes=["rev.", "ktch. hour"])
    data["KitchenHour"] = extract_month_accum_values(line)

    line = find_first_line(hotel_total_lines, startswith="total revenue")
    data["HotelTotalRevenue"] = extract_month_accum_values(line)

    return doc_date, hotel, data

# =====================
# HISTORY
# =====================
def save_history(doc_date, hotel, data):
    row = {
        "date": doc_date,
        "hotel": hotel,
        "RevPAR": data["RevPAR"][0],
        "F&B Total revenue": data["FB_TotalRevenue"][0],
        "Service / wtrs. hour": data["ServiceHour"][0],
        "Kitchen / ktch. hour": data["KitchenHour"][0],
        "Hotel Total revenue": data["HotelTotalRevenue"][0],
    }

    new_df = pd.DataFrame([row])

    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE)

        for col in new_df.columns:
            if col not in df.columns:
                df[col] = pd.NA

        df = df[~((df["date"] == doc_date) & (df["hotel"] == hotel))]
        df = pd.concat([df, new_df], ignore_index=True)
    else:
        df = new_df

    df.to_csv(HISTORY_FILE, index=False)

def load_history():
    if os.path.exists(HISTORY_FILE):
        return pd.read_csv(HISTORY_FILE)
    return pd.DataFrame()

# =====================
# SUMMARY
# =====================
def build_summary(data):
    notes = []

    hotel_total_vs_ly = data["HotelTotalRevenue"][4]
    hotel_total_vs_budget = data["HotelTotalRevenue"][3]
    revpar_vs_ly = data["RevPAR"][4]
    fb_total_vs_ly = data["FB_TotalRevenue"][4]
    service_vs_ly = data["ServiceHour"][4]
    kitchen_vs_ly = data["KitchenHour"][4]

    if hotel_total_vs_ly is not None:
        if hotel_total_vs_ly < 0:
            notes.append(("Общая выручка отеля ниже прошлого года.", "bad"))
        elif hotel_total_vs_ly < 8:
            notes.append(("Общая выручка отеля растёт, но слабее ожидаемого темпа.", "warn"))
        else:
            notes.append(("Общая выручка отеля показывает сильный рост к прошлому году.", "good"))

    if hotel_total_vs_budget is not None:
        if hotel_total_vs_budget < 0:
            notes.append(("Факт отеля ниже бюджета месяца.", "bad"))
        else:
            notes.append(("Факт отеля держится выше бюджета месяца.", "good"))

    if revpar_vs_ly is not None:
        if revpar_vs_ly < 0:
            notes.append(("RevPAR ниже прошлого года.", "bad"))
        else:
            notes.append(("RevPAR выше прошлого года.", "good"))

    if fb_total_vs_ly is not None:
        if fb_total_vs_ly < 0:
            notes.append(("F&B total revenue проседает к прошлому году.", "bad"))
        else:
            notes.append(("F&B total revenue растёт к прошлому году.", "good"))

    if service_vs_ly is not None and kitchen_vs_ly is not None:
        if service_vs_ly > kitchen_vs_ly:
            notes.append(("Эффективность сервиса растёт быстрее кухни.", "good"))
        elif kitchen_vs_ly > service_vs_ly:
            notes.append(("Эффективность кухни растёт быстрее сервиса.", "good"))
        else:
            notes.append(("Кухня и сервис показывают схожую динамику.", "warn"))

    return notes

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
            f"""
            <div class="summary-box" style="border-left: 4px solid {color}; background: {bg}; color: {color};">
                {text}
            </div>
            """,
            unsafe_allow_html=True
        )

# =====================
# UI
# =====================
def show_metric_block(col, section_name, title, metric_name, values):
    actual, budget, ly, vs_budget, vs_ly = values
    color_budget = get_color_for_delta(vs_budget)
    color_ly = get_color_for_delta(vs_ly)

    with col:
        st.markdown(f"**{section_name}**")
        st.markdown(f"<div class='small-note'>{title}</div>", unsafe_allow_html=True)
        st.metric(label=" ", value=format_value(metric_name, actual))
        st.markdown(
            f"<span style='color:{color_budget}; font-weight:700;'>vs Bu. Accum.: {format_pct(vs_budget)}</span>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<span style='color:{color_ly}; font-weight:700;'>vs LY. Accum.: {format_pct(vs_ly)}</span>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<span class='small-note'>Bu: {format_value(metric_name, budget)} | LY: {format_value(metric_name, ly)}</span>",
            unsafe_allow_html=True
        )

st.markdown("""
<div class="hero-box">
    <div class="hero-title">ChefBrain</div>
    <div class="hero-subtitle">Month → Accum. vs Bu. Accum. и LY. Accum.</div>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Загрузи PDF отчёт", type=["pdf"])

if uploaded_file:
    doc_date, hotel, data = parse_pdf(uploaded_file)
    save_history(doc_date, hotel, data)

    st.subheader(f"Отель: {hotel} · Дата документа: {doc_date}")

    c1, c2, c3 = st.columns(3)
    c4, c5 = st.columns(2)

    show_metric_block(c1, "ACCOMMODATION", "RevPAR", "RevPAR", data["RevPAR"])
    show_metric_block(c2, "TOTAL F&B, M&E REVENUE", "Total revenue", "FB_TotalRevenue", data["FB_TotalRevenue"])
    show_metric_block(c3, "TOTAL F&B, M&E REVENUE", "Rev. / wtrs. Hour", "ServiceHour", data["ServiceHour"])
    show_metric_block(c4, "TOTAL F&B, M&E REVENUE", "Rev. / ktch. Hour", "KitchenHour", data["KitchenHour"])
    show_metric_block(c5, "HOTEL TOTAL", "Total revenue", "HotelTotalRevenue", data["HotelTotalRevenue"])

    render_summary_block(build_summary(data))

st.markdown("---")
st.subheader("История")

history = load_history()
if history.empty:
    st.write("Нет данных")
else:
    st.dataframe(history, use_container_width=True)