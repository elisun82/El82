import os
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

# =====================
# SETTINGS
# =====================
HISTORY_FILE = "history.csv"
INFLATION = 8.0
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]

st.set_page_config(page_title="ChefBrain", layout="wide")

# =====================
# STYLES
# =====================
st.markdown("""
<style>
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1400px;
}
.hero-box {
    background: linear-gradient(180deg, #101828 0%, #0B1220 100%);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 20px;
    padding: 20px 24px;
    margin-bottom: 18px;
}
.hero-title {
    font-size: 36px;
    font-weight: 800;
    color: #F9FAFB;
    margin-bottom: 6px;
}
.hero-subtitle {
    color: #9CA3AF;
    font-size: 14px;
}
.metric-card {
    background: linear-gradient(180deg, #111827 0%, #0B1220 100%);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px;
    padding: 18px 18px 14px 18px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.22);
    min-height: 150px;
}
.metric-title {
    font-size: 14px;
    color: #9CA3AF;
    margin-bottom: 10px;
}
.metric-value {
    font-size: 22px;
    font-weight: 700;
    color: #F9FAFB;
    margin-bottom: 14px;
}
.metric-delta {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 15px;
    font-weight: 700;
    background: rgba(255,255,255,0.03);
    border-radius: 999px;
    padding: 6px 10px;
}
.metric-label {
    margin-top: 10px;
    font-size: 12px;
    color: #9CA3AF;
}
.summary-box {
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 10px;
    color: #F3F4F6;
    font-size: 15px;
}
</style>
""", unsafe_allow_html=True)

# =====================
# HELPERS
# =====================
def normalize_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "")

def parse_number(value):
    if value is None:
        return None

    s = str(value).strip().replace("RUR", "").replace("%", "").strip()

    if "," in s and "." in s:
        s = s.replace(",", "")
        try:
            return float(s)
        except:
            return None

    if "," in s and "." not in s:
        parts = s.split(",")

        if len(parts) > 1 and all(p.isdigit() for p in parts) and all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
            try:
                return float(s)
            except:
                return None

        s = s.replace(",", ".")
        try:
            return float(s)
        except:
            return None

    if "." in s:
        try:
            return float(s)
        except:
            return None

    s = s.replace(" ", "")
    try:
        return float(s)
    except:
        return None

def detect_hotel(text: str) -> str:
    upper = text.upper()
    for hotel in HOTELS:
        if hotel in upper:
            return hotel
    return "UNKNOWN"

def extract_section(text: str, start_label: str, end_label: str = None):
    start = text.find(start_label)
    if start == -1:
        return None
    if end_label:
        end = text.find(end_label, start + len(start_label))
        if end != -1:
            return text[start:end]
    return text[start:]

def find_line(text: str, label: str):
    pattern = rf"^{re.escape(label)}.*$"
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(0) if match else None

def extract_mtd_and_ly_index(line):
    if not line:
        return None, None

    nums = re.findall(r"\d[\d ,]*\.?\d*", line)
    nums = [n.strip() for n in nums if n.strip()]

    if len(nums) < 10:
        return None, None

    mtd_actual = parse_number(nums[5])
    ly_index_ratio = parse_number(nums[9])

    if ly_index_ratio is None:
        ly_index_pct = None
    else:
        ly_index_pct = round((ly_index_ratio - 1.0) * 100, 1)

    return mtd_actual, ly_index_pct

def format_value(metric_name: str, value):
    if value is None or pd.isna(value):
        return "нет данных"

    if metric_name == "Occupancy":
        return f"{value:.1f}%"

    return f"{value:,.0f}".replace(",", " ")

