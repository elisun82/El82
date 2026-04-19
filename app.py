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
# HELPERS
# =====================
def normalize_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "")

def parse_number(value):
    if value is None:
        return None

    s = str(value).strip().replace("RUR", "").replace("%", "").strip()

    # Если есть и точка, и запятая:
    # считаем, что запятая = разделитель тысяч, точка = десятичная часть
    # пример: 18,343,087  /  1.03
    if "," in s and "." in s:
        s = s.replace(",", "")
        try:
            return float(s)
        except:
            return None

    # Если есть только запятая:
    # различаем:
    # 1) 24,082,425 -> тысячи
    # 2) 87,2 -> десятичное
    if "," in s and "." not in s:
        parts = s.split(",")

        # если после запятой 3 цифры и таких групп несколько -> это тысячи
        if len(parts) > 1 and all(p.isdigit() for p in parts) and all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
            try:
                return float(s)
            except:
                return None

        # иначе считаем запятую десятичным разделителем
        s = s.replace(",", ".")
        try:
            return float(s)
        except:
            return None

    # Если есть только точка:
    # может быть 1.03 или 66.1
    if "." in s:
        try:
            return float(s)
        except:
            return None

    # Если есть пробелы в тысячах
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

def status_icon(idx):
    if idx is None or pd.isna(idx):
        return "⚪"
    if idx > INFLATION:
        return "🟢"
    if idx > 0:
        return "🟡"
    return "🔴"

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

    accommodation = extract_section(text, "ACCOMMODATION 3675010", "BREAKFAST 3675014") or text
    breakfast_sec = extract_section(text, "BREAKFAST 3675014", "PB MEETING & EVENTS 3675011") or text

    # Новый источник для кухни / сервиса / total revenue
    total_fb_sec = extract_section(text, "TOTAL F&B, M&E REVENUE", "TOTAL SPA") or text
    hotel_total_sec = extract_section(text, "HOTEL TOTAL", "3/3") or extract_section(text, "HOTEL TOTAL") or text

    data = {}

    # ИТОГО ВЫРУЧКА — теперь из HOTEL TOTAL
    data["Revenue"] = extract_mtd_and_ly_index(find_line(hotel_total_sec, "Total revenue"))

    # Завтрак — остаётся из блока BREAKFAST
    data["Breakfast"] = extract_mtd_and_ly_index(find_line(breakfast_sec, "Total revenue"))

    # Загрузка — остаётся из ACCOMMODATION
    data["Occupancy"] = extract_mtd_and_ly_index(find_line(accommodation, "Occ-%"))

    # RevPAR — остаётся из ACCOMMODATION
    data["RevPAR"] = extract_mtd_and_ly_index(find_line(accommodation, "RevPAR"))

    # КУХНЯ — теперь из TOTAL F&B, M&E REVENUE
    data["Kitchen"] = extract_mtd_and_ly_index(find_line(total_fb_sec, "Rev. / ktch. hour"))

    # СЕРВИС — теперь из TOTAL F&B, M&E REVENUE
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

    if revenue_idx is not None and revenue_idx < INFLATION:
        notes.append("Критично: выручка не перекрывает инфляцию.")

    if revpar_idx is not None and occupancy_idx is not None and revpar_idx > occupancy_idx:
        notes.append("Рост идёт за счёт цены, а не загрузки.")

    if breakfast_idx is not None and breakfast_idx < INFLATION:
        notes.append("Завтрак растёт ниже инфляции.")

    if kitchen_idx is not None and waiter_idx is not None:
        if kitchen_idx > waiter_idx:
            notes.append("Эффективность кухни выше сервиса.")
        elif waiter_idx > kitchen_idx:
            notes.append("Эффективность сервиса выше кухни.")

    if not notes:
        notes.append("Критичных отклонений не найдено.")

    return notes

# =====================
# UI
# =====================
st.title("ChefBrain")

uploaded_file = st.file_uploader("Загрузи PDF", type=["pdf"])

if uploaded_file:
    hotel, data = parse_pdf(uploaded_file)
    save_history(hotel, data)

    st.subheader(f"Отель: {hotel}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Revenue", format_value("Revenue", data["Revenue"][0]), f"{status_icon(data['Revenue'][1])} {data['Revenue'][1]}%")
    c2.metric("Breakfast", format_value("Breakfast", data["Breakfast"][0]), f"{status_icon(data['Breakfast'][1])} {data['Breakfast'][1]}%")
    c3.metric("Occupancy", format_value("Occupancy", data["Occupancy"][0]), f"{status_icon(data['Occupancy'][1])} {data['Occupancy'][1]}%")

    c4, c5, c6 = st.columns(3)
    c4.metric("RevPAR", format_value("RevPAR", data["RevPAR"][0]), f"{status_icon(data['RevPAR'][1])} {data['RevPAR'][1]}%")
    c5.metric("Kitchen", format_value("Kitchen", data["Kitchen"][0]), f"{status_icon(data['Kitchen'][1])} {data['Kitchen'][1]}%")
    c6.metric("Waiter", format_value("Waiter", data["Waiter"][0]), f"{status_icon(data['Waiter'][1])} {data['Waiter'][1]}%")

    st.subheader("Вывод")
    for note in build_summary(data):
        st.write(f"• {note}")

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
        st.line_chart(filtered.set_index("date")["Revenue_idx"])

        st.subheader("Динамика RevPAR / Occupancy")
        cols_to_show = [c for c in ["RevPAR_idx", "Occupancy_idx"] if c in filtered.columns]
        if cols_to_show:
            st.line_chart(filtered.set_index("date")[cols_to_show])
