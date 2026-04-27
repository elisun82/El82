import os
import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
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

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.block-container { padding: 1.2rem 2rem 3rem 2rem; max-width: 1500px; }

.cb-header {
    background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
    border: 1px solid rgba(99,102,241,0.25);
    border-radius: 20px;
    padding: 22px 28px 18px 28px;
    margin-bottom: 24px;
}
.cb-logo {
    font-size: 28px; font-weight: 800;
    background: linear-gradient(135deg, #6366F1, #8B5CF6);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
}
.cb-sub  { color:#64748B; font-size:13px; font-weight:500; margin-top:2px; }
.cb-badge {
    display:inline-block; margin-top:10px;
    background:rgba(99,102,241,0.12); border:1px solid rgba(99,102,241,0.3);
    color:#818CF8; font-size:12px; font-weight:600;
    padding:4px 14px; border-radius:999px;
}
.cb-section {
    font-size:13px; font-weight:700; text-transform:uppercase;
    letter-spacing:0.08em; color:#475569;
    margin:26px 0 12px 0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    padding-bottom:8px;
}
.alert-bad  { background:rgba(239,68,68,0.1);  border-left:3px solid #EF4444; color:#FCA5A5; border-radius:10px; padding:10px 14px; margin-bottom:7px; font-size:14px; }
.alert-warn { background:rgba(245,158,11,0.1); border-left:3px solid #F59E0B; color:#FCD34D; border-radius:10px; padding:10px 14px; margin-bottom:7px; font-size:14px; }
.alert-good { background:rgba(16,185,129,0.1); border-left:3px solid #10B981; color:#6EE7B7; border-radius:10px; padding:10px 14px; margin-bottom:7px; font-size:14px; }
.status-pill {
    display:inline-block; padding:4px 13px; border-radius:999px;
    font-size:12px; font-weight:700; margin-bottom:12px;
}
.stTabs [data-baseweb="tab-list"] {
    background:#0F172A; border-radius:10px; padding:4px; gap:4px;
}
.stTabs [data-baseweb="tab"] {
    background:transparent !important; color:#64748B !important;
    border-radius:8px !important; font-size:13px !important; font-weight:600 !important;
}
.stTabs [aria-selected="true"] {
    background:#1E293B !important; color:#F1F5F9 !important;
}
.stSelectbox > div > div { background:#1E293B !important; border-color:rgba(255,255,255,0.1) !important; }
hr { border-color:rgba(255,255,255,0.06) !important; }
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


def normalize_spaces(text):
    return re.sub(r"[ \t]+", " ", text or "")


def split_lines(text):
    return [l.strip() for l in text.splitlines() if l.strip()]


def detect_hotel(text):
    upper = text.upper()
    for h in HOTELS:
        if h in upper:
            return h
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


def extract_tokens(line):
    cleaned = line.replace("RUR", "").replace("%", "").replace("\xa0", " ").strip()
    return [m.group(0).strip() for m in NUM_PATTERN.finditer(cleaned)]


def safe_pct(actual, reference):
    if actual is None or reference is None or pd.isna(actual) or pd.isna(reference) or reference == 0:
        return None
    return round((actual / reference - 1.0) * 100, 1)


def fmt_val(value, is_unit=False):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if is_unit:
        return f"{int(value):,}".replace(",", " ")
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
    if value is None:
        return "—"
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return str(value)
    return dt.strftime("%d.%m.%Y")


def _color(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "#475569"
    return "#4ADE80" if v > 0 else ("#F87171" if v < 0 else "#FBBF24")


def colored_delta(value, suffix=""):
    c  = _color(value)
    bg = ("rgba(74,222,128,0.1)" if (value is not None and not (isinstance(value, float) and pd.isna(value)) and value > 0)
          else "rgba(248,113,113,0.1)" if (value is not None and not (isinstance(value, float) and pd.isna(value)) and value < 0)
          else "rgba(251,191,36,0.1)")
    return (f'<span style="color:{c};background:{bg};padding:2px 7px;'
            f'border-radius:6px;font-size:12px;font-weight:600;">'
            f'{fmt_pct(value)}{suffix}</span>')


def get_status(row):
    checks = [
        row.get("hotel_total_revenue_vs_budget"),
        row.get("hotel_total_revenue_vs_ly"),
        row.get("revpar_vs_ly"),
        row.get("fb_total_revenue_vs_ly"),
        row.get("service_hour_vs_ly"),
        row.get("kitchen_hour_vs_ly"),
    ]
    neg    = sum(1 for x in checks if pd.notna(x) and x < 0)
    strong = sum(1 for x in checks if pd.notna(x) and x >= 8)
    if neg >= 4:
        return "🔴 Критично", "#EF4444", "rgba(239,68,68,0.15)"
    if neg >= 2:
        return "🟡 Риск",     "#F59E0B", "rgba(245,158,11,0.15)"
    if strong >= 3:
        return "🟢 Рост",     "#10B981", "rgba(16,185,129,0.15)"
    return     "🔵 Норма",    "#6366F1", "rgba(99,102,241,0.15)"


# ─────────────────────────────────────────────
# PDF PARSING
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
        if all(k.lower() in lines[j].lower() for k in end_keywords):
            return lines[start_idx:j]
    return lines[start_idx:]


def find_first_line(lines, includes=None, startswith=None):
    includes   = [x.lower() for x in (includes or [])]
    startswith = startswith.lower() if startswith else None
    for line in lines:
        low = line.lower()
        if startswith and not low.startswith(startswith):
            continue
        if includes and not all(x in low for x in includes):
            continue
        return line
    return None


def extract_month_accum_values(line):
    if not line:
        return None, None, None, None, None
    tokens = extract_tokens(line)
    if len(tokens) < 8:
        return None, None, None, None, None
    actual = parse_number(tokens[5])
    budget = parse_number(tokens[6])
    ly     = parse_number(tokens[7])
    return actual, budget, ly, safe_pct(actual, budget), safe_pct(actual, ly)


def extract_doc_date(first_page_text):
    for line in split_lines(first_page_text)[:8]:
        for pat in DATE_PATTERNS:
            m = pat.search(line)
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
        pages, first_page_text = [], ""
        for i, page in enumerate(pdf.pages):
            txt = normalize_spaces(page.extract_text() or "")
            if i == 0:
                first_page_text = txt
            pages.append(txt)
        text = "\n".join(pages)

    doc_date = extract_doc_date(first_page_text)
    hotel    = detect_hotel(text)
    acc_l    = get_section_lines(text, ["accommodation"], ["breakfast"])
    fb_l     = get_section_lines(text, ["total f&b", "m&e revenue"], ["total spa"])
    ht_l     = (get_section_lines(text, ["hotel total"], ["month", "year"])
                or get_section_lines(text, ["hotel total"]))

    return doc_date, hotel, {
        "revpar":              extract_month_accum_values(find_first_line(acc_l, startswith="revpar")),
        "fb_total_revenue":    extract_month_accum_values(find_first_line(fb_l,  startswith="total revenue")),
        "service_hour":        extract_month_accum_values(find_first_line(fb_l,  includes=["rev.", "wtrs. hour"])),
        "kitchen_hour":        extract_month_accum_values(find_first_line(fb_l,  includes=["rev.", "ktch. hour"])),
        "hotel_total_revenue": extract_month_accum_values(find_first_line(ht_l,  startswith="total revenue")),
    }


def flatten_history_row(doc_date, hotel, data):
    row = {"date": doc_date, "hotel": hotel}
    for key, (actual, budget, ly, vs_bu, vs_ly) in data.items():
        row[f"{key}_actual"]    = actual
        row[f"{key}_budget"]    = budget
        row[f"{key}_ly"]        = ly
        row[f"{key}_vs_budget"] = vs_bu
        row[f"{key}_vs_ly"]     = vs_ly
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
        r = requests.get(get_script_url(), params={"key": get_secret_key()}, timeout=20)
        r.raise_for_status()
        result = r.json()
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
        if os.path.exists(HISTORY_FILE_LOCAL_BACKUP):
            try:
                return pd.read_csv(HISTORY_FILE_LOCAL_BACKUP)
            except Exception:
                pass
        st.error(f"Ошибка загрузки истории: {e}")
        return pd.DataFrame()


def save_full_history_to_google(df):
    try:
        df      = df.copy().where(pd.notna(df), "")
        payload = {"key": get_secret_key(), "rows": df.to_dict(orient="records")}
        r       = requests.post(get_script_url(), json=payload, timeout=30)
        r.raise_for_status()
        result  = r.json()
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
        all_cols = set(new_df.columns) | set(history.columns)
        for col in all_cols:
            if col not in history.columns:
                history[col] = pd.NA
            if col not in new_df.columns:
                new_df[col] = pd.NA
        history  = history[~((history["date"].astype(str) == str(doc_date)) & (history["hotel"] == hotel))]
        final_df = pd.concat([history, new_df], ignore_index=True)
    if save_full_history_to_google(final_df):
        st.success("✓ История сохранена в Google Sheets.")


# ─────────────────────────────────────────────
# DATA UTILS
# ─────────────────────────────────────────────
def latest_rows_by_hotel(df):
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


def prepare_chart_df(df, hotel, metric):
    col    = f"{metric}_actual"
    subset = df[df["hotel"] == hotel].copy()
    subset["_date"] = pd.to_datetime(subset["date"], errors="coerce")
    subset[col]     = pd.to_numeric(subset[col], errors="coerce")
    subset = subset.dropna(subset=["_date", col]).sort_values("_date")
    return subset[["_date", col]].rename(columns={col: metric})


# ─────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────
def render_header(latest_date=""):
    badge = f"Данные по {latest_date}" if latest_date else "Analytics"
    st.markdown(f"""
    <div class="cb-header">
        <div class="cb-logo">ChefBrain</div>
        <div class="cb-sub">Hotel KPI Dashboard · Month-to-Date Accumulation</div>
        <div class="cb-badge">{badge}</div>
    </div>
    """, unsafe_allow_html=True)


def section_title(icon, title):
    st.markdown(f'<div class="cb-section">{icon}&nbsp; {title}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# HOTEL CARD  — native widgets, no big HTML blocks
# ─────────────────────────────────────────────
def render_hotel_card(row):
    hotel     = row.get("hotel", "—")
    date_text = fmt_date(row.get("date"))
    accent    = HOTEL_COLORS.get(hotel, "#6366F1")
    s_txt, s_color, s_bg = get_status(row)

    # thin color bar
    st.markdown(
        f'<div style="height:4px;background:{accent};'
        f'border-radius:4px 4px 0 0;margin-bottom:0;"></div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
            f'<p style="font-size:17px;font-weight:800;color:#F8FAFC;'
            f'letter-spacing:-0.3px;margin:0 0 2px 0;">{hotel}</p>'
            f'<p style="font-size:12px;color:#64748B;margin:0 0 8px 0;">{date_text}</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="status-pill" style="background:{s_bg};color:{s_color};">'
            f'{s_txt}</div>',
            unsafe_allow_html=True,
        )

        metrics_cfg = [
            ("Hotel Total",  "hotel_total_revenue", False),
            ("RevPAR",       "revpar",               True),
            ("F&B Revenue",  "fb_total_revenue",     False),
            ("Service / hr", "service_hour",         True),
            ("Kitchen / hr", "kitchen_hour",         True),
        ]

        for label, key, is_unit in metrics_cfg:
            actual = row.get(f"{key}_actual")
            vs_ly  = row.get(f"{key}_vs_ly")
            vs_bu  = row.get(f"{key}_vs_budget")
            ca, cb_ = st.columns([3, 2])
            with ca:
                st.markdown(
                    f'<p style="font-size:11px;color:#64748B;font-weight:600;'
                    f'text-transform:uppercase;letter-spacing:0.05em;margin:0;">{label}</p>'
                    f'<p style="font-size:18px;font-weight:700;color:#F1F5F9;'
                    f'line-height:1.1;margin:0 0 6px 0;">{fmt_val(actual, is_unit)}</p>',
                    unsafe_allow_html=True,
                )
            with cb_:
                st.markdown(
                    f'<p style="text-align:right;margin:4px 0 0 0;line-height:1.6;">'
                    f'<span style="color:{_color(vs_ly)};font-size:12px;font-weight:600;">'
                    f'{fmt_pct(vs_ly)} LY</span><br>'
                    f'<span style="color:{_color(vs_bu)};font-size:12px;font-weight:600;">'
                    f'{fmt_pct(vs_bu)} Bu</span></p>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                '<hr style="margin:0 0 4px 0;border:none;'
                'border-top:1px solid rgba(255,255,255,0.05);">',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────
# PDF KPI STRIP
# ─────────────────────────────────────────────
def render_pdf_kpi(data, hotel, doc_date):
    section_title("📋", f"Отчёт: {hotel} · {fmt_date(doc_date)}")
    strips = [
        ("RevPAR",       "revpar",              True),
        ("F&B Revenue",  "fb_total_revenue",    False),
        ("Service / hr", "service_hour",        True),
        ("Kitchen / hr", "kitchen_hour",        True),
        ("Hotel Total",  "hotel_total_revenue", False),
    ]
    cols = st.columns(5)
    for i, (label, key, is_unit) in enumerate(strips):
        actual, _, _, vs_bu, vs_ly = data[key]
        with cols[i]:
            with st.container(border=True):
                st.markdown(
                    f'<p style="font-size:11px;color:#64748B;font-weight:600;'
                    f'text-transform:uppercase;letter-spacing:0.05em;margin:0 0 4px 0;">'
                    f'{label}</p>'
                    f'<p style="font-size:22px;font-weight:800;color:#F1F5F9;'
                    f'letter-spacing:-0.5px;margin:0 0 6px 0;">{fmt_val(actual, is_unit)}</p>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'vs Bu: {colored_delta(vs_bu)}&nbsp;&nbsp;vs LY: {colored_delta(vs_ly)}',
                    unsafe_allow_html=True,
                )

    st.markdown("<br>", unsafe_allow_html=True)
    section_title("🚨", "Красные зоны")
    alerts = []
    for value, text, level in [
        (data["hotel_total_revenue"][3], "Отель ниже бюджета месяца",              "bad"),
        (data["hotel_total_revenue"][4], "Общая выручка отеля ниже прошлого года", "bad"),
        (data["fb_total_revenue"][4],    "F&B total revenue ниже прошлого года",   "bad"),
        (data["revpar"][4],              "RevPAR ниже прошлого года",              "warn"),
    ]:
        if value is not None and value < 0:
            alerts.append((text, level))
    svc, kch = data["service_hour"][4], data["kitchen_hour"][4]
    if svc is not None and kch is not None and abs(svc - kch) >= 10:
        alerts.append(("Сильный разрыв между сервисом и кухней", "warn"))
    if not alerts:
        alerts.append(("Критичных отклонений не обнаружено", "good"))
    for text, level in alerts:
        icon = {"bad": "⛔", "warn": "⚠️", "good": "✅"}.get(level, "•")
        st.markdown(f'<div class="alert-{level}">{icon} {text}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────
_PL = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter", color="#94A3B8", size=12),
    margin=dict(l=10, r=10, t=36, b=10),
    xaxis=dict(showgrid=False, tickfont=dict(size=11), linecolor="rgba(255,255,255,0.08)"),
    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)", tickfont=dict(size=11), zeroline=False),
    hovermode="x unified",
)


def make_line_chart(chart_df, metric, hotel):
    color = HOTEL_COLORS.get(hotel, "#6366F1")
    label = METRIC_LABELS.get(metric, metric)
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fig = go.Figure(go.Scatter(
        x=chart_df["_date"].values, y=chart_df[metric].values,
        mode="lines", name=label,
        line=dict(color=color, width=2.5),
        fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.08)",
        hovertemplate=f"<b>%{{x|%d.%m}}</b><br>{label}: %{{y:,.0f}}<extra></extra>",
    ))
    fig.update_layout(**_PL, height=320,
                      title=dict(text=f"<b>{label}</b> · {hotel}",
                                 font=dict(size=13, color="#F1F5F9"), x=0))
    return fig


def make_multi_chart(df, metric):
    label = METRIC_LABELS.get(metric, metric)
    fig   = go.Figure()
    for hotel in sorted(df["hotel"].dropna().unique()):
        cdf = prepare_chart_df(df, hotel, metric)
        if cdf.empty:
            continue
        color = HOTEL_COLORS.get(hotel, "#94A3B8")
        fig.add_trace(go.Scatter(
            x=cdf["_date"].values, y=cdf[metric].values,
            mode="lines", name=hotel.title(),
            line=dict(color=color, width=2),
            hovertemplate=f"<b>%{{x|%d.%m}}</b><br>{hotel}: %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(**_PL, height=340,
                      title=dict(text=f"<b>{label}</b> · сравнение отелей",
                                 font=dict(size=13, color="#F1F5F9"), x=0),
                      legend=dict(orientation="h", y=-0.15, x=0,
                                  font=dict(size=11), bgcolor="rgba(0,0,0,0)"))
    return fig


def make_spark(chart_df, metric, hotel):
    color = HOTEL_COLORS.get(hotel, "#6366F1")
    fig   = go.Figure(go.Scatter(
        x=chart_df["_date"].values, y=chart_df[metric].values,
        mode="lines", line=dict(color=color, width=1.5),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=20, b=0), height=70,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False,
        title=dict(text=METRIC_LABELS.get(metric, metric),
                   font=dict(size=10, color="#64748B"), x=0),
    )
    return fig


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
history = load_history()

latest_date_str = ""
if not history.empty and "date" in history.columns:
    try:
        latest_date_str = fmt_date(pd.to_datetime(history["date"], errors="coerce").max())
    except Exception:
        pass

render_header(latest_date_str)

# ── PDF UPLOAD ──────────────────────────────────────
section_title("📤", "Загрузить PDF-отчёт")
uploaded_file = st.file_uploader("Загрузи PDF отчёт", type=["pdf"])

if uploaded_file:
    with st.spinner("Парсим PDF..."):
        doc_date, hotel, data = parse_pdf(uploaded_file)
    save_history(doc_date, hotel, data)
    render_pdf_kpi(data, hotel, doc_date)
    history = load_history()

st.markdown("---")

# ── KPI DASHBOARD ───────────────────────────────────
section_title("🏨", "KPI-дэшборд · последний день")

if history.empty:
    st.info("Нет данных. Загрузи PDF или историю CSV.")
else:
    latest = latest_rows_by_hotel(history)
    if latest.empty:
        st.warning("Не удалось определить последние данные.")
    else:
        card_cols = st.columns(len(latest))
        for i, (_, row) in enumerate(latest.iterrows()):
            with card_cols[i]:
                render_hotel_card(row)

        st.markdown("<br>", unsafe_allow_html=True)
        section_title("📊", "Сравнение KPI")
        table_rows = []
        for _, row in latest.iterrows():
            table_rows.append({
                "Отель":          row["hotel"],
                "Дата":           fmt_date(row.get("date")),
                "Hotel Total LY": fmt_pct(row.get("hotel_total_revenue_vs_ly")),
                "Hotel Total Bu": fmt_pct(row.get("hotel_total_revenue_vs_budget")),
                "RevPAR LY":      fmt_pct(row.get("revpar_vs_ly")),
                "F&B LY":         fmt_pct(row.get("fb_total_revenue_vs_ly")),
                "Service LY":     fmt_pct(row.get("service_hour_vs_ly")),
                "Kitchen LY":     fmt_pct(row.get("kitchen_hour_vs_ly")),
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

st.markdown("---")

# ── CHARTS ──────────────────────────────────────────
section_title("📈", "Графики")

if not history.empty:
    tab1, tab2 = st.tabs(["По отелю", "Сравнение отелей"])

    with tab1:
        ctrl_col, chart_col = st.columns([1, 4])
        with ctrl_col:
            hotel_sel  = st.selectbox("Отель",
                                       sorted(history["hotel"].dropna().unique().tolist()),
                                       key="chart_hotel")
            metric_sel = st.selectbox("Показатель",
                                       list(METRIC_LABELS.keys()),
                                       format_func=lambda x: METRIC_LABELS[x],
                                       key="chart_metric")
        with chart_col:
            cdf = prepare_chart_df(history, hotel_sel, metric_sel)
            if cdf.empty:
                st.warning("Нет данных.")
            else:
                st.plotly_chart(make_line_chart(cdf, metric_sel, hotel_sel),
                                use_container_width=True)

        spark_cols = st.columns(len(METRIC_LABELS))
        for i, mk in enumerate(METRIC_LABELS):
            sdf = prepare_chart_df(history, hotel_sel, mk)
            if not sdf.empty:
                with spark_cols[i]:
                    st.plotly_chart(make_spark(sdf, mk, hotel_sel),
                                    use_container_width=True,
                                    config={"displayModeBar": False})

    with tab2:
        metric_cmp = st.selectbox("Показатель",
                                   list(METRIC_LABELS.keys()),
                                   format_func=lambda x: METRIC_LABELS[x],
                                   key="cmp_metric")
        st.plotly_chart(make_multi_chart(history, metric_cmp), use_container_width=True)

st.markdown("---")

# ── HISTORY TABLE ────────────────────────────────────
section_title("🗂️", "История")

if not history.empty:
    hotel_hist = st.selectbox(
        "Фильтр по отелю",
        ["Все"] + sorted(history["hotel"].dropna().unique().tolist()),
        key="hist_hotel",
    )
    hv = history.copy() if hotel_hist == "Все" else history[history["hotel"] == hotel_hist].copy()
    hv["_dt"] = pd.to_datetime(hv["date"], errors="coerce")
    hv = hv.dropna(subset=["_dt"]).sort_values("_dt", ascending=False).drop(columns=["_dt"])

    def _fv(x, unit=False):
        return fmt_val(x, unit) if pd.notna(x) else "—"

    display = pd.DataFrame({
        "Дата":        hv["date"].apply(fmt_date),
        "Отель":       hv["hotel"],
        "Hotel Total": hv.get("hotel_total_revenue_actual", pd.Series(dtype=float)).apply(_fv),
        "HTot LY%":    hv.get("hotel_total_revenue_vs_ly",  pd.Series(dtype=float)).apply(fmt_pct),
        "RevPAR":      hv.get("revpar_actual",              pd.Series(dtype=float)).apply(lambda x: _fv(x, True)),
        "RevPAR LY%":  hv.get("revpar_vs_ly",               pd.Series(dtype=float)).apply(fmt_pct),
        "F&B Total":   hv.get("fb_total_revenue_actual",    pd.Series(dtype=float)).apply(_fv),
        "F&B LY%":     hv.get("fb_total_revenue_vs_ly",     pd.Series(dtype=float)).apply(fmt_pct),
        "Svc LY%":     hv.get("service_hour_vs_ly",         pd.Series(dtype=float)).apply(fmt_pct),
        "Ktch LY%":    hv.get("kitchen_hour_vs_ly",         pd.Series(dtype=float)).apply(fmt_pct),
    })
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.download_button("📥 Скачать историю CSV",
                       history.to_csv(index=False).encode("utf-8-sig"),
                       file_name="chefbrain_history.csv", mime="text/csv")

st.markdown("---")

# ── HISTORY UPLOAD ────────────────────────────────────
section_title("📂", "Пополнить историю из CSV")
uploaded_history = st.file_uploader("Загрузи CSV с историей",
                                     type=["csv"], key="history_upload")
if uploaded_history:
    try:
        udf      = pd.read_csv(uploaded_history)
        current  = load_history()
        combined = pd.concat([current, udf], ignore_index=True) if not current.empty else udf
        if "date" in combined.columns and "hotel" in combined.columns:
            combined["date"] = combined["date"].astype(str)
            combined = combined.drop_duplicates(subset=["date", "hotel"], keep="last")
        if save_full_history_to_google(combined):
            st.success(f"✓ Добавлено {len(udf)} строк.")
            history = load_history()
    except Exception as e:
        st.error(f"Ошибка при загрузке CSV: {e}")

if os.path.exists(HISTORY_FILE_LOCAL_BACKUP):
    with open(HISTORY_FILE_LOCAL_BACKUP, "rb") as f:
        st.download_button("📥 Локальная резервная копия", f,
                           file_name=HISTORY_FILE_LOCAL_BACKUP, mime="text/csv")
