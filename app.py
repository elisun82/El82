import os
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

HISTORY_FILE = "history_palace.csv"
INFLATION = 8.0
HOTEL_NAME = "PALACE BRIDGE"

st.set_page_config(page_title="ChefBrain Palace", layout="wide")

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
    font-size: 34px;
    font-weight: 800;
    color: #F9FAFB;
    margin-bottom: 6px;
}
.hero-subtitle {
    color: #9CA3AF;
    font-size: 14px;
}
.small-label {
    color: #94A3B8;
    font-size: 12px;
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
        except Exception:
            return None

    if "," in s and "." not in s:
        parts = s.split(",")

        # 24,082,425
        if len(parts) > 1 and all(p.isdigit() for p in parts) and all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
            try:
                return float(s)
            except Exception:
                return None

        # 87,2
        s = s.replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None

    if "." in s:
        try:
            return float(s)
        except Exception:
            return None

    s = s.replace(" ", "")
    try:
        return float(s)
    except Exception:
        return None

def split_lines(text: str):
    return [line.strip() for line in text.splitlines() if line.strip()]

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

def find_last_line(lines, includes=None, startswith=None):
    includes = [x.lower() for x in (includes or [])]
    startswith = startswith.lower() if startswith else None

    for line in reversed(lines):
        low = line.lower()
        if startswith and not low.startswith(startswith):
            continue
        if includes and not all(x in low for x in includes):
            continue
        return line
    return None

def extract_mtd_and_ly_index(line):
    """
    day act | day bud | day ly | bud ind | ly ind | MTD act | MTD bud | MTD ly | bud ind | ly ind
    """
    if not line:
        return None, None

    cleaned = (
        line.replace("RUR", "")
            .replace("%", "")
            .replace("\xa0", " ")
            .strip()
    )

    tokens = re.findall(r"\d[\d\s,]*(?:[.,]\d+)?", cleaned)
    tokens = [t.strip() for t in tokens if t.strip()]

    if len(tokens) < 10:
        return None, None

    mtd_actual = parse_number(tokens[5])

    idx_token = tokens[9].replace(" ", "")
    if "," in idx_token and "." in idx_token:
        idx_token = idx_token.replace(",", "")
    else:
        idx_token = idx_token.replace(",", ".")

    try:
        ly_index_ratio = float(idx_token)
    except Exception:
        ly_index_ratio = None

    ly_index_pct = round((ly_index_ratio - 1.0) * 100, 1) if ly_index_ratio is not None else None
    return mtd_actual, ly_index_pct

def format_value(metric_name: str, value):
    if value is None or pd.isna(value):
        return "нет данных"
    if metric_name == "Occupancy":
        return f"{value:.1f}%"
    return f"{value:,.0f}".replace(",", " ")

def format_idx(idx):
    if idx is None or pd.isna(idx):
        return "нет данных"
    return f"{idx:+.1f}%"

def get_indicator(idx):
    if idx is None or pd.isna(idx):
        return "•", "#9CA3AF", "нет данных"
    if idx < 0:
        return "▼", "#EF4444", "ниже LY"
    if idx < 8:
        return "▲", "#F59E0B", "ниже инфляции"
    return "▲", "#22C55E", "выше инфляции"


# =====================
# PALACE PARSER
# =====================
def parse_palace_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        for page in pdf.pages:
            txt = page.extract_text() or ""
            pages.append(normalize_spaces(txt))
        text = "\n".join(pages)

    all_lines = split_lines(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast"])
    breakfast_lines = get_section_lines(text, ["breakfast"], ["meeting", "events"])
    if not breakfast_lines:
        breakfast_lines = get_section_lines(text, ["breakfast"], ["total kitchen"])

    total_fb_lines = get_section_lines(text, ["total f&b", "m&e revenue"], ["total spa"])
    total_kitchen_lines = get_section_lines(text, ["total kitchen"], ["total f&b", "m&e revenue"])

    data = {}

    # Revenue = Room Revenue from ACCOMMODATION
    revenue_line = find_first_line(accommodation_lines, startswith="room revenue")
    data["Revenue"] = extract_mtd_and_ly_index(revenue_line)

    # Breakfast = Total revenue from BREAKFAST
    breakfast_line = find_first_line(breakfast_lines, startswith="total revenue")
    data["Breakfast"] = extract_mtd_and_ly_index(breakfast_line)

    # Occupancy / RevPAR from ACCOMMODATION
    occupancy_line = find_first_line(accommodation_lines, startswith="occ-%")
    revpar_line = find_first_line(accommodation_lines, startswith="revpar")
    data["Occupancy"] = extract_mtd_and_ly_index(occupancy_line)
    data["RevPAR"] = extract_mtd_and_ly_index(revpar_line)

    # Kitchen = TOTAL KITCHEN -> Rev. / efficient hour, fallback global last
    kitchen_line = find_first_line(total_kitchen_lines, includes=["rev.", "efficient hour"])
    if not kitchen_line:
        kitchen_line = find_last_line(all_lines, includes=["rev.", "efficient hour"])
    data["Kitchen"] = extract_mtd_and_ly_index(kitchen_line)

    # Service = TOTAL F&B -> Rev. / wtrs. Hour, fallback BREAKFAST, then global last
    waiter_line = find_first_line(total_fb_lines, includes=["rev.", "wtrs. hour"])
    if not waiter_line:
        waiter_line = find_first_line(breakfast_lines, includes=["rev.", "wtrs. hour"])
    if not waiter_line:
        waiter_line = find_last_line(all_lines, includes=["rev.", "wtrs. hour"])
    data["Waiter"] = extract_mtd_and_ly_index(waiter_line)

    return HOTEL_NAME, data


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
        return pd.read_csv(HISTORY_FILE)
    return pd.DataFrame()


# =====================
# SUMMARY
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
    else:
        notes.append(("Нет данных по индексу общей выручки.", "warn"))

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

    return notes

def render_summary_block(notes):
    if not notes:
        return

    st.subheader("Вывод")

    color_map = {
        "good": ("#22C55E", "rgba(34,197,94,0.12)"),
        "warn": ("#F59E0B", "rgba(245,158,11,0.12)"),
        "bad":  ("#EF4444", "rgba(239,68,68,0.12)")
    }

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

def show_metric(col, name, metric_key, data):
    value, idx = data[metric_key]
    arrow, color, label = get_indicator(idx)
    value_str = format_value(name, value)
    idx_str = format_idx(idx)

    with col:
        st.markdown(f"**{name}**")
        st.metric(label="", value=value_str, delta=None)
        st.markdown(
            f"<span style='color:{color}; font-weight:700; font-size:18px;'>{arrow} {idx_str}</span>",
            unsafe_allow_html=True
        )
        st.markdown(f"<span class='small-label'>{label}</span>", unsafe_allow_html=True)


# =====================
# UI
# =====================
st.markdown("""
<div class="hero-box">
    <div class="hero-title">ChefBrain — PALACE BRIDGE</div>
    <div class="hero-subtitle">Версия, заточенная только под отчёт Palace Bridge.</div>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Загрузи PDF Palace Bridge", type=["pdf"])

if uploaded_file:
    hotel, data = parse_palace_pdf(uploaded_file)
    save_history(hotel, data)

    st.subheader(f"Отель: {hotel}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    show_metric(c1, "Revenue", "Revenue", data)
    show_metric(c2, "Breakfast", "Breakfast", data)
    show_metric(c3, "Occupancy", "Occupancy", data)
    show_metric(c4, "RevPAR", "RevPAR", data)
    show_metric(c5, "Kitchen", "Kitchen", data)
    show_metric(c6, "Service", "Waiter", data)

    render_summary_block(build_summary(data))

st.markdown("---")
history = load_history()

st.subheader("История Palace Bridge")

if history.empty:
    st.write("Нет данных")
else:
    st.dataframe(history, use_container_width=True)