import os
import pandas as pd
import streamlit as st
from datetime import datetime

HISTORY_FILE = "history.csv"
INFLATION = 8

st.set_page_config(page_title="ChefBrain", layout="wide")

st.title("ChefBrain")

def save_history(hotel, data):
    today = datetime.now().strftime("%Y-%m-%d")

    row = {"date": today, "hotel": hotel}
    for k, v in data.items():
        row[f"{k}_mtd"] = v[0]
        row[f"{k}_idx"] = v[1]

    new_df = pd.DataFrame([row])

    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE)

        if "hotel" not in df.columns:
            df["hotel"] = "UNKNOWN"

        df = pd.concat([df, new_df], ignore_index=True)
    else:
        df = new_df

    df.to_csv(HISTORY_FILE, index=False)


def load_history():
    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE)

        if "hotel" not in df.columns:
            df["hotel"] = "UNKNOWN"

        return df

    return pd.DataFrame()


def show_metric(name, mtd, idx):
    color = "green" if idx and idx > INFLATION else "red"
    st.metric(name, f"{mtd}", f"{idx}%")

uploaded = st.file_uploader("Загрузи PDF")

if uploaded:
    # временные тестовые данные
    hotel = "PALACE BRIDGE"

    data = {
        "Revenue": (120000, 5),
        "Breakfast": (30000, 3),
        "Occupancy": (72, -2),
        "RevPAR": (5400, 4),
        "Kitchen": (1600, 6),
        "Waiter": (1300, 2),
    }

    save_history(hotel, data)

    st.subheader(f"Отель: {hotel}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Revenue", data["Revenue"][0], f"{data['Revenue'][1]}%")
    col2.metric("Breakfast", data["Breakfast"][0], f"{data['Breakfast'][1]}%")
    col3.metric("Occupancy", data["Occupancy"][0], f"{data['Occupancy'][1]}%")

    col4, col5, col6 = st.columns(3)
    col4.metric("RevPAR", data["RevPAR"][0], f"{data['RevPAR'][1]}%")
    col5.metric("Kitchen", data["Kitchen"][0], f"{data['Kitchen'][1]}%")
    col6.metric("Waiter", data["Waiter"][0], f"{data['Waiter'][1]}%")

history = load_history()

st.subheader("История")

if history.empty:
    st.write("Нет данных")
else:
    st.dataframe(history)

    st.subheader("Динамика Revenue")
    st.line_chart(history.set_index("date")["Revenue_idx"])