# =====================
# PDF PARSER
# =====================
def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        for page in pdf.pages:
            txt = page.extract_text() or ""
            pages.append(normalize_spaces(txt))
        text = "\n".join(pages)

    hotel = detect_hotel(text)

    # Универсальнее, чем по точным ID
    accommodation = extract_section(text, "ACCOMMODATION 3675", "BREAKFAST 3675") or text
    breakfast_sec = extract_section(text, "BREAKFAST 3675", "MEETING & EVENTS") or text

    total_kitchen_sec = extract_section(text, "TOTAL KITCHEN", "TOTAL F&B, M&E REVENUE") or text
    total_fb_sec = extract_section(text, "TOTAL F&B, M&E REVENUE", "HOTEL TOTAL") or text
    hotel_total_sec = extract_section(text, "HOTEL TOTAL", "Month Year") or extract_section(text, "HOTEL TOTAL") or text

    data = {}

    # Выручка отеля
    data["Revenue"] = extract_mtd_and_ly_index(find_line(hotel_total_sec, "Total revenue"))

    # Завтрак
    data["Breakfast"] = extract_mtd_and_ly_index(find_line(breakfast_sec, "Total revenue"))

    # Загрузка
    data["Occupancy"] = extract_mtd_and_ly_index(find_line(accommodation, "Occ-%"))

    # RevPAR
    data["RevPAR"] = extract_mtd_and_ly_index(find_line(accommodation, "RevPAR"))

    # Кухня и сервис из итоговых блоков
    data["Kitchen"] = extract_mtd_and_ly_index(find_line(total_kitchen_sec, "Rev. / efficient hour"))
    data["Waiter"] = extract_mtd_and_ly_index(find_line(total_fb_sec, "Rev. / wtrs. Hour"))

    return hotel, data

# =====================
# HISTORY
# =====================
def save_history(hotel, data):
    today = datetime.now().strftime("%Y-%m-%d")

    row = {"date": today, "hotel": hotel}
    for metric, values in data.items():
        row[f"{metric}_mtd"] = values[0]
        row[f"{metric}_idx"] = values[1]

    new_df = pd.DataFrame([row])

    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE)

        if "hotel" not in df.columns:
            df["hotel"] = "UNKNOWN"
        if "date" not in df.columns:
            df["date"] = ""

        for col in new_df.columns:
            if col not in df.columns:
                df[col] = pd.NA

        df = df[~((df["date"] == today) & (df["hotel"] == hotel))]
        df = pd.concat([df, new_df], ignore_index=True)
    else:
        df = new_df

    df.to_csv(HISTORY_FILE, index=False)

def load_history():
    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE)
        if "hotel" not in df.columns:
            df["hotel"] = "UNKNOWN"
        if "date" not in df.columns:
            df["date"] = ""
        return df

    return pd.DataFrame()

# =====================
# SUMMARY + UI HELPERS
# =====================
def build_summary(data):
    notes = []

    revenue_idx = data["Revenue"][1]
    breakfast_idx = data["Breakfast"][1]
    occupancy_idx = data["Occupancy"][1]
    revpar_idx = data["RevPAR"][1]
    kitchen_idx = data["Kitchen"][1]
    waiter_idx = data["Waiter"][1]

    if revenue_idx is not None:
        if revenue_idx < 0:
            notes.append(("Выручка ниже прошлого года.", "bad"))
        elif revenue_idx < 8:
            notes.append(("Выручка растёт, но не перекрывает инфляцию 8%.", "warn"))
        else:
            notes.append(("Выручка растёт выше инфляции.", "good"))

    if revpar_idx is not None and occupancy_idx is not None:
        if revpar_idx > occupancy_idx:
            notes.append(("Рост идёт скорее через цену, а не через загрузку.", "warn"))
        elif occupancy_idx > revpar_idx:
            notes.append(("Рост идёт скорее через загрузку, чем через цену.", "good"))
        else:
            notes.append(("Цена и загрузка растут сбалансированно.", "good"))

    if breakfast_idx is not None:
        if breakfast_idx < 0:
            notes.append(("Завтрак просел к прошлому году.", "bad"))
        elif breakfast_idx < 8:
            notes.append(("Завтрак растёт ниже инфляции.", "warn"))
        else:
            notes.append(("Завтрак растёт стабильно.", "good"))

    if kitchen_idx is not None and waiter_idx is not None:
        if kitchen_idx > waiter_idx:
            notes.append(("Кухня эффективнее сервиса.", "good"))
        elif waiter_idx > kitchen_idx:
            notes.append(("Сервис эффективнее кухни.", "good"))
        else:
            notes.append(("Кухня и сервис на одном уровне.", "good"))

    if kitchen_idx is not None and kitchen_idx < 0:
        notes.append(("Эффективность кухни снижается.", "bad"))

    if waiter_idx is not None and waiter_idx < 0:
        notes.append(("Эффективность сервиса снижается.", "bad"))

    if not notes:
        notes.append(("Критичных отклонений не найдено.", "good"))

    return notes

