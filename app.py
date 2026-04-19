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
    """
    Возвращает:
    arrow, color, label
    """
    if idx is None:
        return "•", "#9CA3AF", "нет данных"

    if idx < 0:
        return "▼", "#EF4444", "ниже LY"
    elif idx < 8:
        return "▲", "#F59E0B", "ниже инфляции"
    else:
        return "▲", "#22C55E", "выше инфляции"


def render_metric_card(title, value, idx, value_str):
    arrow, color, label = get_indicator(idx)

    idx_text = "нет данных" if idx is None else f"{idx:+.1f}%"

    st.markdown(
        f"""
        <div style="
            background: linear-gradient(180deg, #111827 0%, #0B1220 100%);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 18px;
            padding: 18px 18px 14px 18px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.22);
            min-height: 150px;
        ">
            <div style="
                font-size: 14px;
                color: #9CA3AF;
                margin-bottom: 10px;
            ">{title}</div>

            <div style="
                font-size: 22px;
                font-weight: 700;
                color: #F9FAFB;
                margin-bottom: 14px;
            ">{value_str}</div>

            <div style="
                display: inline-flex;
                align-items: center;
                gap: 8px;
                font-size: 15px;
                font-weight: 700;
                color: {color};
                background: rgba(255,255,255,0.03);
                border-radius: 999px;
                padding: 6px 10px;
            ">
                <span style="font-size:16px;">{arrow}</span>
                <span>{idx_text}</span>
            </div>

            <div style="
                margin-top: 10px;
                font-size: 12px;
                color: #9CA3AF;
            ">{label}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_summary_block(notes):
    color_map = {
        "good": ("#22C55E", "rgba(34,197,94,0.12)"),
        "warn": ("#F59E0B", "rgba(245,158,11,0.12)"),
        "bad":  ("#EF4444", "rgba(239,68,68,0.12)")
    }

    st.markdown("### Вывод")

    for text, level in notes:
        border, bg = color_map.get(level, ("#6B7280", "rgba(107,114,128,0.12)"))
        st.markdown(
            f"""
            <div style="
                border-left: 4px solid {border};
                background: {bg};
                border-radius: 12px;
                padding: 12px 14px;
                margin-bottom: 10px;
                color: #F3F4F6;
                font-size: 15px;
            ">
                {text}
            </div>
            """,
            unsafe_allow_html=True
        )
