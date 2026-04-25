import os
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import streamlit as st

# =====================
# SETTINGS
# =====================
HISTORY_FILE = "history_accum_v3.csv"
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]

st.set_page_config(page_title="ChefBrain", layout="wide")

# =====================
# STYLES
# =====================
st.markdown("""
<style>
.block-container {
    padding-top: 1rem;
    padding-bottom: 2rem;
    max-width: 1450px;
}
.hero-box {
    background: linear-gradient(180deg, #101828 0%, #0B1220 100%);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 18px;
    padding: 18px 22px;
    margin-bottom: 16px;
}
.hero-title {
    font-size: 30px;
    font-weight: 800;
    color: #F9FAFB;
    margin-bottom: 4px;
}
.hero-subtitle {
    color: #9CA3AF;
    font-size: 13px;
}
.summary-box {
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 10px;
    font-size: 15px;
}
.small-note {
    font-size: 12px;
    color: #94A3B8;
    margin-top: -6px;
    margin-bottom: 12px;
}
.kpi-warning {
    border-left: 4px solid #991B1B;
    background: #FEE2E2;
    color: #991B1B;
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 10px;
    font-size: 15px;
}
.kpi-caution {
    border-left: 4px solid #92400E;
    background: #FEF3C7;
    color: #92400E;
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 10px;
    font-size: 15px;
}
.kpi-good {
    border-left: 4px solid #166534;
    background: #DCFCE7;
    color: #166534;
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 10px;
    font-size: 15px;
}
</style>
""", unsafe_allow_html=True)

# =====================
# HELPERS
# =====================
NUM_PATTERN = re.compile(
    r"\d{1,3}(?:[ \u00A0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
)

DATE_PATTERNS = [
    re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b"),
    re.compile(r"\b(\d{2}/\d{2}/\d{4})\b"),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
]

def normalize_spaces(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "")

def split_lines(text: str):
    return [line.strip() for line in text.splitlines() if line.strip()]

def detect_hotel(text: str) -> str:
    upper = text.upper()
    for hotel in HOTELS:
        if hotel in upper:
            return hotel
    return "UNKNOWN"

def parse_number(value):
    if value is None:
        return None

    s = str(value).replace("RUR", "").replace("%", "").replace("\xa0", " ").strip()

    if " " in s and "," not in s and "." not in s:
        try:
            return float(s.replace(" ", ""))
        except Exception:
            return None

    if "," in s and "." not in s:
        parts = s.split(",")

        if len(parts) > 1 and all(p.isdigit() for p in parts) and all(len(p) == 3 for p in parts[1:]):
            try:
                return float("".join(parts))
            except Exception:
                return None

        try:
            return float(s.replace(",", "."))
        except Exception:
            return None

    if "." in s:
        try:
            return float(s)
        except Exception:
            return None

    try:
        return float(s)
    except Exception:
        return None

def extract_tokens(line: str):
    cleaned = (
        line.replace("RUR", "")
            .replace("%", "")
            .replace("\xa0", " ")
            .strip()
    )
    return [m.group(0).strip() for m in NUM_PATTERN.finditer(cleaned)]

def safe_pct(actual, reference):
    if actual is None or reference is None or reference == 0:
        return None
    return round((actual / reference - 1.0) * 100, 1)

def format_value(metric_name: str, value):
    if value is None:
        return "нет данных"
    return f"{value:,.0f}".replace(",", " ")

def format_pct(value):
    if value is None:
        return "нет данных"
    return f"{value:+.1f}%"

def fmt_pct(x):
    if pd.isna(x):
        return "—"
    return f"{x:+.1f}%"

def get_color_for_delta(value):
    if value is None:
        return "#9CA3AF"
    if value < 0:
        return "#EF4444"
    if value == 0:
        return "#F59E0B"
    return "#22C55E"

def get_section_lines(text, start_keywords, end_keywords=None):
    lines = split_lines(text)
    start_idx = None

    for i, line in enumerate(lines):
        low = line.lower()
        if all(k.lower() in low for k in start_keywords):
            start_idx = i
            break

    if start_idx is None:
        return []

    if not end_keywords:
        return lines[start_idx:]

    for j in range(start_idx + 1, len(lines)):
        low = lines[j].lower()
        if all(k.lower() in low for k in end_keywords):
            return lines[start_idx:j]

    return lines[start_idx:]

