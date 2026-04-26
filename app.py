import os
import re
from datetime import datetime
import pandas as pd
import pdfplumber
import requests
import streamlit as st
import plotly.graph_objects as go

# --- Конфигурация ---
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]
st.set_page_config(page_title="ChefBrain Analytics v5", layout="wide")

# --- Стилизация ---
st.markdown("""
<style>
.block-container {padding-top:1rem; max-width:1400px;}
.hero-box {
    background: linear-gradient(90deg, #1e293b 0%, #0f172a 100%);
    padding: 20px; border-radius: 15px; margin-bottom: 20px; border: 1px solid #334155;
}
.kpi-card {background:#1e293b; padding:15px; border-radius:12px; border:1px solid #334155;}
</style>
""", unsafe_allow_html=True)

# --- Улучшенная логика извлечения ---
def clean_num(s):
    if not s: return None
    # Очистка от валют, мусора и спецсимволов
    s = re.sub(r"[^0-9.,-]", "", s.replace("\xa0", "").replace(" ", ""))
    if not s: return None
    # Обработка европейского формата 1.234,56 или американского 1,234.56
    if "," in s and "." in s: s = s.replace(",", "")
    elif "," in s: s = s.replace(",", ".")
    try: return float(s)
    except: return None

def get_numbers_from_text(text):
    """Ищет все числа в строке, учитывая возможные пробелы-разделители."""
    # Ищем группы цифр, которые могут быть разделены пробелом или точкой (разделитель тысяч)
    pattern = r"[-+]?\d{1,3}(?:[ \u00A0.]\d{3})*(?:,\d+)?"
    matches = re.findall(pattern, text)
    return [clean_num(m) for m in matches if clean_num(m) is not None]

def extract_mtd_values(lines, keyword, second_keyword=None):
    """
    Логика для Daily Revenue Report:
    Обычно Accum Actual, Accum Budget и Accum LY идут в 4-й и 5-й колонках (блоках).
    """
    for line in lines:
        if keyword.upper() in line.upper():
            if second_keyword and second_keyword.upper() not in line.upper():
                continue
            
            # В твоем PDF данные разделены на блоки (ячейки)
            # Мы берем все числа из строки и пытаемся найти MTD-блок.
            # В структуре отчета MTD обычно начинается с 5-го по 8-е число в ряду.
            nums = get_numbers_from_text(line)
            
            if len(nums) >= 6:
                # Стандартная структура для твоего PDF (Accum Actual, Accum Budget, Accum LY)
                # Эти значения обычно находятся во второй половине списка чисел строки
                act = nums[4] if len(nums) > 4 else None
                bud = nums[5] if len(nums) > 5 else None
                ly = nums[-1] if len(nums) > 0 else None 
                
                # Защита от попадания 'Daily' вместо 'Accum'
                if act and act < 1000 and "Revenue" in keyword: # Если число слишком маленькое для выручки
                    act = nums[len(nums)//2] 
                
                vs_bu = round((act/bud - 1)*100, 1) if act and bud else None
                vs_ly = round((act/ly - 1)*100, 1) if act and ly else None
                return [act, bud, ly, vs_bu, vs_ly]
    return [None]*5

# --- Работа с Google Sheets (БД) ---
def load_history():
    try:
        url = st.secrets["GOOGLE_SCRIPT_URL"]
        resp = requests.get(url, params={"key": st.secrets["CHEFBRAIN_SECRET_KEY"]}, timeout=10)
        df = pd.DataFrame(resp.json().get("rows", []))
        if not df.empty:
            for col in df.columns:
                if col not in ["date", "hotel"]: df[col] = pd.to_numeric(df[col], errors="coerce")
            df["date"] = pd.to_datetime(df["date"])
        return df
    except: return pd.DataFrame()

def save_to_db(date, hotel, data):
    row = {"date": date, "hotel": hotel}
    for k, v in data.items():
        row.update({f"{k}_actual": v[0], f"{k}_budget": v[1], f"{k}_ly": v[2], f"{k}_vs_budget": v[3], f"{k}_vs_ly": v[4]})
    
    payload = {"key": st.secrets["CHEFBRAIN_SECRET_KEY"], "rows": [row]}
    try: requests.post(st.secrets["GOOGLE_SCRIPT_URL"], json=payload, timeout=15)
    except: st.error("Ошибка сохранения в базу")

# --- Интерфейс ---
st.markdown('<div class="hero-box"><h1 style="margin:0; color:white;">ChefBrain Analytics v5.0</h1></div>', unsafe_allow_html=True)

uploaded_file = st.file_uploader("Загрузи Daily Revenue Report (PDF)", type="pdf")

if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        # Извлекаем текст, сохраняя структуру колонок насколько возможно
        text_pages = [page.extract_text(layout=True) for page in pdf.pages]
        full_text = "\n".join(text_pages)
        lines = full_text.splitlines()

    # Парсинг заголовка
    hotel = next((h for h in HOTELS if h in full_text.upper()), "UNKNOWN")
    date_match = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", full_text)
    doc_date = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}" if date_match else datetime.now().strftime("%Y-%m-%d")

    # Извлечение KPI (с учетом специфики твоего PDF)
    data = {
        "revpar": extract_mtd_values(lines, "RevPAR"),
        "fb_total_revenue": extract_mtd_values(lines, "Tokal revenue", "Food"), # Ищем Total Revenue именно в блоке F&B
        "service_hour": extract_mtd_values(lines, "Rev/wtrs. Hoor"),
        "kitchen_hour": extract_mtd_values(lines, "Rev/koch. hour"),
        "hotel_total_revenue": extract_mtd_values(lines, "Total revenue", "Hours") # Общая выручка отеля
    }

    save_to_db(doc_date, hotel, data)
    
    st.success(f"Данные за {doc_date} ({hotel}) успешно обработаны!")

    # Виджеты KPI
    cols = st.columns(5)
    metrics_labels = [("RevPAR", "revpar"), ("F&B Rev", "fb_total_revenue"), ("Service", "service_hour"), ("Kitchen", "kitchen_hour"), ("Total Rev", "hotel_total_revenue")]
    
    for i, (label, key) in enumerate(metrics_labels):
        vals = data[key]
        with cols[i]:
            st.metric(label, f"{vals[0]:,.0f}".replace(",", " ") if vals[0] else "—", 
                      delta=f"{vals[4]:+.1f}% vs LY" if vals[4] else None)
            st.caption(f"Budget: {vals[1]:,.0f}".replace(",", " ") if vals[1] else "")

