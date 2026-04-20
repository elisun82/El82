import os
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

# =====================
# SETTINGS
# =====================
HISTORY_FILE = "history_all_hotels.csv"
INFLATION = 8.0
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]

st.set_page_config(page_title="ChefBrain Final", layout="wide")

# =====================
# STYLES
# =====================
st.markdown("""
<style>
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1450px;
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
    font-size: 15px;
}
</style>
""", unsafe_allow_html=True)

# =====================
# HELPERS
# =====================
NUM_PATTERN = re.compile(
    r"\d{1,3}(?:[ \u00A0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
)

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

    s = str(value).replace("RUR", "").replace("%", "").strip()

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

def parse_metric_line(line: str):
    if not line:
        return None, None

    tokens = extract_tokens(line)
    if len(tokens) < 10:
        return None, None

    mtd_value = parse_number(tokens[5])

    idx_raw = tokens[9].replace(" ", "")
    if "," in idx_raw and "." in idx_raw:
        idx_raw = idx_raw.replace(",", "")
    else:
        idx_raw = idx_raw.replace(",", ".")

    try:
        idx_ratio = float(idx_raw)
        idx_pct = round((idx_ratio - 1.0) * 100, 1)
    except Exception:
        idx_pct = None

    return mtd_value, idx_pct

def format_value(name, value):
    if value is None:
        return "нет данных"
    if name == "Occupancy":
        return f"{value:.1f}%"
    return f"{value:,.0f}".replace(",", " ")

def format_idx(idx):
    if idx is None:
        return "нет данных"
    return f"{idx:+.1f}%"

def get_indicator(idx):
    if idx is None:
        return "•", "#9CA3AF", "нет данных"
    if idx < 0:
        return "▼", "#EF4444", "ниже LY"
    if idx < 8:
        return "▲", "#F59E0B", "ниже инфляции"
    return "▲", "#22C55E", "выше инфляции"

def get_status_name(idx):
    if idx is None:
        return "Нет данных"
    if idx < 0:
        return "Критично"
    if idx < 8:
        return "Риск"
    return "Рост"

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

def find_nth_from_end(lines, includes=None, startswith=None, n=1):
    includes = [x.lower() for x in (includes or [])]
    startswith = startswith.lower() if startswith else None

    matches = []
    for line in lines:
        low = line.lower()
        if startswith and not low.startswith(startswith):
            continue
        if includes and not all(x in low for x in includes):
            continue
        matches.append(line)

    if len(matches) < n:
        return None

    return matches[-n]