def find_first_line(lines, includes=None, startswith=None):
    includes = [x.lower() for x in (includes or [])]
    startswith = startswith.lower() if startswith else None

    for line in lines:
        low = line.lower()
        if startswith and not low.startswith(startswith):
            continue
        if includes and not all(x in low for x in includes):
            continue
        return line
    return None

def extract_month_accum_values(line: str):
    """
    Day: Act | Bu | LY | idx_bu | idx_ly
    Month: Accum | Bu.Accum | LY.Accum | idx_bu | idx_ly

    [5] = Accum
    [6] = Bu.Accum
    [7] = LY.Accum
    """
    if not line:
        return None, None, None, None, None

    tokens = extract_tokens(line)

    if len(tokens) < 8:
        return None, None, None, None, None

    actual = parse_number(tokens[5])
    budget = parse_number(tokens[6])
    ly = parse_number(tokens[7])

    vs_budget = safe_pct(actual, budget)
    vs_ly = safe_pct(actual, ly)

    return actual, budget, ly, vs_budget, vs_ly

def extract_doc_date(first_page_text: str):
    lines = split_lines(first_page_text)
    header_lines = lines[:8]

    for line in header_lines:
        for pattern in DATE_PATTERNS:
            m = pattern.search(line)
            if m:
                raw = m.group(1)
                for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        pass

    return datetime.now().strftime("%Y-%m-%d")

# =====================
# PARSER
# =====================
def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        first_page_text = ""
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            txt = normalize_spaces(txt)
            if i == 0:
                first_page_text = txt
            pages.append(txt)
        text = "\n".join(pages)

    doc_date = extract_doc_date(first_page_text)
    hotel = detect_hotel(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast"])
    total_fb_lines = get_section_lines(text, ["total f&b", "m&e revenue"], ["total spa"])
    hotel_total_lines = get_section_lines(text, ["hotel total"], ["month", "year"])
    if not hotel_total_lines:
        hotel_total_lines = get_section_lines(text, ["hotel total"])

    data = {}

    line = find_first_line(accommodation_lines, startswith="revpar")
    data["revpar"] = extract_month_accum_values(line)

    line = find_first_line(total_fb_lines, startswith="total revenue")
    data["fb_total_revenue"] = extract_month_accum_values(line)

    line = find_first_line(total_fb_lines, includes=["rev.", "wtrs. hour"])
    data["service_hour"] = extract_month_accum_values(line)

    line = find_first_line(total_fb_lines, includes=["rev.", "ktch. hour"])
    data["kitchen_hour"] = extract_month_accum_values(line)

    line = find_first_line(hotel_total_lines, startswith="total revenue")
    data["hotel_total_revenue"] = extract_month_accum_values(line)

    return doc_date, hotel, data

# =====================
# HISTORY
# =====================
def flatten_history_row(doc_date, hotel, data):
    row = {"date": doc_date, "hotel": hotel}

    for metric_key, values in data.items():
        actual, budget, ly, vs_budget, vs_ly = values
        row[f"{metric_key}_actual"] = actual
        row[f"{metric_key}_budget"] = budget
        row[f"{metric_key}_ly"] = ly
        row[f"{metric_key}_vs_budget"] = vs_budget
        row[f"{metric_key}_vs_ly"] = vs_ly

    return row

def save_history(doc_date, hotel, data):
    row = flatten_history_row(doc_date, hotel, data)
    new_df = pd.DataFrame([row])

    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE)

        for col in new_df.columns:
            if col not in df.columns:
                df[col] = pd.NA

        df = df[~((df["date"] == doc_date) & (df["hotel"] == hotel))]
        df = pd.concat([df, new_df], ignore_index=True)
    else:
        df = new_df

    df.to_csv(HISTORY_FILE, index=False)

def load_history():
    if os.path.exists(HISTORY_FILE):
        return pd.read_csv(HISTORY_FILE)
    return pd.DataFrame()

def latest_rows_by_hotel(df):
    if df.empty:
        return pd.DataFrame()

    return (
        df.sort_values("date")
          .groupby("hotel", as_index=False)
          .tail(1)
          .sort_values("hotel")
    )

