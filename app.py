
import os
from datetime import datetime
from typing import Dict, Tuple, Optional

import pandas as pd
import streamlit as st

HISTORY_FILE = "history_hotels.csv"
INFLATION = 8.0
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]

st.set_page_config(page_title="ChefBrain Excel", layout="wide")

st.markdown("""
<style>
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1450px;
}
.hero-box {
    background: linear-gradient(180deg, #101828 0%, #0B1220 100%);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 18px;
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
    color: #94A3B8;
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
.section-title {
    margin-top: 8px;
}
</style>
""", unsafe_allow_html=True)


# =========================
# HELPERS
# =========================
def detect_hotel(df: pd.DataFrame, filename: str) -> str:
    first_cell = str(df.iloc[0, 0]).upper() if not df.empty and pd.notna(df.iloc[0, 0]) else ""
    full_name = f"{filename} {first_cell}".upper()

    for hotel in HOTELS:
        if hotel in full_name:
            return hotel

    if "PALACE" in full_name and "BRIDGE" in full_name:
        return "PALACE BRIDGE"
    if "OLYMPIA" in full_name and "GARDEN" in full_name:
        return "OLYMPIA GARDEN"
    if "VASILIEV" in full_name:
        return "VASILIEVSKY"

    return "UNKNOWN"


