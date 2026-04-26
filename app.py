import os
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import requests
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# --- Конфигурация ---
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]
st.set_page_config(page_title="ChefBrain v4", layout="wide")

# --- Стилизация ---
st.markdown("""
<style>
.block-container {padding-top:1rem; padding-bottom:2rem; max-width:1450px;}
.hero-box {
    background: linear-gradient(180deg, #101828 0%, #0B1220 100%);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px; padding: 18px 22px; margin-bottom: 16px;
}
.hero-title {font-size:30px; font-weight:800; color:#F9FAFB;}
.summary-box {border-radius:12px; padding:12px 14px; margin-bottom:10px; font-size:14px;}
.small-note {font-size:11px; color:#94A3B8; margin-top:-4px;}
.kpi-card {background:#111827; padding:15px; border-radius:15px; border:1px solid #374151; margin-bottom:10px;}
</style>
""", unsafe_allow_html=True)

# --- Логика извлечения данных ---
NUM_PATTERN = re.compile(r"[-+]?\d{1,3}(?:[ \u00A0]\d{3})*(?:[.,]\d+)?")

def parse_number(s):
    if not s: return None
    s = s.replace("RUR", "").replace("%", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    try: return float(s)
    except: return None

def extract_tokens(line: str):
    return [m.group(0).strip() for m in NUM_PATTERN.finditer(line)]

def safe_pct(actual, reference):
    if actual is None or reference is None or reference == 0: return None
    return round((actual / reference - 1.0) * 100, 1)

def extract_month_accum_values(line: str):
    if not line: return [None]*5
    tokens = extract_tokens(line)
    # В отчете обычно 6 колонок: [Day Act, Day Bu, Day LY, MTD Act, MTD Bu, MTD LY]
    # Берем с конца, чтобы не зависеть от мусора в начале строки
    if len(tokens) >= 3:
        # Индексы с конца: -3(Actual), -2(Budget), -1(LY)
        actual = parse_number(tokens[-3])
        budget = parse_number(tokens[-2])
        ly = parse_number(tokens[-1])
        return actual, budget, ly, safe_pct(actual, budget), safe_pct(actual, ly)
    return [None]*5

# --- Функции для работы с данными ---
def load_history():
    try:
        url = st.secrets["GOOGLE_SCRIPT_URL"]
        resp = requests.get(url, params={"key": st.secrets["CHEFBRAIN_SECRET_KEY"]}, timeout=15)
        df = pd.DataFrame(resp.json().get("rows", []))
        for col in df.columns:
            if col not in ["date", "hotel"]: df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except: return pd.DataFrame()

def save_history(doc_date, hotel, data):
    row = {"date": doc_date, "hotel": hotel}
    for k, v in data.items():
        row.update({f"{k}_actual": v[0], f"{k}_budget": v[1], f"{k}_ly": v[2], f"{k}_vs_budget": v[3], f"{k}_vs_ly": v[4]})
    history = load_history()
    new_row = pd.DataFrame([row])
    if not history.empty:
        history = history[~((history["date"].astype(str) == str(doc_date)) & (history["hotel"] == hotel))]
        final_df = pd.concat([history, new_row], ignore_index=True)
    else: final_df = new_row
    payload = {"key": st.secrets["CHEFBRAIN_SECRET_KEY"], "rows": final_df.where(pd.notna(final_df), None).to_dict(orient="records")}
    requests.post(st.secrets["GOOGLE_SCRIPT_URL"], json=payload, timeout=20)

# --- Визуализация ---
def fmt_val(v): return f"{v:,.0f}".replace(",", " ") if v is not None else "нет данных"
def fmt_p(v): return f"{v:+.1f}%" if v is not None else "—"

def render_metric_card(col, title, sub, values):
    act, bu, ly, v_bu, v_ly = values
    with col:
        st.markdown(f"**{title}**")
        st.markdown(f"<div class='small-note'>{sub}</div>", unsafe_allow_html=True)
        st.metric(label="Actual", value=fmt_val(act))
        c_bu = "#EF4444" if (v_bu or 0) < 0 else "#22C55E"
        c_ly = "#EF4444" if (v_ly or 0) < 0 else "#22C55E"
        st.markdown(f"<div style='font-size:13px;'>vs Bu: <span style='color:{c_bu}; font-weight:bold;'>{fmt_p(v_bu)}</span></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:13px;'>vs LY: <span style='color:{c_ly}; font-weight:bold;'>{fmt_p(v_ly)}</span></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='small-note'>Bu: {fmt_val(bu)} | LY: {fmt_val(ly)}</div>", unsafe_allow_html=True)

# --- Main App ---
st.markdown('<div class="hero-box"><div class="hero-title">ChefBrain Analytics</div></div>', unsafe_allow_html=True)

uploaded = st.file_uploader("Загрузить отчет PDF", type="pdf")
if uploaded:
    with pdfplumber.open(uploaded) as pdf:
        text = "\n".join([p.extract_text() or "" for p in pdf.pages])
    
    # Очень простой поиск даты и отеля
    doc_date = datetime.now().strftime("%Y-%m-%d") # Упростим для теста, в коде выше есть поиск
    hotel = "UNKNOWN"
    for h in HOTELS: 
        if h in text.upper(): hotel = h
    
    # Парсинг секций
    lines = text.splitlines()
    data = {
        "revpar": extract_month_accum_values(next((l for l in lines if "RevPAR" in l), "")),
        "fb_total_revenue": extract_month_accum_values(next((l for l in lines if "Total F&B" in l and "Revenue" in l), "")),
        "service_hour": extract_month_accum_values(next((l for l in lines if "Wtrs" in l and "Hour" in l), "")),
        "kitchen_hour": extract_month_accum_values(next((l for l in lines if "Ktch" in l and "Hour" in l), "")),
        "hotel_total_revenue": extract_month_accum_values(next((l for l in lines if "Hotel Total" in l and "Revenue" in l), ""))
    }
    
    save_history(doc_date, hotel, data)
    
    st.subheader(f"Результаты: {hotel} ({doc_date})")
    cols = st.columns(5)
    render_metric_card(cols[0], "ACCOMM.", "RevPAR", data["revpar"])
    render_metric_card(cols[1], "F&B", "Total Revenue", data["fb_total_revenue"])
    render_metric_card(cols[2], "SERVICE", "Rev/Hour", data["service_hour"])
    render_metric_card(cols[3], "KITCHEN", "Rev/Hour", data["kitchen_hour"])
    render_metric_card(cols[4], "TOTAL", "Total Revenue", data["hotel_total_revenue"])

# --- Секция истории ---
history = load_history()
if not history.empty:
    st.markdown("---")
    st.subheader("Сравнение отелей")
    
    latest = history.sort_values("date").groupby("hotel").last().reset_index()
    cols_h = st.columns(len(latest))
    for i, (_, row) in enumerate(latest.iterrows()):
        with cols_h[i]:
            v_ly = row.get("hotel_total_revenue_vs_ly")
            color = "#EF4444" if (v_ly or 0) < 0 else "#22C55E"
            st.markdown(f"""
            <div class="kpi-card">
                <div style="color:#9CA3AF; font-size:12px;">{row['hotel']}</div>
                <div style="font-size:22px; font-weight:bold; color:{color};">{fmt_p(v_ly)}</div>
                <div style="font-size:11px; color:#6B7280;">vs Last Year (Total)</div>
            </div>
            """, unsafe_allow_html=True)

    st.subheader("Тренды показателей")
    h_plot = history.copy()
    h_plot["date"] = pd.to_datetime(h_plot["date"])
    h_plot = h_plot.sort_values("date")

    target_hotel = st.selectbox("Отель", h_plot["hotel"].unique())
    target_metric = st.selectbox("Показатель", [
        "hotel_total_revenue_actual", "revpar_actual", "fb_total_revenue_actual", 
        "service_hour_actual", "kitchen_hour_actual"
    ])

    df_filtered = h_plot[h_plot["hotel"] == target_hotel]
    
    # Построение плавного графика через Plotly
    fig = px.line(df_filtered, x="date", y=target_metric, 
                  title=f"Динамика {target_metric}",
                  render_mode="svg") # Для плавности
    
    fig.update_traces(line_shape='spline', line_smoothing=1.3, line_width=3, marker=dict(size=8))
    
    fig.update_layout(
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False, 
            rangeslider=dict(visible=True), # Возможность менять масштаб
            type='date'
        ),
        yaxis=dict(autorange=True, fixedrange=False, showgrid=True, gridcolor="#374151") # Автоподстройка
    )
    
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Посмотреть сырые данные таблицы"):
        st.dataframe(history)
