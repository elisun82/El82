
import streamlit as st
import pdfplumber
import re

INFLATION = 8.0

def normalize_spaces(s):
    return re.sub(r"[ \t]+", " ", s)

def parse_number(num_str):
    if num_str is None:
        return None
    s = num_str.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except:
        return None

def extract_section(text, start_label, end_label=None):
    start = text.find(start_label)
    if start == -1:
        return None
    if end_label:
        end = text.find(end_label, start + len(start_label))
        if end != -1:
            return text[start:end]
    return text[start:]

def extract_mtd_from_line(line):
    nums = re.findall(r'\d[\d ]*(?:,\d+)?', line)
    if len(nums) < 10:
        return None, None
    mtd_actual = parse_number(nums[5])
    yoy_index_ratio = parse_number(nums[9])
    yoy_index_pct = (yoy_index_ratio - 1.0) * 100 if yoy_index_ratio is not None else None
    return mtd_actual, yoy_index_pct

def find_line(text, label):
    pattern = rf'^{re.escape(label)}.*$'
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(0) if match else None

def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        for p in pdf.pages:
            txt = p.extract_text() or ""
            pages.append(normalize_spaces(txt))
        text = "\n".join(pages)

    accommodation = extract_section(text, "ACCOMMODATION 3675010", "BREAKFAST 3675014") or text
    breakfast_sec = extract_section(text, "BREAKFAST 3675014", "PB MEETING & EVENTS 3675011") or text
    total_fb_sec = extract_section(text, "TOTAL F&B, M&E REVENUE", "HOTEL TOTAL") or text

    metrics = {}

    line = find_line(accommodation, "Room Revenue")
    metrics["Revenue"] = extract_mtd_from_line(line) if line else (None, None)

    line = find_line(breakfast_sec, "Total revenue")
    metrics["Breakfast"] = extract_mtd_from_line(line) if line else (None, None)

    line = find_line(accommodation, "Occ-%")
    metrics["Occupancy"] = extract_mtd_from_line(line) if line else (None, None)

    line = find_line(accommodation, "RevPAR")
    metrics["RevPAR"] = extract_mtd_from_line(line) if line else (None, None)

    line = find_line(total_fb_sec, "Rev. / efficient hour")
    if not line:
        line = find_line(text, "Rev. / efficient hour")
    metrics["Kitchen"] = extract_mtd_from_line(line) if line else (None, None)

    line = find_line(total_fb_sec, "Rev. / total hour")
    if not line:
        line = find_line(text, "Rev. / total hour")
    metrics["Waiter"] = extract_mtd_from_line(line) if line else (None, None)

    return metrics

def status(x):
    if x is None:
        return "—"
    if x > INFLATION:
        return "🟢"
    elif x > 0:
        return "🟡"
    return "🔴"

def fmt_val(x, metric):
    if x is None:
        return "нет данных"
    if metric == "Occupancy":
        return f"{x:.1f}%"
    return f"{x:,.0f}".replace(",", " ")

def fmt_pct(x):
    if x is None:
        return "нет данных"
    return f"{x:+.1f}%"

def build_summary(d):
    out = []
    revenue_idx = d["Revenue"][1]
    breakfast_idx = d["Breakfast"][1]
    occ_idx = d["Occupancy"][1]
    revpar_idx = d["RevPAR"][1]
    kitchen_idx = d["Kitchen"][1]
    waiter_idx = d["Waiter"][1]

    if revenue_idx is not None and revenue_idx < INFLATION:
        out.append("КРИТИЧНО: выручка не перекрывает инфляцию")
    if revpar_idx is not None and occ_idx is not None and revpar_idx > occ_idx:
        out.append("Рост идёт за счёт цены, а не загрузки")
    if breakfast_idx is not None and breakfast_idx < INFLATION:
        out.append("Завтрак растёт ниже инфляции")
    if kitchen_idx is not None and waiter_idx is not None:
        if kitchen_idx > waiter_idx:
            out.append("Эффективность кухни выше сервиса")
        elif waiter_idx > kitchen_idx:
            out.append("Эффективность сервиса выше кухни")

    if not out:
        out.append("Критичных отклонений не найдено")
    return out

st.set_page_config(page_title="ChefBrain", layout="wide")
st.title("ChefBrain")
st.caption("Загрузи PDF-отчёт и получи MTD-факт + индекс к прошлому году")

file = st.file_uploader("Загрузи PDF отчёт", type=["pdf"])

if file:
    data = parse_pdf(file)

    st.subheader("Показатели на текущую дату месяца")
    c1, c2, c3 = st.columns([2.1, 1.3, 1.2])
    with c1:
        st.markdown("**Показатель**")
    with c2:
        st.markdown("**MTD факт**")
    with c3:
        st.markdown("**Индекс к LY**")

    for metric, (mtd_actual, yoy_pct) in data.items():
        c1, c2, c3 = st.columns([2.1, 1.3, 1.2])
        with c1:
            st.write(metric)
        with c2:
            st.write(fmt_val(mtd_actual, metric))
        with c3:
            st.write(f"{fmt_pct(yoy_pct)} {status(yoy_pct)}")

    st.subheader("Вывод")
    for item in build_summary(data):
        st.write(f"• {item}")
