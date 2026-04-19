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

    # И запятая, и точка: вероятно тысячи через запятую, дробная часть через точку
    if "," in s and "." in s:
        s = s.replace(",", "")
        try:
            return float(s)
        except Exception:
            return None

    # Только запятая: или тысячи, или десятичный разделитель
    if "," in s and "." not in s:
        parts = s.split(",")

        # 24,082,425 -> тысячи
        if len(parts) > 1 and all(p.isdigit() for p in parts) and all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
            try:
                return float(s)
            except Exception:
                return None

        # 66,1 -> дробное число
        s = s.replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None

    # Только точка
    if "." in s:
        try:
            return float(s)
        except Exception:
            return None

    # Пробелы в тысячах
    s = s.replace(" ", "")
    try:
        return float(s)
    except Exception:
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
    """
    В отчётах структура строки обычно такая:
    day act | day bud | day ly | bud ind | ly ind | MTD act | MTD bud | MTD ly | bud ind | ly ind | ...
    Нам нужно:
    - MTD actual = 6-е число
    - индекс к LY = 10-е число
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

# =====================
# PARSER
# =====================
def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        for page in pdf.pages:
            txt = page.extract_text() or ""
            pages.append(normalize_spaces(txt))
        text = "\n".join(pages)

    hotel = detect_hotel(text)

    # Универсальные блоки
    accommodation = extract_section(text, "ACCOMMODATION 3675", "BREAKFAST 3675") or text
    breakfast_sec = extract_section(text, "BREAKFAST 3675", "MEETING & EVENTS") or text

    total_kitchen_sec = extract_section(text, "TOTAL KITCHEN", "TOTAL F&B, M&E REVENUE") or text
    total_fb_sec = extract_section(text, "TOTAL F&B, M&E REVENUE", "HOTEL TOTAL") or text
    hotel_total_sec = extract_section(text, "HOTEL TOTAL", "Month Year") or extract_section(text, "HOTEL TOTAL") or text

    data = {}

    # Берём MTD и LY index
    data["Revenue"] = extract_mtd_and_ly_index(find_line(hotel_total_sec, "Total revenue"))
    data["Breakfast"] = extract_mtd_and_ly_index(find_line(breakfast_sec, "Total revenue"))
    data["Occupancy"] = extract_mtd_and_ly_index(find_line(accommodation, "Occ-%"))
    data["RevPAR"] = extract_mtd_and_ly_index(find_line(accommodation, "RevPAR"))
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
# LOGIC
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

    if kitchen_idx is not None and kitchen_idx < 0:
        notes.append(("Эффективность кухни снижается.", "bad"))

    if waiter_idx is not None and waiter_idx < 0:
        notes.append(("Эффективность сервиса снижается.", "bad"))

    return notes

def get_indicator(idx):
    if idx is None or pd.isna(idx):
        return "•", "#9CA3AF", "нет данных"
    if idx < 0:
        return "▼", "#EF4444", "ниже LY"
    if idx < 8:
        return "▲", "#F59E0B", "ниже инфляции"
    return "▲", "#22C55E", "выше инфляции"

def get_status_name(idx):
    if idx is None or pd.isna(idx):
        return "Нет данных"
    if idx < 0:
        return "Критично"
    if idx < 8:
        return "Риск"
    return "Рост"

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

def latest_rows_by_hotel(df):
    if df.empty:
        return pd.DataFrame()

    return (
        df.sort_values("date")
          .groupby("hotel", as_index=False)
          .tail(1)
          .sort_values("hotel")
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
st.subheader("Сравнение отелей")

if history.empty:
    st.info("История пока пуста. Загрузите хотя бы по одному отчёту для каждого отеля.")
else:
    latest = latest_rows_by_hotel(history)

    if latest.empty:
        st.info("Пока недостаточно данных для сравнения.")
    else:
        # Таблица последних значений
        display_cols = [
            "hotel", "date",
            "Revenue_idx", "Breakfast_idx", "Occupancy_idx",
            "RevPAR_idx", "Kitchen_idx", "Waiter_idx"
        ]
        existing_cols = [c for c in display_cols if c in latest.columns]
        latest_display = latest[existing_cols].copy()

        rename_map = {
            "hotel": "Hotel",
            "date": "Date",
            "Revenue_idx": "Revenue %",
            "Breakfast_idx": "Breakfast %",
            "Occupancy_idx": "Occupancy %",
            "RevPAR_idx": "RevPAR %",
            "Kitchen_idx": "Kitchen %",
            "Waiter_idx": "Service %",
        }
        latest_display = latest_display.rename(columns=rename_map)

        st.dataframe(latest_display, use_container_width=True, hide_index=True)

        # Статус по отелям
        st.subheader("Статус по отелям")
        cols = st.columns(3)
        rows = latest[["hotel", "Revenue_idx"]].sort_values("hotel").values.tolist()

        for i, row in enumerate(rows[:3]):
            hotel_name, idx = row[0], row[1]
            arrow, color, label = get_indicator(idx)
            status_name = get_status_name(idx)

            with cols[i]:
                st.markdown(f"**{hotel_name}**")
                st.metric(label="", value=status_name, delta=None)
                st.markdown(
                    f"<span style='color:{color}; font-weight:700; font-size:18px;'>{arrow} {format_idx(idx)}</span>",
                    unsafe_allow_html=True
                )
                st.markdown(f"<span class='small-label'>{label}</span>", unsafe_allow_html=True)

        # График Revenue по отелям
        st.subheader("Revenue: сравнение отелей")
        if {"date", "hotel", "Revenue_idx"}.issubset(history.columns):
            pivot = history.pivot_table(index="date", columns="hotel", values="Revenue_idx", aggfunc="last")
            if pivot.shape[1] > 0:
                st.line_chart(pivot)
            else:
                st.info("Пока недостаточно данных для графика Revenue.")

        # График RevPAR по отелям
        st.subheader("RevPAR: сравнение отелей")
        if {"date", "hotel", "RevPAR_idx"}.issubset(history.columns):
            pivot = history.pivot_table(index="date", columns="hotel", values="RevPAR_idx", aggfunc="last")
            if pivot.shape[1] > 0:
                st.line_chart(pivot)
            else:
                st.info("Пока недостаточно данных для графика RevPAR.")

st.markdown("---")

st.subheader("История")

if history.empty:
    st.write("Нет данных")
else:
    hotel_filter = st.selectbox(
        "Фильтр по отелю",
        ["Все отели"] + sorted(history["hotel"].dropna().unique().tolist())
    )

    filtered = history.copy()
    if hotel_filter != "Все отели":
        filtered = filtered[filtered["hotel"] == hotel_filter]

    st.dataframe(filtered, use_container_width=True)

    if not filtered.empty:
        st.subheader("Динамика Revenue")
        if "Revenue_idx" in filtered.columns:
            if hotel_filter == "Все отели":
                pivot = filtered.pivot_table(index="date", columns="hotel", values="Revenue_idx", aggfunc="last")
                if pivot.shape[1] > 0:
                    st.line_chart(pivot)
            else:
                st.line_chart(filtered.set_index("date")["Revenue_idx"])

        st.subheader("Динамика RevPAR / Occupancy")
        cols_to_show = [c for c in ["RevPAR_idx", "Occupancy_idx"] if c in filtered.columns]
        if cols_to_show:
            if hotel_filter == "Все отели":
                metric = st.selectbox("Показатель для сравнения", cols_to_show, index=0)
                pivot = filtered.pivot_table(index="date", columns="hotel", values=metric, aggfunc="last")
                if pivot.shape[1] > 0:
                    st.line_chart(pivot)
            else:
                st.line_chart(filtered.set_index("date")[cols_to_show])
