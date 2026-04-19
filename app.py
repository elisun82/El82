import os
import pandas as pd
import streamlit as st
from datetime import datetime

st.write("VERSION CHECK 002")
HISTORY_FILE = "history.csv"

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


st.title("ChefBrain")

uploaded_file = st.file_uploader("Загрузи PDF")

if uploaded_file:
    hotel = "TEST HOTEL"
    metrics = {
        "Revenue": (100000, 5),
        "Breakfast": (20000, 3),
        "Occupancy": (70, -2),
        "RevPAR": (5000, 4),
        "Kitchen": (1500, 6),
        "Waiter": (1200, 2),
    }

    save_history(hotel, metrics)
    st.success("Файл обработан")

history = load_history()

st.subheader("История")

if history.empty:
    st.write("Нет данных")
else:
    st.dataframe(history)