# =====================
# SUMMARY
# =====================
def build_summary(data):
    notes = []

    hotel_total_vs_ly = data["hotel_total_revenue"][4]
    hotel_total_vs_budget = data["hotel_total_revenue"][3]
    revpar_vs_ly = data["revpar"][4]
    fb_total_vs_ly = data["fb_total_revenue"][4]
    service_vs_ly = data["service_hour"][4]
    kitchen_vs_ly = data["kitchen_hour"][4]

    if hotel_total_vs_ly is not None:
        if hotel_total_vs_ly < 0:
            notes.append(("Общая выручка отеля ниже прошлого года.", "bad"))
        elif hotel_total_vs_ly < 8:
            notes.append(("Общая выручка отеля растёт, но слабее ожидаемого темпа.", "warn"))
        else:
            notes.append(("Общая выручка отеля показывает сильный рост к прошлому году.", "good"))

    if hotel_total_vs_budget is not None:
        if hotel_total_vs_budget < 0:
            notes.append(("Факт отеля ниже бюджета месяца.", "bad"))
        else:
            notes.append(("Факт отеля держится выше бюджета месяца.", "good"))

    if revpar_vs_ly is not None:
        if revpar_vs_ly < 0:
            notes.append(("RevPAR ниже прошлого года.", "bad"))
        else:
            notes.append(("RevPAR выше прошлого года.", "good"))

    if fb_total_vs_ly is not None:
        if fb_total_vs_ly < 0:
            notes.append(("F&B total revenue проседает к прошлому году.", "bad"))
        else:
            notes.append(("F&B total revenue растёт к прошлому году.", "good"))

    if service_vs_ly is not None and kitchen_vs_ly is not None:
        if service_vs_ly > kitchen_vs_ly:
            notes.append(("Эффективность сервиса растёт быстрее кухни.", "good"))
        elif kitchen_vs_ly > service_vs_ly:
            notes.append(("Эффективность кухни растёт быстрее сервиса.", "good"))
        else:
            notes.append(("Кухня и сервис показывают схожую динамику.", "warn"))

    return notes

def build_alerts(data):
    alerts = []

    hotel_total_vs_budget = data["hotel_total_revenue"][3]
    hotel_total_vs_ly = data["hotel_total_revenue"][4]
    revpar_vs_ly = data["revpar"][4]
    fb_total_vs_ly = data["fb_total_revenue"][4]
    service_vs_ly = data["service_hour"][4]
    kitchen_vs_ly = data["kitchen_hour"][4]

    if hotel_total_vs_budget is not None and hotel_total_vs_budget < 0:
        alerts.append(("Отель ниже бюджета месяца.", "bad"))

    if hotel_total_vs_ly is not None and hotel_total_vs_ly < 0:
        alerts.append(("Общая выручка отеля ниже прошлого года.", "bad"))

    if fb_total_vs_ly is not None and fb_total_vs_ly < 0:
        alerts.append(("F&B total revenue ниже прошлого года.", "bad"))

    if revpar_vs_ly is not None and revpar_vs_ly < 0:
        alerts.append(("RevPAR ниже прошлого года.", "warn"))

    if (
        service_vs_ly is not None and kitchen_vs_ly is not None
        and abs(service_vs_ly - kitchen_vs_ly) >= 10
    ):
        alerts.append(("Сильный разрыв динамики между сервисом и кухней.", "warn"))

    if not alerts:
        alerts.append(("Критичных отклонений не найдено.", "good"))

    return alerts

def render_summary_block(notes):
    if not notes:
        return

    st.subheader("Вывод")

    color_map = {
        "good": ("#166534", "#DCFCE7"),
        "warn": ("#92400E", "#FEF3C7"),
        "bad": ("#991B1B", "#FEE2E2"),
    }

    for text, level in notes:
        color, bg = color_map.get(level, ("#374151", "#F3F4F6"))
        st.markdown(
            f"""
            <div class="summary-box" style="border-left: 4px solid {color}; background: {bg}; color: {color};">
                {text}
            </div>
            """,
            unsafe_allow_html=True
        )

def render_alert_block(alerts):
    st.subheader("Красные зоны")

    for text, level in alerts:
        if level == "bad":
            st.markdown(f"<div class='kpi-warning'>{text}</div>", unsafe_allow_html=True)
        elif level == "warn":
            st.markdown(f"<div class='kpi-caution'>{text}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='kpi-good'>{text}</div>", unsafe_allow_html=True)

