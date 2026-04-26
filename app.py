import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- CONFIG & STYLING ---
st.set_page_config(page_title="ChefBrain Dashboard", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 24px; }
    .main { background-color: #f5f7f9; }
    </style>
""", unsafe_allow_html=True)

# --- CORE DATA ENGINE ---
class ChefBrainData:
    @staticmethod
    def load_and_clean(file_path_or_buffer):
        try:
            df = pd.read_csv(file_path_or_buffer)
            
            # 1. Нормализация даты
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date'])
            
            # 2. Список KPI групп
            kpi_metrics = ['revpar', 'fb_total_revenue', 'service_hour', 'kitchen_hour', 'hotel_total_revenue']
            
            # 3. Принудительная конвертация в float и очистка
            for metric in kpi_metrics:
                cols = [f"{metric}_actual", f"{metric}_budget", f"{metric}_ly", f"{metric}_vs_budget", f"{metric}_vs_ly"]
                for col in cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            
            return df.sort_values(by='date', ascending=False)
        except Exception as e:
            st.error(f"Ошибка обработки данных: {e}")
            st.info(f"Доступные колонки: {list(df.columns) if 'df' in locals() else 'None'}")
            return pd.DataFrame()

# --- UI COMPONENTS ---
def delta_color(value):
    """Логика RAG: Red (< -5%), Amber (-5% to 0%), Green (> 0%)"""
    if value > 0: return "normal"
    if value < -5: return "inverse" # Красный
    return "off" # Серый/Желтый

def plot_kpi_trend(df, metric_name, hotel_name):
    """Компактный график тренда"""
    hotel_df = df[df['hotel'] == hotel_name].sort_values('date')
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hotel_df['date'], 
        y=hotel_df[f'{metric_name}_actual'],
        mode='lines+markers',
        name='Actual',
        line=dict(color='#1f77b4', width=3)
    ))
    fig.add_trace(go.Scatter(
        x=hotel_df['date'], 
        y=hotel_df[f'{metric_name}_budget'],
        mode='lines',
        name='Budget',
        line=dict(color='#ff7f0e', dash='dash')
    ))
    
    fig.update_layout(
        height=200,
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified"
    )
    return fig

# --- MAIN APP ---
def main():
    st.title("👨‍🍳 ChefBrain: Analytics")
    
    # Загрузка данных
    uploaded_file = st.sidebar.file_uploader("Загрузить историю (CSV)", type="csv")
    
    if uploaded_file is not None:
        data_engine = ChefBrainData()
        df = data_engine.load_and_clean(uploaded_file)
        
        if not df.empty:
            # Фильтры
            hotels = df['hotel'].unique()
            selected_hotel = st.sidebar.selectbox("Выберите отель", hotels)
            
            # Получаем последнюю запись по отелю
            latest_data = df[df['hotel'] == selected_hotel].iloc[0]
            st.subheader(f"KPI: {selected_hotel} на {latest_data['date'].strftime('%d.%m.%Y')}")
            
            # --- KPI GRID ---
            kpis = [
                ("Total Revenue", "hotel_total_revenue"),
                ("F&B Revenue", "fb_total_revenue"),
                ("RevPAR", "revpar"),
                ("Service Hour", "service_hour"),
                ("Kitchen Hour", "kitchen_hour")
            ]
            
            cols = st.columns(len(kpis))
            
            for i, (label, key) in enumerate(kpis):
                actual = latest_data[f"{key}_actual"]
                vs_budget = latest_data[f"{key}_vs_budget"]
                
                with cols[i]:
                    st.metric(
                        label=label,
                        value=f"{actual:,.0f}".replace(",", " "),
                        delta=f"{vs_budget:.1f}% vs Bud",
                        delta_color=delta_color(vs_budget)
                    )
            
            st.divider()
            
            # --- TRENDS ---
            st.subheader("Анализ трендов")
            t_col1, t_col2 = st.columns(2)
            
            with t_col1:
                st.plotly_chart(plot_kpi_trend(df, "fb_total_revenue", selected_hotel), use_container_width=True)
                st.plotly_chart(plot_kpi_trend(df, "kitchen_hour", selected_hotel), use_container_width=True)
            
            with t_col2:
                st.plotly_chart(plot_kpi_trend(df, "service_hour", selected_hotel), use_container_width=True)
                st.plotly_chart(plot_kpi_trend(df, "revpar", selected_hotel), use_container_width=True)

            # --- DATA TABLE ---
            with st.expander("Посмотреть историю (Raw Data)"):
                st.dataframe(df[df['hotel'] == selected_hotel], use_container_width=True)
    else:
        st.info("Пожалуйста, загрузите CSV файл с историей для начала анализа.")

if __name__ == "__main__":
    main()
