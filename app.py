import pandas as pd
import streamlit as st

st.set_page_config(page_title="ChefBrain Excel", layout="wide")

# =====================
# HELPERS
# =====================
def extract_value_and_index(row):
    nums = [x for x in row if isinstance(x, (int, float))]

    if len(nums) < 2:
        return None, None

    mtd = nums[-3]   # обычно MTD ближе к концу
    idx_ratio = nums[-1]

    if idx_ratio is None:
        return mtd, None

    idx_pct = (idx_ratio - 1) * 100
    return mtd, round(idx_pct, 1)


def format_value(name, value):
    if value is None:
        return "нет данных"

    if name == "Occupancy":
        return f"{value:.1f}%"

    return f"{int(value):,}".replace(",", " ")


def format_idx(idx):
    if idx is None:
        return "нет данных"
    return f"{idx:+.1f}%"


def get_indicator(idx):
    if idx is None:
        return "•", "gray"

    if idx < 0:
        return "▼", "red"
    elif idx < 8:
        return "▲", "orange"
    else:
        return "▲", "green"


# =====================
# PARSER
# =====================
def parse_excel(file):
    df = pd.read_excel(file, sheet_name="Manager view", header=None)

    data = {}

    for i in range(len(df)):
        row = df.iloc[i].tolist()

        if not isinstance(row[0], str):
            continue

        name = row[0].lower()

        if "room revenue" in name:
            data["Revenue"] = extract_value_and_index(row)

        if name.strip() == "total revenue":
            data["Breakfast"] = extract_value_and_index(row)

        if "occ-%" in name:
            data["Occupancy"] = extract_value_and_index(row)

        if "revpar" in name:
            data["RevPAR"] = extract_value_and_index(row)

        if "efficient hour" in name:
            data["Kitchen"] = extract_value_and_index(row)

        if "wtrs. hour" in name:
            data["Service"] = extract_value_and_index(row)

    return data


# =====================
# UI
# =====================
st.title("ChefBrain (Excel версия)")

files = st.file_uploader(
    "Загрузи 1 или несколько Excel файлов",
    type=["xlsx"],
    accept_multiple_files=True
)

if files:
    all_data = {}

    for file in files:
        name = file.name.split(".")[0]
        data = parse_excel(file)
        all_data[name] = data

    # =====================
    # KPI ПО КАЖДОМУ ОТЕЛЮ
    # =====================
    for hotel, data in all_data.items():
        st.subheader(hotel)

        cols = st.columns(6)

        metrics = [
            ("Revenue", "Revenue"),
            ("Breakfast", "Breakfast"),
            ("Occupancy", "Occupancy"),
            ("RevPAR", "RevPAR"),
            ("Kitchen", "Kitchen"),
            ("Service", "Service"),
        ]

        for i, (title, key) in enumerate(metrics):
            val, idx = data.get(key, (None, None))

            arrow, color = get_indicator(idx)

            with cols[i]:
                st.metric(
                    label=title,
                    value=format_value(title, val),
                    delta=format_idx(idx)
                )

        st.divider()

    # =====================
    # СРАВНЕНИЕ
    # =====================
    if len(all_data) > 1:
        st.subheader("Сравнение отелей")

        compare = []

        for hotel, data in all_data.items():
            rev_idx = data.get("Revenue", (None, None))[1]

            compare.append({
                "Hotel": hotel,
                "Revenue %": rev_idx
            })

        df_compare = pd.DataFrame(compare).sort_values("Revenue %", ascending=False)

        st.dataframe(df_compare, use_container_width=True)