# =====================
# UI HELPERS
# =====================
def show_metric_block(col, section_name, title, metric_name, values):
    actual, budget, ly, vs_budget, vs_ly = values
    color_budget = get_color_for_delta(vs_budget)
    color_ly = get_color_for_delta(vs_ly)

    with col:
        st.markdown(f"**{section_name}**")
        st.markdown(f"<div class='small-note'>{title}</div>", unsafe_allow_html=True)
        st.metric(label=" ", value=format_value(metric_name, actual))
        st.markdown(
            f"<span style='color:{color_budget}; font-weight:700;'>vs Bu. Accum.: {format_pct(vs_budget)}</span>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<span style='color:{color_ly}; font-weight:700;'>vs LY. Accum.: {format_pct(vs_ly)}</span>",
            unsafe_allow_html=True
        )
        st.markdown(
            f"<span class='small-note'>Bu: {format_value(metric_name, budget)} | LY: {format_value(metric_name, ly)}</span>",
            unsafe_allow_html=True
        )

def build_compare_table(latest):
    rows = []
    for _, row in latest.iterrows():
        rows.append({
            "Hotel": row["hotel"],
            "Date": row["date"],
            "Hotel Total % LY": row.get("hotel_total_revenue_vs_ly"),
            "Hotel Total % Bu": row.get("hotel_total_revenue_vs_budget"),
            "RevPAR % LY": row.get("revpar_vs_ly"),
            "F&B Total % LY": row.get("fb_total_revenue_vs_ly"),
            "Service % LY": row.get("service_hour_vs_ly"),
            "Kitchen % LY": row.get("kitchen_hour_vs_ly"),
        })
    return pd.DataFrame(rows)

def get_status_badge(row):
    checks = [
        row.get("hotel_total_revenue_vs_budget"),
        row.get("hotel_total_revenue_vs_ly"),
        row.get("revpar_vs_ly"),
        row.get("fb_total_revenue_vs_ly"),
    ]

    negatives = sum(1 for x in checks if pd.notna(x) and x < 0)
    strong = sum(1 for x in checks if pd.notna(x) and x >= 8)

    if negatives >= 2:
        return "Критично", "#991B1B", "#FEE2E2"
    if negatives >= 1:
        return "Риск", "#92400E", "#FEF3C7"
    if strong >= 2:
        return "Рост", "#166534", "#DCFCE7"
    return "Норма", "#1D4ED8", "#DBEAFE"

def render_kpi_dashboard(latest_df):
    st.subheader("KPI-дэшборд")

    cols = st.columns(3)

    for i, (_, row) in enumerate(latest_df.iterrows()):
        status_text, status_color, status_bg = get_status_badge(row)

        card_html = f"""<div style="border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 16px; background: linear-gradient(180deg, #111827 0%, #0B1220 100%); min-height: 220px; margin-bottom: 14px;">
<div style="font-size: 20px; font-weight: 800; color: #F9FAFB; margin-bottom: 4px;">{row["hotel"]}</div>
<div style="font-size: 12px; color: #9CA3AF; margin-bottom: 10px;">Дата: {row["date"]}</div>
<div style="display: inline-block; padding: 6px 10px; border-radius: 999px; background: {status_bg}; color: {status_color}; font-size: 12px; font-weight: 700; margin-bottom: 14px;">{status_text}</div>
<div style="font-size: 13px; color: #9CA3AF;">Отель vs LY</div>
<div style="font-size: 22px; font-weight: 800; color: #F9FAFB; margin-bottom: 8px;">{fmt_pct(row.get("hotel_total_revenue_vs_ly"))}</div>
<div style="font-size: 13px; color: #9CA3AF;">Отель vs Бюджет</div>
<div style="font-size: 18px; font-weight: 700; color: #F9FAFB; margin-bottom: 8px;">{fmt_pct(row.get("hotel_total_revenue_vs_budget"))}</div>
<div style="font-size: 13px; color: #9CA3AF;">RevPAR vs LY</div>
<div style="font-size: 18px; font-weight: 700; color: #F9FAFB; margin-bottom: 8px;">{fmt_pct(row.get("revpar_vs_ly"))}</div>
<div style="font-size: 13px; color: #9CA3AF;">F&B vs LY</div>
<div style="font-size: 18px; font-weight: 700; color: #F9FAFB;">{fmt_pct(row.get("fb_total_revenue_vs_ly"))}</div>
</div>"""

        with cols[i % 3]:
            st.markdown(card_html, unsafe_allow_html=True)

