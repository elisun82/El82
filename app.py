import re
import pdfplumber
import streamlit as st
import pandas as pd

st.set_page_config(page_title="ChefBrain Palace Debug", layout="wide")

st.markdown("## ChefBrain — PALACE BRIDGE debug")

def normalize_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "")

def parse_number(value):
    if value is None:
        return None

    s = str(value).replace("RUR", "").replace("%", "").strip()

    # 24 082 425
    if " " in s and "," not in s and "." not in s:
        s = s.replace(" ", "")
        try:
            return float(s)
        except:
            return None

    # 24,082,425
    if "," in s and "." not in s:
        parts = s.split(",")
        if len(parts) > 1 and all(p.isdigit() for p in parts) and all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
            try:
                return float(s)
            except:
                return None
        else:
            s = s.replace(",", ".")
            try:
                return float(s)
            except:
                return None

    # 1.04
    if "." in s and "," not in s:
        try:
            return float(s)
        except:
            return None

    # 1,04 or 87,2
    if "," in s and "." not in s:
        s = s.replace(",", ".")
        try:
            return float(s)
        except:
            return None

    try:
        return float(s)
    except:
        return None

def extract_tokens(line):
    cleaned = line.replace("RUR", "").replace("%", "").replace("\xa0", " ")
    tokens = re.findall(r"\d[\d\s,]*(?:[.,]\d+)?", cleaned)
    return [t.strip() for t in tokens if t.strip()]

def parse_metric_line(line):
    """
    Ожидаем:
    day act / day bud / day ly / day bud idx / day ly idx /
    MTD act / MTD bud / MTD ly / MTD bud idx / MTD ly idx
    """
    if not line:
        return None, None

    tokens = extract_tokens(line)

    if len(tokens) < 10:
        return None, None

    mtd_value = parse_number(tokens[5])

    idx_raw = tokens[9].replace(" ", "")
    if "," in idx_raw and "." in idx_raw:
        idx_raw = idx_raw.replace(",", "")
    else:
        idx_raw = idx_raw.replace(",", ".")

    try:
        idx_ratio = float(idx_raw)
        idx_pct = round((idx_ratio - 1.0) * 100, 1)
    except:
        idx_pct = None

    return mtd_value, idx_pct

def format_value(name, value):
    if value is None:
        return "нет данных"
    if name == "Occupancy":
        return f"{value:.1f}%"
    return f"{value:,.0f}".replace(",", " ")

def format_idx(idx):
    if idx is None:
        return "нет данных"
    return f"{idx:+.1f}%"

def get_indicator(idx):
    if idx is None:
        return "•", "#9CA3AF", "нет данных"
    if idx < 0:
        return "▼", "#EF4444", "ниже LY"
    if idx < 8:
        return "▲", "#F59E0B", "ниже инфляции"
    return "▲", "#22C55E", "выше инфляции"

def show_metric(col, name, value, idx):
    arrow, color, label = get_indicator(idx)
    with col:
        st.markdown(f"**{name}**")
        st.metric("", format_value(name, value))
        st.markdown(
            f"<span style='color:{color}; font-weight:700; font-size:18px;'>{arrow} {format_idx(idx)}</span>",
            unsafe_allow_html=True
        )
        st.caption(label)

uploaded_file = st.file_uploader("Загрузи PDF PALACE BRIDGE", type=["pdf"])

if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        pages = []
        for page in pdf.pages:
            txt = page.extract_text() or ""
            pages.append(normalize_spaces(txt))
        text = "\n".join(pages)

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # -------- ACCOMMODATION block --------
    acc_start = next((i for i, l in enumerate(lines) if "ACCOMMODATION" in l.upper()), None)
    br_start = next((i for i, l in enumerate(lines) if "BREAKFAST" in l.upper()), None)

    if acc_start is not None and br_start is not None and br_start > acc_start:
        acc_lines = lines[acc_start:br_start]
    else:
        acc_lines = lines

    # -------- BREAKFAST block --------
    if br_start is not None:
        next_sections = []
        for keyword in ["MEETING & EVENTS", "MAIN RESTAURANT", "TOTAL KITCHEN", "WELLNESS CLUB"]:
            idx = next((i for i, l in enumerate(lines[br_start + 1:], start=br_start + 1) if keyword in l.upper()), None)
            if idx is not None:
                next_sections.append(idx)

        br_end = min(next_sections) if next_sections else len(lines)
        br_lines = lines[br_start:br_end]
    else:
        br_lines = []

    # -------- GLOBAL SEARCH --------
    def first_startswith(pool, prefix):
        prefix = prefix.lower()
        for line in pool:
            if line.lower().startswith(prefix):
                return line
        return None

    def last_contains(pool, phrase):
        phrase = phrase.lower()
        for line in reversed(pool):
            if phrase in line.lower():
                return line
        return None

    revenue_line = first_startswith(acc_lines, "room revenue")
    breakfast_line = first_startswith(br_lines, "total revenue")
    occupancy_line = first_startswith(acc_lines, "occ-%")
    revpar_line = first_startswith(acc_lines, "revpar")
    kitchen_line = last_contains(lines, "rev. / efficient hour")
    service_line = last_contains(lines, "rev. / wtrs. hour")

    revenue = parse_metric_line(revenue_line)
    breakfast = parse_metric_line(breakfast_line)
    occupancy = parse_metric_line(occupancy_line)
    revpar = parse_metric_line(revpar_line)
    kitchen = parse_metric_line(kitchen_line)
    service = parse_metric_line(service_line)

    st.subheader("Отель: PALACE BRIDGE")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    show_metric(c1, "Revenue", revenue[0], revenue[1])
    show_metric(c2, "Breakfast", breakfast[0], breakfast[1])
    show_metric(c3, "Occupancy", occupancy[0], occupancy[1])
    show_metric(c4, "RevPAR", revpar[0], revpar[1])
    show_metric(c5, "Kitchen", kitchen[0], kitchen[1])
    show_metric(c6, "Service", service[0], service[1])

    st.markdown("---")
    st.subheader("Диагностика: какие строки реально найдены")

    debug_df = pd.DataFrame(
        [
            ["Revenue", revenue_line],
            ["Breakfast", breakfast_line],
            ["Occupancy", occupancy_line],
            ["RevPAR", revpar_line],
            ["Kitchen", kitchen_line],
            ["Service", service_line],
        ],
        columns=["Metric", "Found line"]
    )
    st.dataframe(debug_df, use_container_width=True, hide_index=True)