# --- Аналитика и Графики ---
history = load_history()
if not history.empty:
    st.divider()
    
    col_l, col_r = st.columns([1, 3])
    with col_l:
        st.subheader("Сравнение")
        latest = history.sort_values("date").groupby("hotel").last().reset_index()
        for _, row in latest.iterrows():
            v = row.get("hotel_total_revenue_vs_ly", 0)
            color = "#22c55e" if v > 0 else "#ef4444"
            st.markdown(f"""
            <div class="kpi-card" style="margin-bottom:10px;">
                <div style="font-size:0.8rem; color:#94a3b8;">{row['hotel']}</div>
                <div style="font-size:1.2rem; font-weight:bold; color:{color};">{v:+.1f}% <span style="font-size:0.7rem; color:#94a3b8;">vs LY</span></div>
            </div>
            """, unsafe_allow_html=True)

    with col_r:
        st.subheader("Тренды показателей")
        target_hotel = st.selectbox("Выберите отель", history["hotel"].unique())
        metric_choice = st.selectbox("Показатель", ["hotel_total_revenue_actual", "revpar_actual", "fb_total_revenue_actual"])
        
        df_plot = history[history["hotel"] == target_hotel].sort_values("date")
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_plot["date"], y=df_plot[metric_choice],
            mode='lines+markers',
            line=dict(shape='spline', smoothing=1.3, width=3, color='#3b82f6'),
            marker=dict(size=7),
            name="Actual"
        ))
        
        fig.update_layout(
            template="plotly_dark",
            height=400,
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis=dict(rangeslider=dict(visible=True), type='date'),
            yaxis=dict(autorange=True, fixedrange=False, gridcolor="#334155")
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("Просмотр сырых данных (база)"):
        st.dataframe(history.sort_values("date", ascending=False))