def get_indicator(idx):
    if idx is None or pd.isna(idx):
        return "•", "#9CA3AF", "нет данных"

    if idx < 0:
        return "▼", "#EF4444", "ниже LY"
    elif idx < 8:
        return "▲", "#F59E0B", "ниже инфляции"
    else:
        return "▲", "#22C55E", "выше инфляции"

def render_metric_card(title, value_str, idx):
    arrow, color, label = get_indicator(idx)
    idx_text = "нет данных" if idx is None or pd.isna(idx) else f"{idx:+.1f}%"

    html = f"""
<div class="metric-card">
    <div class="metric-title">{title}</div>
    <div class="metric-value">{value_str}</div>

    <div class="metric-delta" style="color: {color};">
        <span style="font-size: 16px;">{arrow}</span>
        <span>{idx_text}</span>
    </div>

    <div class="metric-label">{label}</div>
</div>
"""
    st.markdown(html, unsafe_allow_html=True)

def render_summary_block(notes):
    color_map = {
        "good": ("#22C55E", "rgba(34,197,94,0.12)"),
        "warn": ("#F59E0B", "rgba(245,158,11,0.12)"),
        "bad":  ("#EF4444", "rgba(239,68,68,0.12)")
    }

    st.subheader("Вывод")

    for text, level in notes:
        border, bg = color_map.get(level, ("#6B7280", "rgba(107,114,128,0.12)"))
        st.markdown(
            f"""
            <div class="summary-box" style="border-left: 4px solid {border}; background: {bg};">
                {text}
            </div>
            """,
            unsafe_allow_html=True
        )

# =====================
# UI
# =====================
st.markdown("""
<div class="hero-box">
    <div class="hero-title">ChefBrain</div>
    <div class="hero-subtitle">Загрузи PDF-отчёт, получи MTD-факт, индекс к прошлому году и управленческий вывод.</div>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Загрузи PDF", type=["pdf"])

if uploaded_file:
    hotel, data = parse_pdf(uploaded_file)
    save_history(hotel, data)

    st.subheader(f"Отель: {hotel}")

    c1, c2, c3 = st.columns(3)
    with c1:
        render_metric_card("Revenue", format_value("Revenue", data["Revenue"][0]), data["Revenue"][1])
    with c2:
        render_metric_card("Breakfast", format_value("Breakfast", data["Breakfast"][0]), data["Breakfast"][1])
    with c3:
        render_metric_card("Occupancy", format_value("Occupancy", data["Occupancy"][0]), data["Occupancy"][1])

    c4, c5, c6 = st.columns(3)
    with c4:
        render_metric_card("RevPAR", format_value("RevPAR", data["RevPAR"][0]), data["RevPAR"][1])
    with c5:
        render_metric_card("Kitchen", format_value("Kitchen", data["Kitchen"][0]), data["Kitchen"][1])
    with c6:
        render_metric_card("Service", format_value("Waiter", data["Waiter"][0]), data["Waiter"][1])

    render_summary_block(build_summary(data))

history = load_history()

st.subheader("История")

if history.empty:
    st.write("Нет данных")
else:
    st.dataframe(history, use_container_width=True)

    hotel_filter = st.selectbox(
        "Фильтр по отелю",
        ["Все отели"] + sorted(history["hotel"].dropna().unique().tolist())
    )

    filtered = history.copy()
    if hotel_filter != "Все отели":
        filtered = filtered[filtered["hotel"] == hotel_filter]

    if not filtered.empty:
        st.subheader("Динамика Revenue")
        if "Revenue_idx" in filtered.columns:
            st.line_chart(filtered.set_index("date")["Revenue_idx"])

        st.subheader("Динамика RevPAR / Occupancy")
        cols_to_show = [c for c in ["RevPAR_idx", "Occupancy_idx"] if c in filtered.columns]
        if cols_to_show:
            st.line_chart(filtered.set_index("date")[cols_to_show])