def format_value(metric_name: str, value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return "нет данных"

    if metric_name == "Occupancy":
        # В файлах occupancy хранится долей, например 0.46
        if value <= 1.5:
            return f"{value * 100:.1f}%"
        return f"{value:.1f}%"

    return f"{value:,.0f}".replace(",", " ")


def format_idx(idx: Optional[float]) -> str:
    if idx is None or pd.isna(idx):
        return "нет данных"
    return f"{idx:+.1f}%"


def get_indicator(idx: Optional[float]) -> Tuple[str, str, str]:
    if idx is None or pd.isna(idx):
        return "•", "#94A3B8", "нет данных"
    if idx < 0:
        return "▼", "#EF4444", "ниже LY"
    if idx < INFLATION:
        return "▲", "#F59E0B", "ниже инфляции"
    return "▲", "#22C55E", "выше инфляции"


def get_status_name(idx: Optional[float]) -> str:
    if idx is None or pd.isna(idx):
        return "Нет данных"
    if idx < 0:
        return "Критично"
    if idx < INFLATION:
        return "Риск"
    return "Рост"


def find_row_index(df: pd.DataFrame, text: str, start_idx: int = 0) -> Optional[int]:
    for i in range(start_idx, len(df)):
        cell = str(df.iloc[i, 0]).strip().upper()
        if cell == text.upper():
            return i
    return None


def first_row_between(df: pd.DataFrame, start_idx: Optional[int], end_idx: Optional[int], target: str) -> Optional[int]:
    if start_idx is None:
        return None
    end = len(df) if end_idx is None else end_idx

    for i in range(start_idx, end):
        cell = str(df.iloc[i, 0]).strip().upper()
        if cell == target.upper():
            return i
    return None


def first_contains_between(df: pd.DataFrame, start_idx: Optional[int], end_idx: Optional[int], target: str) -> Optional[int]:
    if start_idx is None:
        return None
    end = len(df) if end_idx is None else end_idx
    t = target.upper()

    for i in range(start_idx, end):
        cell = str(df.iloc[i, 0]).strip().upper()
        if t in cell:
            return i
    return None


def row_to_metric(df: pd.DataFrame, row_idx: Optional[int]) -> Tuple[Optional[float], Optional[float]]:
    """
    Manager view structure:
    - col 9  = MTD actual (Accum.)
    - col 14 = LY index ratio
    """
    if row_idx is None:
        return (None, None)

    row = df.iloc[row_idx]

    value = row[9] if 9 in row.index else None
    idx_ratio = row[14] if 14 in row.index else None

    value = None if pd.isna(value) else float(value)

    if pd.isna(idx_ratio):
        idx = None
    else:
        idx = round((float(idx_ratio) - 1.0) * 100, 1)

    return value, idx


# =========================
# EXCEL PARSER
# =========================
def parse_excel(file) -> Tuple[str, Dict[str, Tuple[Optional[float], Optional[float]]]]:
    df = pd.read_excel(file, sheet_name="Manager view", header=None)
    hotel = detect_hotel(df, file.name)

    acc_idx = find_row_index(df, "ACCOMMODATION")
    breakfast_idx = find_row_index(df, "BREAKFAST")
    total_kitchen_idx = find_row_index(df, "TOTAL KITCHEN")
    total_fb_idx = find_row_index(df, "TOTAL F&B, M&E REVENUE")
    hotel_total_idx = find_row_index(df, "HOTEL TOTAL")

    # Revenue
    revenue_row = first_row_between(df, hotel_total_idx, len(df), "Total revenue")
    if revenue_row is None:
        revenue_row = first_row_between(df, acc_idx, breakfast_idx, "Room Revenue")

    # Breakfast
    breakfast_row = first_row_between(df, breakfast_idx, total_kitchen_idx, "Total revenue")

    # Occupancy / RevPAR
    occupancy_row = first_row_between(df, acc_idx, breakfast_idx, "Occ-%")
    revpar_row = first_row_between(df, acc_idx, breakfast_idx, "RevPAR")

    # Kitchen
    kitchen_row = first_contains_between(df, total_kitchen_idx, total_fb_idx, "Rev. / efficient hour")
    if kitchen_row is None:
        kitchen_row = first_contains_between(df, total_fb_idx, hotel_total_idx, "Rev. / efficient hour")
    if kitchen_row is None and hotel_total_idx is not None:
        kitchen_row = first_contains_between(df, hotel_total_idx, len(df), "Rev. / efficient hour")

    # Service
    service_row = first_contains_between(df, total_fb_idx, hotel_total_idx, "Rev. / wtrs. Hour")
    if service_row is None:
        service_row = first_contains_between(df, breakfast_idx, total_kitchen_idx, "Rev. / wtrs. Hour")

    data = {
        "Revenue": row_to_metric(df, revenue_row),
        "Breakfast": row_to_metric(df, breakfast_row),
        "Occupancy": row_to_metric(df, occupancy_row),
        "RevPAR": row_to_metric(df, revpar_row),
        "Kitchen": row_to_metric(df, kitchen_row),
        "Waiter": row_to_metric(df, service_row),
    }

    return hotel, data


# =========================
# HISTORY
# =========================
def save_history(hotel: str, data: Dict[str, Tuple[Optional[float], Optional[float]]]) -> None:
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


def load_history() -> pd.DataFrame:
    if os.path.exists(HISTORY_FILE):
        return pd.read_csv(HISTORY_FILE)
    return pd.DataFrame()


def latest_rows_by_hotel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    return (
        df.sort_values("date")
        .groupby("hotel", as_index=False)
        .tail(1)
        .sort_values("hotel")
    )


# =========================
# ANALYTICS
# =========================
def build_summary(data: Dict[str, Tuple[Optional[float], Optional[float]]]):
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
        elif revenue_idx < INFLATION:
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
        elif breakfast_idx < INFLATION:
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


def render_summary_block(notes) -> None:
    if not notes:
        return

    st.subheader("Вывод")

    color_map = {
        "good": ("#22C55E", "rgba(34,197,94,0.12)"),
        "warn": ("#F59E0B", "rgba(245,158,11,0.12)"),
        "bad": ("#EF4444", "rgba(239,68,68,0.12)"),
    }

    for text, level in notes:
        border, bg = color_map.get(level, ("#6B7280", "rgba(107,114,128,0.12)"))
        st.markdown(
            f"""
            <div class="summary-box" style="border-left: 4px solid {border}; background: {bg};">
                {text}
            </div>
            """,
            unsafe_allow_html=True,
        )


def show_metric(col, title: str, key: str, data: Dict[str, Tuple[Optional[float], Optional[float]]]) -> None:
    value, idx = data.get(key, (None, None))
    arrow, color, label = get_indicator(idx)

    with col:
        st.markdown(f"**{title}**")
        st.metric(label="", value=format_value(title, value), delta=None)
        st.markdown(
            f"<span style='color:{color}; font-weight:700; font-size:18px;'>{arrow} {format_idx(idx)}</span>",
            unsafe_allow_html=True,
        )
        st.markdown(f"<span class='small-label'>{label}</span>", unsafe_allow_html=True)


# =========================
# UI
# =========================
st.markdown("""
<div class="hero-box">
    <div class="hero-title">ChefBrain (Excel версия)</div>
    <div class="hero-subtitle">Загрузи 1 или несколько Excel-файлов с листом Manager view.</div>
</div>
""", unsafe_allow_html=True)

files = st.file_uploader(
    "Загрузи 1 или несколько Excel файлов",
    type=["xlsx"],
    accept_multiple_files=True,
)

current_uploads: Dict[str, Dict[str, Tuple[Optional[float], Optional[float]]]] = {}

if files:
    for file in files:
        hotel, data = parse_excel(file)
        current_uploads[hotel] = data
        save_history(hotel, data)

    for hotel, data in current_uploads.items():
        st.subheader(hotel)

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
    st.info("История пока пуста. Загрузите отчёты.")
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

        latest_display = latest_display.rename(columns={
            "hotel": "Hotel",
            "date": "Date",
            "Revenue_idx": "Revenue %",
            "Breakfast_idx": "Breakfast %",
            "Occupancy_idx": "Occupancy %",
            "RevPAR_idx": "RevPAR %",
            "Kitchen_idx": "Kitchen %",
            "Waiter_idx": "Service %",
        })

        st.dataframe(latest_display, use_container_width=True, hide_index=True)

        if {"date", "hotel", "Revenue_idx"}.issubset(history.columns):
            st.subheader("Revenue: сравнение отелей")
            pivot = history.pivot_table(index="date", columns="hotel", values="Revenue_idx", aggfunc="last")
            if pivot.shape[1] > 0:
                st.line_chart(pivot)

        if {"date", "hotel", "RevPAR_idx"}.issubset(history.columns):
            st.subheader("RevPAR: сравнение отелей")
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
