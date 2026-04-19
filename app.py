
import os
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

INFLATION = 8.0
HISTORY_FILE = "history.csv"
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]

st.set_page_config(page_title="ChefBrain", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px;}
.hero {padding: 1.25rem 1.4rem; border: 1px solid rgba(255,255,255,0.08); border-radius: 22px;
background: linear-gradient(135deg, rgba(25,35,64,0.95), rgba(10,13,23,0.98)); margin-bottom: 1rem;}
.hero-title {font-size: 2.25rem; font-weight: 800; margin: 0 0 0.2rem 0;}
.hero-sub {color: #b8bfd1; font-size: 0.98rem; margin: 0;}
.metric-card {border: 1px solid rgba(255,255,255,0.08); border-radius: 20px; padding: 1rem 1rem 0.9rem 1rem;
background: rgba(255,255,255,0.025); min-height: 142px;}
.metric-title {color: #b8bfd1; font-size: 0.95rem; margin-bottom: 0.5rem;}
.metric-main {font-size: 1.8rem; font-weight: 750; line-height: 1.15; margin-bottom: 0.35rem;}
.metric-sub {color: #c8cfdf; font-size: 0.92rem;}
.chip {display: inline-block; padding: 0.18rem 0.55rem; border-radius: 999px; font-size: 0.82rem; font-weight: 700; margin-top: 0.45rem;}
.chip-green {background: rgba(40,167,69,.16); color: #7fe39b; border: 1px solid rgba(40,167,69,.28);}
.chip-yellow {background: rgba(255,193,7,.14); color: #ffd86a; border: 1px solid rgba(255,193,7,.24);}
.chip-red {background: rgba(220,53,69,.14); color: #ff8c98; border: 1px solid rgba(220,53,69,.24);}
.section-card {border: 1px solid rgba(255,255,255,0.08); border-radius: 20px; padding: 1rem 1.1rem; background: rgba(255,255,255,0.02);}
.summary-box {border-left: 4px solid #5d8cff; background: rgba(93,140,255,.08); border-radius: 12px; padding: 0.9rem 1rem; margin-bottom: 0.7rem;}
.small-muted {color: #b8bfd1; font-size: 0.9rem;}
</style>
""", unsafe_allow_html=True)

def normalize_spaces(s):
    return re.sub(r"[ \t]+", " ", s or "")

def parse_number(num_str):
    if num_str is None:
        return None
    s = str(num_str).replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def detect_hotel(text):
    upper = text.upper()
    for hotel in HOTELS:
        if hotel in upper:
            return hotel
    return "UNKNOWN"

def extract_section(text, start_label, end_label=None):
    start = text.find(start_label)
    if start == -1:
        return None
    if end_label:
        end = text.find(end_label, start + len(start_label))
        if end != -1:
            return text[start:end]
    return text[start:]

def find_line(text, label):
    pattern = rf"^{re.escape(label)}.*$"
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(0) if match else None

def extract_mtd_from_line(line):
    if not line:
        return None, None
    nums = re.findall(r"\d[\d ]*(?:,\d+)?", line)
    if len(nums) < 10:
        return None, None
    mtd_actual = parse_number(nums[5])
    yoy_index_ratio = parse_number(nums[9])
    yoy_index_pct = (yoy_index_ratio - 1.0) * 100 if yoy_index_ratio is not None else None
    return mtd_actual, yoy_index_pct

def fmt_number(x):
    if x is None or pd.isna(x):
        return "нет данных"
    return f"{x:,.0f}".replace(",", " ")

def fmt_percent(x):
    if x is None or pd.isna(x):
        return "нет данных"
    return f"{x:+.1f}%"

def fmt_occupancy(x):
    if x is None or pd.isna(x):
        return "нет данных"
    return f"{x:.1f}%"

def status_text(value):
    if value is None or pd.isna(value):
        return "Нет данных", "chip-yellow"
    if value > INFLATION:
        return "Выше инфляции", "chip-green"
    if value > 0:
        return "Ниже инфляции", "chip-yellow"
    return "Падение", "chip-red"

def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        for p in pdf.pages:
            txt = p.extract_text() or ""
            pages.append(normalize_spaces(txt))
        text = "\n".join(pages)

    hotel = detect_hotel(text)
    accommodation = extract_section(text, "ACCOMMODATION 3675010", "BREAKFAST 3675014") or text
    breakfast_sec = extract_section(text, "BREAKFAST 3675014", "PB MEETING & EVENTS 3675011") or text
    total_fb_sec = extract_section(text, "TOTAL F&B, M&E REVENUE", "HOTEL TOTAL") or text

    metrics = {}
    metrics["Revenue"] = extract_mtd_from_line(find_line(accommodation, "Room Revenue"))
    metrics["Breakfast"] = extract_mtd_from_line(find_line(breakfast_sec, "Total revenue"))
    metrics["Occupancy"] = extract_mtd_from_line(find_line(accommodation, "Occ-%"))
    metrics["RevPAR"] = extract_mtd_from_line(find_line(accommodation, "RevPAR"))

    kitchen_line = find_line(total_fb_sec, "Rev. / efficient hour") if total_fb_sec else None
    if not kitchen_line:
        kitchen_line = find_line(text, "Rev. / efficient hour")
    metrics["Kitchen"] = extract_mtd_from_line(kitchen_line)

    waiter_line = find_line(total_fb_sec, "Rev. / total hour") if total_fb_sec else None
    if not waiter_line:
        waiter_line = find_line(text, "Rev. / total hour")
    metrics["Waiter"] = extract_mtd_from_line(waiter_line)

    return hotel, metrics

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

def build_summary(metrics):
    out = []
    revenue_idx = metrics["Revenue"][1]
    breakfast_idx = metrics["Breakfast"][1]
    occ_idx = metrics["Occupancy"][1]
    revpar_idx = metrics["RevPAR"][1]
    kitchen_idx = metrics["Kitchen"][1]
    waiter_idx = metrics["Waiter"][1]

    if revenue_idx is not None and revenue_idx < INFLATION:
        out.append("Критично: выручка не перекрывает инфляцию.")
    if revpar_idx is not None and occ_idx is not None and revpar_idx > occ_idx:
        out.append("Рост идёт за счёт цены, а не загрузки.")
    if breakfast_idx is not None and breakfast_idx < INFLATION:
        out.append("Завтрак растёт ниже инфляции.")
    if kitchen_idx is not None and waiter_idx is not None:
        if kitchen_idx > waiter_idx:
            out.append("Эффективность кухни выше сервиса.")
        elif waiter_idx > kitchen_idx:
            out.append("Эффективность сервиса выше кухни.")
    if not out:
        out.append("Критичных отклонений не найдено.")
    return out

def latest_summary_from_history(df_hotel):
    if df_hotel.empty:
        return []
    latest = df_hotel.sort_values("date").iloc[-1]
    notes = []
    if pd.notna(latest.get("Revenue_idx")) and latest["Revenue_idx"] < INFLATION:
        notes.append("Последняя выручка ниже целевого инфляционного порога.")
    if pd.notna(latest.get("RevPAR_idx")) and pd.notna(latest.get("Occupancy_idx")):
        if latest["RevPAR_idx"] > latest["Occupancy_idx"]:
            notes.append("RevPAR растёт быстрее загрузки — рост в основном через цену.")
    return notes

def render_metric_card(title, mtd_value, idx_value, value_type="money"):
    if value_type == "occupancy":
        main = fmt_occupancy(mtd_value)
    else:
        main = fmt_number(mtd_value)
    idx_text = fmt_percent(idx_value)
    chip_text, chip_class = status_text(idx_value)
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">{title}</div>
        <div class="metric-main">{main}</div>
        <div class="metric-sub">Индекс к LY: <strong>{idx_text}</strong></div>
        <div class="chip {chip_class}">{chip_text}</div>
    </div>
    """, unsafe_allow_html=True)

def render_hero():
    st.markdown("""
    <div class="hero">
        <div class="hero-title">ChefBrain</div>
        <p class="hero-sub">
            Мультиотельная аналитика для PALACE BRIDGE, OLYMPIA GARDEN и VASILIEVSKY.
            Загрузи отчёт, сохрани историю и сравни динамику по отелям.
        </p>
    </div>
    """, unsafe_allow_html=True)

with st.sidebar:
    st.header("Настройки")
    inflation = st.number_input("Порог инфляции, %", value=INFLATION, step=0.5)
    INFLATION = float(inflation)
    st.markdown("---")
    st.markdown("**Отели:**")
    for h in HOTELS:
        st.caption(f"• {h}")
    st.markdown("---")
    if st.button("Очистить локальную историю", use_container_width=True):
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
            st.success("Локальная история очищена. Перезагрузи страницу.")
        else:
            st.info("Истории пока нет.")

render_hero()

upload_col, info_col = st.columns([1.25, 1])

with upload_col:
    uploaded_file = st.file_uploader("Загрузи PDF-отчёт", type=["pdf"])

with info_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("**Что покажет приложение**")
    st.markdown("""
    - MTD факт по ключевым метрикам  
    - Индекс к прошлому году  
    - Автоопределение отеля  
    - Историю и сравнение по 3 отелям
    """)
    st.markdown("</div>", unsafe_allow_html=True)

if uploaded_file:
    hotel, metrics = parse_pdf(uploaded_file)
    save_history(hotel, metrics)
    st.success(f"Отчёт распознан как: **{hotel}**")

    st.subheader("Ключевые показатели")
    cols = st.columns(3)
    with cols[0]:
        render_metric_card("Revenue", metrics["Revenue"][0], metrics["Revenue"][1], "money")
    with cols[1]:
        render_metric_card("Breakfast", metrics["Breakfast"][0], metrics["Breakfast"][1], "money")
    with cols[2]:
        render_metric_card("Occupancy", metrics["Occupancy"][0], metrics["Occupancy"][1], "occupancy")

    cols2 = st.columns(3)
    with cols2[0]:
        render_metric_card("RevPAR", metrics["RevPAR"][0], metrics["RevPAR"][1], "money")
    with cols2[1]:
        render_metric_card("Kitchen Efficiency", metrics["Kitchen"][0], metrics["Kitchen"][1], "money")
    with cols2[2]:
        render_metric_card("Waiter Efficiency", metrics["Waiter"][0], metrics["Waiter"][1], "money")

    st.subheader("Управленческий вывод")
    for item in build_summary(metrics):
        st.markdown(f'<div class="summary-box">• {item}</div>', unsafe_allow_html=True)

st.divider()
history = load_history()
st.subheader("История и сравнение")

if history.empty:
    st.info("История пока пуста. Загрузи первый PDF-отчёт.")
else:
    if "hotel" not in history.columns:
        history["hotel"] = "UNKNOWN"
    if "date" not in history.columns:
        history["date"] = ""

    required_cols = [
        "Revenue_mtd", "Revenue_idx",
        "Breakfast_mtd", "Breakfast_idx",
        "Occupancy_mtd", "Occupancy_idx",
        "RevPAR_mtd", "RevPAR_idx",
        "Kitchen_mtd", "Kitchen_idx",
        "Waiter_mtd", "Waiter_idx",
    ]
    for col in required_cols:
        if col not in history.columns:
            history[col] = pd.NA

    filter_col, view_col = st.columns([1, 1])
    with filter_col:
        hotel_options = ["Все отели"] + sorted(history["hotel"].dropna().unique().tolist())
        selected_hotel = st.selectbox("Фильтр по отелю", hotel_options, index=0)
    with view_col:
        compare_metric = st.selectbox(
            "Показатель для сравнения",
            ["Revenue_idx", "Breakfast_idx", "Occupancy_idx", "RevPAR_idx", "Kitchen_idx", "Waiter_idx"],
            index=0,
        )

    filtered = history.copy()
    if selected_hotel != "Все отели":
        filtered = filtered[filtered["hotel"] == selected_hotel]
    filtered = filtered.sort_values(["date", "hotel"])

    top_left, top_right = st.columns([1.2, 1])

    with top_left:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**Последние записи**")
        st.dataframe(filtered.tail(20), use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with top_right:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("**Быстрый вывод по истории**")
        if selected_hotel == "Все отели":
            st.markdown('<p class="small-muted">Выбран режим сравнения всех отелей.</p>', unsafe_allow_html=True)
            latest_by_hotel = history.sort_values("date").groupby("hotel", as_index=False).tail(1)[["hotel", compare_metric]].sort_values(compare_metric, ascending=False)
            st.dataframe(latest_by_hotel, use_container_width=True, hide_index=True)
        else:
            notes = latest_summary_from_history(filtered)
            if notes:
                for note in notes:
                    st.markdown(f'<div class="summary-box">• {note}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<p class="small-muted">Недостаточно данных для расширенного вывода.</p>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("Графики")

    if selected_hotel == "Все отели":
        pivot = filtered.pivot_table(index="date", columns="hotel", values=compare_metric, aggfunc="last")
        if not pivot.empty:
            st.line_chart(pivot, height=360)
    else:
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            mtd_cols = ["Revenue_mtd", "Breakfast_mtd", "RevPAR_mtd"]
            existing_mtd = [c for c in mtd_cols if c in filtered.columns]
            if existing_mtd:
                st.markdown("**MTD факт**")
                st.line_chart(filtered.set_index("date")[existing_mtd], height=320)
        with chart_col2:
            idx_cols = ["Revenue_idx", "Breakfast_idx", "Occupancy_idx", "RevPAR_idx", "Kitchen_idx", "Waiter_idx"]
            existing_idx = [c for c in idx_cols if c in filtered.columns]
            if existing_idx:
                st.markdown("**Индексы к LY**")
                st.line_chart(filtered.set_index("date")[existing_idx], height=320)

    st.subheader("Сравнение последнего доступного дня")
    latest_rows = history.sort_values("date").groupby("hotel", as_index=False).tail(1)[
        ["hotel", "date", "Revenue_idx", "Breakfast_idx", "Occupancy_idx", "RevPAR_idx", "Kitchen_idx", "Waiter_idx"]
    ].sort_values("hotel")
    st.dataframe(latest_rows, use_container_width=True, hide_index=True)