# =====================
# UI
# =====================
st.markdown("""
<div class="hero-box">
    <div class="hero-title">ChefBrain</div>
    <div class="hero-subtitle">Month → Accum. vs Bu. Accum. и LY. Accum.</div>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Загрузи PDF отчёт", type=["pdf"])

if uploaded_file:
    doc_date, hotel, data = parse_pdf(uploaded_file)
    save_history(doc_date, hotel, data)

    st.subheader(f"Отель: {hotel} · Дата документа: {doc_date}")

    # KPI В ОДНУ ЛИНИЮ
    c1, c2, c3, c4, c5 = st.columns(5)

    show_metric_block(c1, "ACCOMMODATION", "RevPAR", "revpar", data["revpar"])
    show_metric_block(c2, "TOTAL F&B", "Total revenue", "fb_total_revenue", data["fb_total_revenue"])
    show_metric_block(c3, "SERVICE", "Rev. / wtrs. Hour", "service_hour", data["service_hour"])
    show_metric_block(c4, "KITCHEN", "Rev. / ktch. Hour", "kitchen_hour", data["kitchen_hour"])
    show_metric_block(c5, "HOTEL TOTAL", "Total revenue", "hotel_total_revenue", data["hotel_total_revenue"])
     
st.markdown("---")
st.subheader("Пополнить историю")

uploaded_history = st.file_uploader(
    "Загрузи CSV с историей для добавления в Google Sheets",
    type=["csv"],
    key="history_upload"
)

if uploaded_history:
    try:
        uploaded_df = pd.read_csv(uploaded_history)
        current_history = load_history()

        if current_history.empty:
            combined = uploaded_df
        else:
            combined = pd.concat([current_history, uploaded_df], ignore_index=True)

            if "date" in combined.columns and "hotel" in combined.columns:
                combined = combined.drop_duplicates(
                    subset=["date", "hotel"],
                    keep="last"
                )

        save_full_history_to_google(combined)

        st.success("История успешно пополнена и сохранена в Google Sheets.")

    except Exception as e:
        st.error(f"Ошибка при пополнении истории: {e}")
        
# =====================
# GOOGLE SHEETS HISTORY
# =====================
import gspread
from google.oauth2.service_account import Credentials

SHEET_NAME = "history"

def get_gsheet_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )

    return gspread.authorize(creds)

def get_history_sheet():
    client = get_gsheet_client()
    sheet_id = st.secrets["GOOGLE_SHEET_ID"]
    spreadsheet = client.open_by_key(sheet_id)

    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=50)

    return worksheet

def flatten_history_row(doc_date, hotel, data):
    row = {"date": doc_date, "hotel": hotel}

    for metric_key, values in data.items():
        actual, budget, ly, vs_budget, vs_ly = values
        row[f"{metric_key}_actual"] = actual
        row[f"{metric_key}_budget"] = budget
        row[f"{metric_key}_ly"] = ly
        row[f"{metric_key}_vs_budget"] = vs_budget
        row[f"{metric_key}_vs_ly"] = vs_ly

    return row

def load_history():
    try:
        worksheet = get_history_sheet()
        records = worksheet.get_all_records()

        if not records:
            return pd.DataFrame()

        return pd.DataFrame(records)

    except Exception as e:
        st.error(f"Ошибка чтения Google Sheets: {e}")
        return pd.DataFrame()

def save_history(doc_date, hotel, data):
    new_row = flatten_history_row(doc_date, hotel, data)
    new_df = pd.DataFrame([new_row])

    history = load_history()

    if history.empty:
        final_df = new_df
    else:
        for col in new_df.columns:
            if col not in history.columns:
                history[col] = pd.NA

        for col in history.columns:
            if col not in new_df.columns:
                new_df[col] = pd.NA

        history = history[~((history["date"] == doc_date) & (history["hotel"] == hotel))]
        final_df = pd.concat([history, new_df], ignore_index=True)

    save_full_history_to_google(final_df)

def save_full_history_to_google(df):
    worksheet = get_history_sheet()

    df = df.copy()
    df = df.where(pd.notna(df), "")

    worksheet.clear()
    worksheet.update([df.columns.tolist()] + df.values.tolist())