# =====================
# HOTEL PARSERS
# =====================
def parse_palace(text: str):
    all_lines = split_lines(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast"])
    breakfast_lines = get_section_lines(text, ["breakfast"], ["meeting", "events"])
    if not breakfast_lines:
        breakfast_lines = get_section_lines(text, ["breakfast"], ["total kitchen"])

    total_kitchen_lines = get_section_lines(text, ["total kitchen"], ["total f&b", "m&e revenue"])
    total_fb_lines = get_section_lines(text, ["total f&b", "m&e revenue"], ["total spa"])

    revenue_line = find_first_line(accommodation_lines, startswith="room revenue")
    breakfast_line = find_first_line(breakfast_lines, startswith="total revenue")
    occupancy_line = find_first_line(accommodation_lines, startswith="occ-%")
    revpar_line = find_first_line(accommodation_lines, startswith="revpar")

    kitchen_line = find_first_line(total_kitchen_lines, includes=["rev.", "efficient hour"])
    if not kitchen_line:
        kitchen_line = find_last_line(all_lines, includes=["rev.", "efficient hour"])

    waiter_line = find_first_line(total_fb_lines, includes=["rev.", "wtrs. hour"])
    if not waiter_line:
        waiter_line = find_first_line(breakfast_lines, includes=["rev.", "wtrs. hour"])
    if not waiter_line:
        waiter_line = find_last_line(all_lines, includes=["rev.", "wtrs. hour"])

    return {
        "Revenue": parse_metric_line(revenue_line),
        "Breakfast": parse_metric_line(breakfast_line),
        "Occupancy": parse_metric_line(occupancy_line),
        "RevPAR": parse_metric_line(revpar_line),
        "Kitchen": parse_metric_line(kitchen_line),
        "Waiter": parse_metric_line(waiter_line),
    }

def parse_olympia(text: str):
    all_lines = split_lines(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast"])
    breakfast_lines = get_section_lines(text, ["breakfast"], ["og - meeting", "events"])
    if not breakfast_lines:
        breakfast_lines = get_section_lines(text, ["breakfast"], ["og - main restaurant"])
    if not breakfast_lines:
        breakfast_lines = get_section_lines(text, ["breakfast"], ["total kitchen"])

    total_kitchen_lines = get_section_lines(text, ["total kitchen"], ["total f&b", "m&e revenue"])
    total_fb_lines = get_section_lines(text, ["total f&b", "m&e revenue"], ["hotel total"])

    revenue_line = find_first_line(accommodation_lines, startswith="room revenue")
    breakfast_line = find_first_line(breakfast_lines, startswith="total revenue")
    occupancy_line = find_first_line(accommodation_lines, startswith="occ-%")
    revpar_line = find_first_line(accommodation_lines, startswith="revpar")

    kitchen_line = find_first_line(total_kitchen_lines, includes=["rev.", "efficient hour"])
    if not kitchen_line:
        kitchen_line = find_last_line(all_lines, includes=["rev.", "efficient hour"])

    waiter_line = find_first_line(total_fb_lines, includes=["rev.", "wtrs. hour"])
    if not waiter_line:
        waiter_line = find_first_line(breakfast_lines, includes=["rev.", "wtrs. hour"])
    if not waiter_line:
        waiter_line = find_last_line(all_lines, includes=["rev.", "wtrs. hour"])

    return {
        "Revenue": parse_metric_line(revenue_line),
        "Breakfast": parse_metric_line(breakfast_line),
        "Occupancy": parse_metric_line(occupancy_line),
        "RevPAR": parse_metric_line(revpar_line),
        "Kitchen": parse_metric_line(kitchen_line),
        "Waiter": parse_metric_line(waiter_line),
    }

def parse_vasilievsky(text: str):
    all_lines = split_lines(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast"])
    breakfast_lines = get_section_lines(text, ["breakfast"], ["vs pub"])
    if not breakfast_lines:
        breakfast_lines = get_section_lines(text, ["breakfast"], ["vs main restaurant"])
    if not breakfast_lines:
        breakfast_lines = get_section_lines(text, ["breakfast"], ["total kitchen"])

    revenue_line = find_nth_from_end(all_lines, startswith="total revenue", n=1)
    breakfast_line = find_first_line(breakfast_lines, startswith="total revenue")
    occupancy_line = find_first_line(accommodation_lines, startswith="occ-%")
    revpar_line = find_first_line(accommodation_lines, startswith="revpar")
    kitchen_line = find_nth_from_end(all_lines, includes=["rev.", "efficient hour"], n=3)
    waiter_line = find_nth_from_end(all_lines, includes=["rev.", "wtrs. hour"], n=1)

    return {
        "Revenue": parse_metric_line(revenue_line),
        "Breakfast": parse_metric_line(breakfast_line),
        "Occupancy": parse_metric_line(occupancy_line),
        "RevPAR": parse_metric_line(revpar_line),
        "Kitchen": parse_metric_line(kitchen_line),
        "Waiter": parse_metric_line(waiter_line),
    }

def parse_uploaded_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        for page in pdf.pages:
            txt = page.extract_text() or ""
            pages.append(normalize_spaces(txt))
        text = "\n".join(pages)

    hotel = detect_hotel(text)

    if hotel == "PALACE BRIDGE":
        data = parse_palace(text)
    elif hotel == "OLYMPIA GARDEN":
        data = parse_olympia(text)
    elif hotel == "VASILIEVSKY":
        data = parse_vasilievsky(text)
    else:
        data = {
            "Revenue": (None, None),
            "Breakfast": (None, None),
            "Occupancy": (None, None),
            "RevPAR": (None, None),
            "Kitchen": (None, None),
            "Waiter": (None, None),
        }

    return hotel, data

# =====================
# HISTORY
# =====================
def save_history(hotel, data):
    if hotel == "UNKNOWN":
        return

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
            notes.append((f"Выручка растёт, но не перекрывает инфляцию {INFLATION:.0f}%.", "warn"))
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
        "good": ("#166534", "#DCFCE7"),
        "warn": ("#92400E", "#FEF3C7"),
        "bad":  ("#991B1B", "#FEE2E2")
    }

    for text, level in notes:
        border, bg = color_map.get(level, ("#374151", "#F3F4F6"))
        st.markdown(
            f"""
            <div class="summary-box" style="border-left: 4px solid {border}; background: {bg}; color: {border};">
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
        st.metric(label=" ", value=value_str)
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
    <div class="hero-title">ChefBrain Final</div>
    <div class="hero-subtitle">PALACE BRIDGE + OLYMPIA GARDEN + VASILIEVSKY</div>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Загрузи PDF отчёт", type=["pdf"])

if uploaded_file:
    hotel, data = parse_uploaded_pdf(uploaded_file)

    if hotel == "UNKNOWN":
        st.error("Не удалось определить отель по файлу.")
    else:
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
    st.info("История пока пуста. Загрузите хотя бы по одному отчёту для отелей.")
else:
    latest = latest_rows_by_hotel(history)

    if latest.empty:
        st.info("Пока недостаточно данных для сравнения.")
    else:
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

        st.subheader("Статус по отелям")
        cols = st.columns(3)
        rows = latest[["hotel", "Revenue_idx"]].sort_values("hotel").values.tolist()

        for i, row in enumerate(rows[:3]):
            hotel_name, idx = row[0], row[1]
            arrow, color, label = get_indicator(idx)
            status_name = get_status_name(idx)

            with cols[i]:
                st.markdown(f"**{hotel_name}**")
                st.metric(label=" ", value=status_name)
                st.markdown(
                    f"<span style='color:{color}; font-weight:700; font-size:18px;'>{arrow} {format_idx(idx)}</span>",
                    unsafe_allow_html=True
                )
                st.markdown(f"<span class='small-label'>{label}</span>", unsafe_allow_html=True)

        st.subheader("Revenue: сравнение отелей")
        if {"date", "hotel", "Revenue_idx"}.issubset(history.columns):
            pivot = history.pivot_table(index="date", columns="hotel", values="Revenue_idx", aggfunc="last")
            if pivot.shape[1] > 0:
                st.line_chart(pivot)

        st.subheader("RevPAR: сравнение отелей")
        if {"date", "hotel", "RevPAR_idx"}.issubset(history.columns):
            pivot = history.pivot_table(index="date", columns="hotel", values="RevPAR_idx", aggfunc="last")
            if pivot.shape[1] > 0:
                st.line_chart(pivot)

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
