import streamlit as st
import pdfplumber
import re
import pandas as pd
import os
from datetime import datetime

INFLATION = 8

HISTORY_FILE = "history.csv"

def parse_number(x):
    return float(x.replace(",", ".")) if x else None

def extract_numbers(line):
    nums = re.findall(r'\d+,\d+', line)
    return [parse_number(n) for n in nums]

def extract_metric(text, label):
    match = re.search(rf"{label}.*", text)
    if not match:
        return None, None
    
    nums = extract_numbers(match.group(0))
    
    if len(nums) < 10:
        return None, None

    mtd = nums[5]
    index = (nums[9] - 1) * 100

    return mtd, index

def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        text = "\n".join([p.extract_text() for p in pdf.pages])

    data = {}

    data["Revenue"] = extract_metric(text, "Room Revenue")
    data["Breakfast"] = extract_metric(text, "Total revenue")
    data["Occupancy"] = extract_metric(text, "Occ-%")
    data["RevPAR"] = extract_metric(text, "RevPAR")
    data["Kitchen"] = extract_metric(text, "Rev. / efficient hour")
    data["Waiter"] = extract_metric(text, "Rev. / total hour")

    return data

def save_history(data):
    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    for k, v in data.items():
        row[k+"_mtd"] = v[0]
        row[k+"_idx"] = v[1]

    df_new = pd.DataFrame([row])

    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE)
        df = pd.concat([df, df_new])
    else:
        df = df_new

    df.to_csv(HISTORY_FILE, index=False)

def status(x):
    if x is None:
        return "—"
    if x > INFLATION:
        return "🟢"
    elif x > 0:
        return "🟡"
    return "🔴"

st.title("ChefBrain")

file = st.file_uploader("Загрузи PDF", type=["pdf"])

if file:
    data = parse_pdf(file)

    save_history(data)

    st.subheader("Сегодня")

    for k, v in data.items():
        st.write(f"{k}: {round(v[0],1) if v[0] else '—'} | {round(v[1],1) if v[1] else '—'}% {status(v[1])}")

if os.path.exists(HISTORY_FILE):
    st.subheader("История")

    df = pd.read_csv(HISTORY_FILE)

    st.dataframe(df.tail(10))

    st.subheader("Графики")

    st.line_chart(df.set_index("date")[[
        "Revenue_mtd",
        "RevPAR_mtd",
        "Occupancy_mtd"
    ]])

    st.line_chart(df.set_index("date")[[
        "Kitchen_mtd",
        "Waiter_mtd"
    ]])
