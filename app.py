import os
import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import pdfplumber
import requests
import streamlit as st

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
HISTORY_FILE_LOCAL_BACKUP = "history_accum_v3.csv"
HOTELS = ["PALACE BRIDGE", "OLYMPIA GARDEN", "VASILIEVSKY"]

HOTEL_COLORS = {
    "PALACE BRIDGE":  "#6366F1",
    "OLYMPIA GARDEN": "#10B981",
    "VASILIEVSKY":    "#F59E0B",
}

METRIC_LABELS = {
    "hotel_total_revenue": "Hotel Total Revenue",
    "revpar":              "RevPAR",
    "fb_total_revenue":    "F&B Total Revenue",
    "service_hour":        "Service / wtrs. hr",
    "kitchen_hour":        "Kitchen / ktch. hr",
}

st.set_page_config(page_title="ChefBrain", layout="wide", initial_sidebar_state="collapsed")

# ─────────────────────────────────────────────
# GLOBAL STYLES
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

.block-container {
    padding: 1.2rem 2rem 3rem 2rem;
    max-width: 1500px;
}

/* ── HEADER ── */
.cb-header {
    background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
    border: 1px solid rgba(99,102,241,0.25);
    border-radius: 20px;
    padding: 22px 28px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 16px;
}
.cb-logo {
    font-size: 28px;
    font-weight: 800;
    background: linear-gradient(135deg, #6366F1, #8B5CF6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
}
.cb-sub {
    color: #64748B;
    font-size: 13px;
    font-weight: 500;
    margin-top: 2px;
}
.cb-badge {
    margin-left: auto;
    background: rgba(99,102,241,0.12);
    border: 1px solid rgba(99,102,241,0.3);
    color: #818CF8;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 999px;
}

/* ── SECTION TITLE ── */
.cb-section {
    font-size: 14px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #475569;
    margin: 28px 0 14px 0;
    display: flex;
    align-items: center;
    gap: 8px;
}
.cb-section::after {
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(255,255,255,0.06);
}

/* ── HOTEL CARD ── */
.hotel-card {
    background: linear-gradient(160deg, #111827 0%, #0D1520 100%);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 18px;
    padding: 20px 22px;
    min-height: 340px;
    transition: border-color 0.2s;
}
.hotel-card:hover { border-color: rgba(255,255,255,0.13); }
.hotel-name {
    font-size: 18px;
    font-weight: 800;
    color: #F8FAFC;
    margin-bottom: 2px;
    letter-spacing: -0.3px;
}
.hotel-date { font-size: 12px; color: #64748B; margin-bottom: 12px; }
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    margin-bottom: 16px;
}
.kpi-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 10px;
    padding-bottom: 10px;
    border-bottom: 1px solid rgba(255,255,255,0.05);
}
.kpi-row:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.kpi-label { font-size: 12px; color: #64748B; font-weight: 500; }
.kpi-val { font-size: 17px; font-weight: 700; color: #F1F5F9; line-height: 1; }
.kpi-delta {
    font-size: 12px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 6px;
    margin-top: 2px;
    display: inline-block;
}
.delta-pos { color: #4ADE80; background: rgba(74,222,128,0.1); }
.delta-neg { color: #F87171; background: rgba(248,113,113,0.1); }
.delta-neu { color: #FBBF24; background: rgba(251,191,36,0.1); }

/* ── KPI STRIP ── */
.kpi-strip {
    background: #0F172A;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px;
    padding: 14px 18px;
    text-align: center;
}
.kpi-strip-label { font-size: 11px; color: #64748B; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }
.kpi-strip-val { font-size: 22px; font-weight: 800; color: #F1F5F9; letter-spacing: -0.5px; }
.kpi-strip-subs { font-size: 11px; color: #475569; margin-top: 4px; }
.kpi-strip-delta { font-size: 13px; font-weight: 700; margin-top: 3px; }

/* ── ALERT BOXES ── */
.alert-box {
    border-radius: 12px;
    padding: 11px 16px;
    margin-bottom: 8px;
    font-size: 14px;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 10px;
}
.alert-bad  { background: rgba(239,68,68,0.1);  border-left: 3px solid #EF4444; color: #FCA5A5; }
.alert-warn { background: rgba(245,158,11,0.1); border-left: 3px solid #F59E0B; color: #FCD34D; }
.alert-good { background: rgba(16,185,129,0.1); border-left: 3px solid #10B981; color: #6EE7B7; }

/* ── TABLE ── */
.stDataFrame { border-radius: 12px; overflow: hidden; }

/* ── UPLOAD ZONE ── */
.upload-box {
    background: #0F172A;
    border: 1.5px dashed rgba(99,102,241,0.35);
    border-radius: 16px;
    padding: 24px;
    text-align: center;
    color: #64748B;
    font-size: 14px;
    margin-bottom: 16px;
}

/* ── METRIC COMPARISON TABLE ── */
.compare-header {
    background: #1E293B;
    border-radius: 10px 10px 0 0;
    padding: 10px 16px;
    font-size: 12px;
    font-weight: 700;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

/* Streamlit overrides */
div[data-testid="stMetric"] {
    background: #111827;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 12px 16px;
}
div[data-testid="stMetricValue"] { font-size: 20px !important; }
label[data-testid="stWidgetLabel"] { font-size: 13px !important; color: #94A3B8 !important; }
.stSelectbox > div > div { background: #1E293B !important; border-color: rgba(255,255,255,0.1) !important; }
.stFileUploader > div { background: #0F172A !important; border-color: rgba(99,102,241,0.3) !important; border-radius: 12px !important; }
h1,h2,h3 { color: #F1F5F9 !important; }
hr { border-color: rgba(255,255,255,0.06) !important; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
NUM_PATTERN = re.compile(r"\d{1,3}(?:[ \u00A0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
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
    try:
        return float(s)
    except Exception:
        return None


def extract_tokens(line: str):
    cleaned = line.replace("RUR", "").replace("%", "").replace("\xa0", " ").strip()
    return [m.group(0).strip() for m in NUM_PATTERN.finditer(cleaned)]


def safe_pct(actual, reference):
    if actual is None or reference is None or pd.isna(actual) or pd.isna(reference) or reference == 0:
        return None
    return round((actual / reference - 1.0) * 100, 1)


def fmt_val(value, is_revpar=False):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if is_revpar:
        return f"{value:,.0f}".replace(",", " ")
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:,.0f}"


def fmt_pct(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{value:+.1f}%"


def fmt_date(value):
    if value is None or pd.isna(value):
        return "—"
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return str(value)
    return dt.strftime("%d.%m.%Y")


def delta_class(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "delta-neu"
    if value > 0:
        return "delta-pos"
    if value < 0:
        return "delta-neg"
    return "delta-neu"


def get_status(row):
    checks = [
        row.get("hotel_total_revenue_vs_budget"),
        row.get("hotel_total_revenue_vs_ly"),
        row.get("revpar_vs_ly"),
        row.get("fb_total_revenue_vs_ly"),
        row.get("service_hour_vs_ly"),
        row.get("kitchen_hour_vs_ly"),
    ]
    negatives = sum(1 for x in checks if pd.notna(x) and x < 0)
    strong    = sum(1 for x in checks if pd.notna(x) and x >= 8)

    if negatives >= 4:
        return "Критично", "#EF4444", "rgba(239,68,68,0.12)", "🔴"
    if negatives >= 2:
        return "Риск",     "#F59E0B", "rgba(245,158,11,0.12)", "🟡"
    if strong >= 3:
        return "Рост",     "#10B981", "rgba(16,185,129,0.12)", "🟢"
    return     "Норма",    "#6366F1", "rgba(99,102,241,0.12)", "🔵"


# ─────────────────────────────────────────────
# PDF PARSING (unchanged logic)
# ─────────────────────────────────────────────
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
    includes  = [x.lower() for x in (includes or [])]
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
    if not line:
        return None, None, None, None, None
    tokens = extract_tokens(line)
    if len(tokens) < 8:
        return None, None, None, None, None
    actual  = parse_number(tokens[5])
    budget  = parse_number(tokens[6])
    ly      = parse_number(tokens[7])
    return actual, budget, ly, safe_pct(actual, budget), safe_pct(actual, ly)


def extract_doc_date(first_page_text: str):
    lines = split_lines(first_page_text)
    for line in lines[:8]:
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


def parse_pdf(file):
    with pdfplumber.open(file) as pdf:
        pages = []
        first_page_text = ""
        for i, page in enumerate(pdf.pages):
            txt = normalize_spaces(page.extract_text() or "")
            if i == 0:
                first_page_text = txt
            pages.append(txt)
        text = "\n".join(pages)

    doc_date = extract_doc_date(first_page_text)
    hotel    = detect_hotel(text)

    accommodation_lines = get_section_lines(text, ["accommodation"], ["breakfast"])
    total_fb_lines      = get_section_lines(text, ["total f&b", "m&e revenue"], ["total spa"])
    hotel_total_lines   = (
        get_section_lines(text, ["hotel total"], ["month", "year"])
        or get_section_lines(text, ["hotel total"])
    )

    data = {
        "revpar":               extract_month_accum_values(find_first_line(accommodation_lines, startswith="revpar")),
        "fb_total_revenue":     extract_month_accum_values(find_first_line(total_fb_lines, startswith="total revenue")),
        "service_hour":         extract_month_accum_values(find_first_line(total_fb_lines, includes=["rev.", "wtrs. hour"])),
        "kitchen_hour":         extract_month_accum_values(find_first_line(total_fb_lines, includes=["rev.", "ktch. hour"])),
        "hotel_total_revenue":  extract_month_accum_values(find_first_line(hotel_total_lines, startswith="total revenue")),
    }
    return doc_date, hotel, data


def flatten_history_row(doc_date, hotel, data):
    row = {"date": doc_date, "hotel": hotel}
    for metric_key, values in data.items():
        actual, budget, ly, vs_budget, vs_ly = values
        row[f"{metric_key}_actual"]    = actual
        row[f"{metric_key}_budget"]    = budget
        row[f"{metric_key}_ly"]        = ly
        row[f"{metric_key}_vs_budget"] = vs_budget
        row[f"{metric_key}_vs_ly"]     = vs_ly
    return row


# ─────────────────────────────────────────────
# GOOGLE SHEETS I/O
# ─────────────────────────────────────────────
def get_script_url():
    return st.secrets["GOOGLE_SCRIPT_URL"]


def get_secret_key():
    return st.secrets["CHEFBRAIN_SECRET_KEY"]


def load_history():
    try:
        response = requests.get(get_script_url(), params={"key": get_secret_key()}, timeout=20)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            st.error(f"Google Script error: {result.get('error')}")
            return pd.DataFrame()
        rows = result.get("rows", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        for col in df.columns:
            if col not in ["date", "hotel"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["date"] = df["date"].astype(str)
        return df
    except Exception as e:
        # Fallback: try local backup
        if os.path.exists(HISTORY_FILE_LOCAL_BACKUP):
            try:
                return pd.read_csv(HISTORY_FILE_LOCAL_BACKUP)
            except Exception:
                pass
        st.error(f"Ошибка чтения истории: {e}")
        return pd.DataFrame()


def save_full_history_to_google(df):
    try:
        df = df.copy()
        df = df.where(pd.notna(df), "")
        payload  = {"key": get_secret_key(), "rows": df.to_dict(orient="records")}
        response = requests.post(get_script_url(), json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            st.error(f"Google Script error: {result.get('error')}")
            return False
        return True
    except Exception as e:
        st.error(f"Ошибка записи истории: {e}")
        return False


def save_history(doc_date, hotel, data):
    new_df  = pd.DataFrame([flatten_history_row(doc_date, hotel, data)])
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
        history  = history[~((history["date"].astype(str) == str(doc_date)) & (history["hotel"] == hotel))]
        final_df = pd.concat([history, new_df], ignore_index=True)
    if save_full_history_to_google(final_df):
        st.success("✓ История сохранена в Google Sheets.")


# ─────────────────────────────────────────────
# DATA PROCESSING
# ─────────────────────────────────────────────
def latest_rows_by_hotel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["_dt"] = pd.to_datetime(df["date"], errors="coerce")
    return (
        df.dropna(subset=["_dt"])
          .sort_values("_dt")
          .groupby("hotel", as_index=False)
          .last()
          .sort_values("hotel")
          .drop(columns=["_dt"], errors="ignore")
    )


def prepare_chart_df(df: pd.DataFrame, hotel: str, metric: str) -> pd.DataFrame:
    col    = f"{metric}_actual"
    subset = df[df["hotel"] == hotel].copy()
    subset["_date"] = pd.to_datetime(subset["date"], errors="coerce")  # tz-naive
    subset = subset.dropna(subset=["_date"])
    subset[col] = pd.to_numeric(subset[col], errors="coerce")
    subset = subset.dropna(subset=[col]).sort_values("_date")
    return subset[["_date", col]].rename(columns={col: metric})


# ─────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────
def render_header(latest_date: str = ""):
    badge = f"Данные по {latest_date}" if latest_date else "ChefBrain Analytics"
    st.markdown(f"""
    <div class="cb-header">
        <div>
            <div class="cb-logo">ChefBrain</div>
            <div class="cb-sub">Hotel KPI Dashboard · Month-to-Date Accumulation</div>
        </div>
        <div class="cb-badge">{badge}</div>
    </div>
    """, unsafe_allow_html=True)


def section_title(icon: str, title: str):
    st.markdown(f'<div class="cb-section">{icon}&nbsp;&nbsp;{title}</div>', unsafe_allow_html=True)


def render_kpi_strip(col, label: str, actual, vs_budget, vs_ly, is_revpar=False):
    v  = fmt_val(actual, is_revpar)
    vb = fmt_pct(vs_budget)
    vl = fmt_pct(vs_ly)
    cb = delta_class(vs_budget)
    cl = delta_class(vs_ly)
    with col:
        st.markdown(f"""
        <div class="kpi-strip">
            <div class="kpi-strip-label">{label}</div>
            <div class="kpi-strip-val">{v}</div>
            <div class="kpi-strip-subs">vs Budget &nbsp;·&nbsp; vs LY</div>
            <div>
                <span class="kpi-delta {cb}">{vb}</span>
                &nbsp;
                <span class="kpi-delta {cl}">{vl}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)


def render_hotel_card(row: pd.Series, spark_data: pd.DataFrame | None = None):
    status_text, status_color, status_bg, status_icon = get_status(row)
    date_text = fmt_date(row.get("date"))
    hotel     = row.get("hotel", "—")
    accent    = HOTEL_COLORS.get(hotel, "#6366F1")

    metrics = [
        ("Hotel Total",   "hotel_total_revenue", False),
        ("RevPAR",        "revpar",               True),
        ("F&B Revenue",   "fb_total_revenue",     False),
        ("Service / hr",  "service_hour",         True),
        ("Kitchen / hr",  "kitchen_hour",         True),
    ]

    rows_html = ""
    for label, key, is_rp in metrics:
        actual   = row.get(f"{key}_actual")
        vs_ly    = row.get(f"{key}_vs_ly")
        vs_bu    = row.get(f"{key}_vs_budget")
        v        = fmt_val(actual, is_rp)
        vl       = fmt_pct(vs_ly)
        vb       = fmt_pct(vs_bu)
        cl       = delta_class(vs_ly)
        cb       = delta_class(vs_bu)
        rows_html += f"""
        <div class="kpi-row">
            <div>
                <div class="kpi-label">{label}</div>
                <div class="kpi-val">{v}</div>
            </div>
            <div style="text-align:right;">
                <div><span class="kpi-delta {cl}">{vl} LY</span></div>
                <div style="margin-top:3px;"><span class="kpi-delta {cb}">{vb} Bu</span></div>
            </div>
        </div>"""

    st.markdown(f"""
    <div class="hotel-card" style="border-top: 3px solid {accent};">
        <div class="hotel-name">{hotel}</div>
        <div class="hotel-date">{date_text}</div>
        <div class="status-pill" style="background:{status_bg}; color:{status_color};">
            {status_icon} {status_text}
        </div>
        {rows_html}
    </div>
    """, unsafe_allow_html=True)


def render_alerts(data: dict):
    items = []
    checks = [
        (data["hotel_total_revenue"][3], "Отель ниже бюджета месяца",              "bad"),
        (data["hotel_total_revenue"][4], "Общая выручка отеля ниже прошлого года", "bad"),
        (data["fb_total_revenue"][4],    "F&B total revenue ниже прошлого года",   "bad"),
        (data["revpar"][4],              "RevPAR ниже прошлого года",              "warn"),
    ]
    for value, text, level in checks:
        if value is not None and value < 0:
            items.append((text, level))
    svc = data["service_hour"][4]
    kch = data["kitchen_hour"][4]
    if svc is not None and kch is not None and abs(svc - kch) >= 10:
        items.append(("Сильный разрыв между сервисом и кухней", "warn"))
    if not items:
        items.append(("Критичных отклонений не обнаружено", "good"))

    for text, level in items:
        icon  = {"bad": "⛔", "warn": "⚠️", "good": "✅"}.get(level, "•")
        cls   = f"alert-{level}"
        st.markdown(f'<div class="alert-box {cls}">{icon} {text}</div>', unsafe_allow_html=True)


def render_pdf_kpi(data: dict, hotel: str, doc_date: str):
    section_title("📋", f"Отчёт: {hotel} · {fmt_date(doc_date)}")
    c1, c2, c3, c4, c5 = st.columns(5)
    cols = [c1, c2, c3, c4, c5]
    strip_data = [
        ("RevPAR",         "revpar",              True),
        ("F&B Revenue",    "fb_total_revenue",    False),
        ("Service / hr",   "service_hour",        True),
        ("Kitchen / hr",   "kitchen_hour",        True),
        ("Hotel Total",    "hotel_total_revenue", False),
    ]
    for i, (label, key, is_rp) in enumerate(strip_data):
        actual, budget, ly, vs_bu, vs_ly = data[key]
        render_kpi_strip(cols[i], label, actual, vs_bu, vs_ly, is_rp)

    st.markdown("<br>", unsafe_allow_html=True)
    section_title("🚨", "Красные зоны")
    render_alerts(data)


# ─────────────────────────────────────────────
# CHARTS (Plotly – tz-naive dates)
# ─────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter", color="#94A3B8", size=12),
    margin=dict(l=10, r=10, t=30, b=10),
    xaxis=dict(
        showgrid=False,
        tickfont=dict(size=11),
        linecolor="rgba(255,255,255,0.08)",
    ),
    yaxis=dict(
        showgrid=True,
        gridcolor="rgba(255,255,255,0.05)",
        tickfont=dict(size=11),
        zeroline=False,
    ),
    hovermode="x unified",
)


def make_line_chart(chart_df: pd.DataFrame, metric: str, hotel: str) -> go.Figure:
    color = HOTEL_COLORS.get(hotel, "#6366F1")
    label = METRIC_LABELS.get(metric, metric)
    y     = chart_df[metric].values
    x     = chart_df["_date"].values

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines",
        name=label,
        line=dict(color=color, width=2.5),
        fill="tozeroy",
        fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)",
        hovertemplate=f"<b>%{{x|%d.%m}}</b><br>{label}: %{{y:,.0f}}<extra></extra>",
    ))
    fig.update_layout(**PLOTLY_LAYOUT, height=320, title=dict(
        text=f"<b>{label}</b> · {hotel}",
        font=dict(size=13, color="#F1F5F9"),
        x=0,
    ))
    return fig


def make_multi_hotel_chart(df: pd.DataFrame, metric: str) -> go.Figure:
    label = METRIC_LABELS.get(metric, metric)
    fig   = go.Figure()
    for hotel in sorted(df["hotel"].unique()):
        cdf   = prepare_chart_df(df, hotel, metric)
        if cdf.empty:
            continue
        color = HOTEL_COLORS.get(hotel, "#94A3B8")
        fig.add_trace(go.Scatter(
            x=cdf["_date"].values,
            y=cdf[metric].values,
            mode="lines",
            name=hotel.title(),
            line=dict(color=color, width=2),
            hovertemplate=f"<b>%{{x|%d.%m}}</b><br>{hotel}: %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(**PLOTLY_LAYOUT, height=340, title=dict(
        text=f"<b>{label}</b> · сравнение отелей",
        font=dict(size=13, color="#F1F5F9"),
        x=0,
    ), legend=dict(
        orientation="h", y=-0.15, x=0,
        font=dict(size=11),
        bgcolor="rgba(0,0,0,0)",
    ))
    return fig


# ─────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────
history = load_history()

# Latest date for header badge
latest_date_str = ""
if not history.empty and "date" in history.columns:
    try:
        latest_date_str = fmt_date(pd.to_datetime(history["date"], errors="coerce").max())
    except Exception:
        pass

render_header(latest_date_str)

# ── PDF UPLOAD ─────────────────────────────
section_title("📤", "Загрузить PDF-отчёт")
uploaded_file = st.file_uploader("", type=["pdf"], label_visibility="collapsed")

if uploaded_file:
    with st.spinner("Парсим PDF..."):
        doc_date, hotel, data = parse_pdf(uploaded_file)
    save_history(doc_date, hotel, data)
    render_pdf_kpi(data, hotel, doc_date)
    history = load_history()  # refresh after save

st.markdown("---")

# ── KPI DASHBOARD ──────────────────────────
section_title("🏨", "KPI-дэшборд · последний день")

if history.empty:
    st.info("Нет данных. Загрузи PDF или историю CSV.")
else:
    latest = latest_rows_by_hotel(history)
    if latest.empty:
        st.warning("Не удалось определить последние данные.")
    else:
        cols = st.columns(len(latest))
        for i, (_, row) in enumerate(latest.iterrows()):
            with cols[i]:
                render_hotel_card(row)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── COMPARE TABLE ──
        section_title("📊", "Сравнение KPI")
        table_rows = []
        for _, row in latest.iterrows():
            table_rows.append({
                "Отель":           row["hotel"],
                "Дата":            fmt_date(row.get("date")),
                "Hotel Total LY":  fmt_pct(row.get("hotel_total_revenue_vs_ly")),
                "Hotel Total Bu":  fmt_pct(row.get("hotel_total_revenue_vs_budget")),
                "RevPAR LY":       fmt_pct(row.get("revpar_vs_ly")),
                "F&B LY":          fmt_pct(row.get("fb_total_revenue_vs_ly")),
                "Service LY":      fmt_pct(row.get("service_hour_vs_ly")),
                "Kitchen LY":      fmt_pct(row.get("kitchen_hour_vs_ly")),
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

st.markdown("---")

# ── CHARTS ─────────────────────────────────
section_title("📈", "Графики")

if history.empty:
    st.info("Нет данных для графиков.")
else:
    tab1, tab2 = st.tabs(["По отелю", "Сравнение отелей"])

    with tab1:
        col_l, col_r = st.columns([1, 3])
        with col_l:
            hotel_sel  = st.selectbox(
                "Отель",
                sorted(history["hotel"].dropna().unique().tolist()),
                key="chart_hotel"
            )
            metric_sel = st.selectbox(
                "Показатель",
                list(METRIC_LABELS.keys()),
                format_func=lambda x: METRIC_LABELS[x],
                key="chart_metric"
            )
        with col_r:
            chart_df = prepare_chart_df(history, hotel_sel, metric_sel)
            if chart_df.empty:
                st.warning("Нет данных для выбранного отеля / показателя.")
            else:
                fig = make_line_chart(chart_df, metric_sel, hotel_sel)
                st.plotly_chart(fig, use_container_width=True)

        # mini sparklines for all metrics
        st.markdown("<br>", unsafe_allow_html=True)
        spark_cols = st.columns(len(METRIC_LABELS))
        for i, (metric_key, metric_name) in enumerate(METRIC_LABELS.items()):
            cdf = prepare_chart_df(history, hotel_sel, metric_key)
            if cdf.empty:
                continue
            color = HOTEL_COLORS.get(hotel_sel, "#6366F1")
            spark = go.Figure(go.Scatter(
                x=cdf["_date"].values,
                y=cdf[metric_key].values,
                mode="lines",
                line=dict(color=color, width=1.5),
            ))
            spark.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=22, b=0),
                height=80,
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                showlegend=False,
                title=dict(
                    text=metric_name,
                    font=dict(size=10, color="#64748B"),
                    x=0,
                ),
            )
            with spark_cols[i]:
                st.plotly_chart(spark, use_container_width=True, config={"displayModeBar": False})

    with tab2:
        metric_cmp = st.selectbox(
            "Показатель для сравнения",
            list(METRIC_LABELS.keys()),
            format_func=lambda x: METRIC_LABELS[x],
            key="cmp_metric"
        )
        fig_cmp = make_multi_hotel_chart(history, metric_cmp)
        st.plotly_chart(fig_cmp, use_container_width=True)

st.markdown("---")

# ── HISTORY TABLE ──────────────────────────
section_title("🗂️", "История")

if history.empty:
    st.info("История пуста.")
else:
    hotel_hist = st.selectbox(
        "Фильтр по отелю",
        ["Все"] + sorted(history["hotel"].dropna().unique().tolist()),
        key="hist_hotel"
    )
    hist_view = history.copy() if hotel_hist == "Все" else history[history["hotel"] == hotel_hist].copy()
    hist_view["_dt"] = pd.to_datetime(hist_view["date"], errors="coerce")
    hist_view = hist_view.dropna(subset=["_dt"]).sort_values("_dt", ascending=False).drop(columns=["_dt"])

    display = pd.DataFrame({
        "Дата":          hist_view["date"].apply(fmt_date),
        "Отель":         hist_view["hotel"],
        "Hotel Total":   hist_view.get("hotel_total_revenue_actual", pd.Series()).apply(
                             lambda x: fmt_val(x) if pd.notna(x) else "—"),
        "Hotel LY %":    hist_view.get("hotel_total_revenue_vs_ly",  pd.Series()).apply(fmt_pct),
        "RevPAR":        hist_view.get("revpar_actual",              pd.Series()).apply(
                             lambda x: fmt_val(x, True) if pd.notna(x) else "—"),
        "RevPAR LY %":   hist_view.get("revpar_vs_ly",               pd.Series()).apply(fmt_pct),
        "F&B Total":     hist_view.get("fb_total_revenue_actual",    pd.Series()).apply(
                             lambda x: fmt_val(x) if pd.notna(x) else "—"),
        "F&B LY %":      hist_view.get("fb_total_revenue_vs_ly",     pd.Series()).apply(fmt_pct),
        "Service LY %":  hist_view.get("service_hour_vs_ly",         pd.Series()).apply(fmt_pct),
        "Kitchen LY %":  hist_view.get("kitchen_hour_vs_ly",         pd.Series()).apply(fmt_pct),
    })
    st.dataframe(display, use_container_width=True, hide_index=True)

    csv = history.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 Скачать историю CSV",
        data=csv,
        file_name="chefbrain_history.csv",
        mime="text/csv",
    )

st.markdown("---")

# ── HISTORY UPLOAD ─────────────────────────
section_title("📂", "Пополнить историю из CSV")

uploaded_history = st.file_uploader(
    "Загрузи CSV с историей",
    type=["csv"],
    key="history_upload",
    label_visibility="collapsed",
)

if uploaded_history:
    try:
        uploaded_df    = pd.read_csv(uploaded_history)
        current        = load_history()
        combined       = pd.concat([current, uploaded_df], ignore_index=True) if not current.empty else uploaded_df
        if "date" in combined.columns and "hotel" in combined.columns:
            combined["date"] = combined["date"].astype(str)
            combined = combined.drop_duplicates(subset=["date", "hotel"], keep="last")
        if save_full_history_to_google(combined):
            st.success(f"✓ Добавлено {len(uploaded_df)} строк. История обновлена.")
            history = load_history()
    except Exception as e:
        st.error(f"Ошибка при загрузке CSV: {e}")

# ── LOCAL BACKUP DOWNLOAD ───────────────────
if os.path.exists(HISTORY_FILE_LOCAL_BACKUP):
    with open(HISTORY_FILE_LOCAL_BACKUP, "rb") as f:
        st.download_button(
            "📥 Локальная резервная копия",
            f,
            file_name=HISTORY_FILE_LOCAL_BACKUP,
            mime="text/csv",
        )
