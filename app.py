import pandas as pd
import streamlit as st

st.set_page_config(page_title="ChefBrain Excel", layout="wide")

# =====================
# HELPERS
# =====================
def parse_excel(file):
    df = pd.read_excel(file, sheet_name="Manager view", header=None)
    df_str = df.astype(str)

    # --- найти строку HOTEL TOTAL ---
    hotel_total_idx = None
    for i in range(len(df_str)):
        if "HOTEL TOTAL" in df_str.iloc[i, 0]:
            hotel_total_idx = i
            break

    if hotel_total_idx is None:
        return "UNKNOWN", {}

    # --- найти Total revenue НИЖЕ HOTEL TOTAL ---
    revenue_row = None
    for i in range(hotel_total_idx, len(df_str)):
        if df_str.iloc[i, 0] == "Total revenue":
            revenue_row = df.iloc[i]
            break

    # --- Revenue ---
    revenue_mtd = revenue_row[9] if revenue_row is not None else None
    revenue_idx = None

    if revenue_row is not None and pd.notna(revenue_row[35]):
        revenue_idx = round((revenue_row[35] - 1) * 100, 1)

    # --- Occupancy ---
    occ_row = df[df[0] == "Occ-%"].iloc[-1]
    occ_mtd = occ_row[2]
    occ_idx = round((occ_row[35] - 1) * 100, 1) if pd.notna(occ_row[35]) else None

    # --- RevPAR ---
    revpar_row = df[df[0] == "RevPAR"].iloc[-1]
    revpar_mtd = revpar_row[2]
    revpar_idx = round((revpar_row[35] - 1) * 100, 1) if pd.notna(revpar_row[35]) else None

    # --- Breakfast ---
    breakfast_block = df[df[0] == "BREAKFAST"].index
    if len(breakfast_block) > 0:
        start = breakfast_block[0]
        breakfast_row = df.iloc[start+4]  # Total revenue в блоке
        breakfast_mtd = breakfast_row[2]
        breakfast_idx = round((breakfast_row[35] - 1) * 100, 1) if pd.notna(breakfast_row[35]) else None
    else:
        breakfast_mtd, breakfast_idx = None, None

    # --- Kitchen ---
    kitchen_row = df[df[0] == "Rev. / ktch. hour"].iloc[-1]
    kitchen_mtd = kitchen_row[2]
    kitchen_idx = round((kitchen_row[35] - 1) * 100, 1) if pd.notna(kitchen_row[35]) else None

    # --- Service ---
    service_row = df[df[0] == "Rev. / wtrs. Hour"].iloc[-1]
    service_mtd = service_row[2]
    service_idx = round((service_row[35] - 1) * 100, 1) if pd.notna(service_row[35]) else None

    data = {
        "Revenue": (revenue_mtd, revenue_idx),
        "Breakfast": (breakfast_mtd, breakfast_idx),
        "Occupancy": (occ_mtd, occ_idx),
        "RevPAR": (revpar_mtd, revpar_idx),
        "Kitchen": (kitchen_mtd, kitchen_idx),
        "Waiter": (service_mtd, service_idx),
    }

    return "PALACE BRIDGE", data


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