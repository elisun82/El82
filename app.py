
import streamlit as st
import pdfplumber
import re

INFLATION = 8

def extract_index(text, label):
    pattern = rf"{label}.*?(\d+,\d+)\s+(\d+,\d+)"
    match = re.search(pattern, text)
    if match:
        return float(match.group(2).replace(",", ".")) * 100 - 100
    return None

def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        text = "\n".join([p.extract_text() for p in pdf.pages])

    return {
        "Revenue": extract_index(text, "Room Revenue"),
        "Breakfast": extract_index(text, "BREAKFAST"),
        "Occupancy": extract_index(text, "Occ-%"),
        "RevPAR": extract_index(text, "RevPAR"),
        "Kitchen": extract_index(text, "Rev. / ktch. hour"),
        "Waiter": extract_index(text, "Rev. / wtrs. Hour"),
    }

def status(x):
    if x is None:
        return "—"
    if x > INFLATION:
        return "🟢"
    elif x > 0:
        return "🟡"
    else:
        return "🔴"

def summary(d):
    result = []
    if d["Revenue"] is not None and d["Revenue"] < INFLATION:
        result.append("КРИТИЧНО: выручка не перекрывает инфляцию")
    if d["RevPAR"] and d["Occupancy"] and d["RevPAR"] > d["Occupancy"]:
        result.append("Рост за счёт цены, а не загрузки")
    if d["Waiter"] and d["Waiter"] < 0:
        result.append("Проблема в официантах")
    return "\n".join(result)

st.title("ChefBrain")

file = st.file_uploader("Загрузи PDF отчёт")

if file:
    data = parse_pdf(file)

    st.subheader("Индексы к прошлому году")
    for k, v in data.items():
        if v is not None:
            st.write(f"{k}: {round(v,1)}% {status(v)}")
        else:
            st.write(f"{k}: нет данных")

    st.subheader("Вывод")
    st.write(summary(data))
