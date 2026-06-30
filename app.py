"""
app.py — ΑΒ Σκύρος Dashboard
ΕΚΔΟΣΗ: v5.0 GLASSMORPHISM — ημιδιάφανες κάρτες με blur
(Αν βλέπεις αυτή τη γραμμή στο GitHub, ανέβηκε η ΣΩΣΤΗ έκδοση)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import io, re
from datetime import datetime, date, timedelta
from imap_tools import MailBox, AND
from pdf2image import convert_from_bytes
import pytesseract

from gsheets_helper import (
    load_sales as _raw_load_sales, merge_sales,
    load_invoices as _raw_load_invoices, merge_invoices,
    load_timologiseis, merge_timologiseis, update_timologiseis_check_number, update_timologiseis_expenses,
    update_sales_value,
    check_sales_quality, check_timologiseis_quality, check_invoices_quality, delete_sheet_row,
)

# ── PATCH ΓΙΑ ΔΙΟΡΘΩΣΗ ΔΕΔΟΜΕΝΩΝ (Ασφαλής Μετατροπή & Αφαίρεση Διπλών) ─────────
def _clean_numeric(x):
    if pd.isna(x): return 0.0
    if isinstance(x, (int, float)): return float(x)
    s = str(x).replace("€", "").replace(" ", "").strip()
    # Αν υπάρχει και τελεία και κόμμα, π.χ. "1.500,50"
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    # Αν υπάρχει μόνο κόμμα, π.χ. "1500,50"
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return 0.0

def load_sales():
    df = _raw_load_sales()
    if df is not None and not df.empty:
        df = df.copy()
        if "net_sales" in df.columns:
            df["net_sales"] = df["net_sales"].apply(_clean_numeric)
        if "avg_basket" in df.columns:
            df["avg_basket"] = df["avg_basket"].apply(_clean_numeric)
        # Αφαίρεση διπλοεγγραφών ανά ημερομηνία για καθαρή εικόνα
        if "date" in df.columns:
            df = df.drop_duplicates(subset=["date"])
    return df

if hasattr(_raw_load_sales, "clear"):
    load_sales.clear = _raw_load_sales.clear

def load_invoices():
    df = _raw_load_invoices()
    if df is not None and not df.empty:
        df = df.copy()
        # Invoices: το Google Sheet αποθηκεύει x100 (σε λεπτά) — ίδια λογική με πωλήσεις
        if "value" in df.columns:
            df["value"] = df["value"].apply(_clean_numeric)
        if "date" in df.columns and "type" in df.columns and "value" in df.columns:
            df = df.drop_duplicates(subset=["date", "type", "value"])
    return df

if hasattr(_raw_load_invoices, "clear"):
    load_invoices.clear = _raw_load_invoices.clear
# ──────────────────────────────────────────────────────────────────────────────

# ── CONFIG ────────────────────────────────────────────────────────────────────
INVOICES_EMAIL_USER   = "abf.skyros@gmail.com"
INVOICES_EMAIL_SENDER = "Notifications@WeDoConnect.com"
SALES_EMAIL_USER      = "ftoulisgm@gmail.com"
SALES_EMAIL_SENDER    = "abf.skyros@gmail.com"
# Τιμολογήσεις (επιταγές) — έρχονται στο ftoulisgm από noreply@ab.gr
TIMOL_EMAIL_USER      = "ftoulisgm@gmail.com"
TIMOL_EMAIL_SENDER    = "noreply@ab.gr"
TIMOL_SUBJECT_KW      = "ΤΙΜΟΛΟΓΗΣΕΙΣ"
SALES_SUBJECT_KW      = "ΑΒ ΣΚΥΡΟΣ"
BATCH_SIZE            = 25
DEEP_SCAN_YEARS       = 2

MONTHS_GR = [
    "Ιανουάριος","Φεβρουάριος","Μάρτιος","Απρίλιος",
    "Μάιος","Ιούνιος","Ιούλιος","Αύγουστος",
    "Σεπτέμβριος","Οκτώβριος","Νοέμβριος","Δεκέμβριος"
]
# Συντομογραφίες ημερών (Δευτέρα=0 ... Κυριακή=6) — 3 πρώτα γράμματα
DAYS_GR = ["Δευ", "Τρι", "Τετ", "Πεμ", "Παρ", "Σαβ", "Κυρ"]

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ΑΒ Σκύρος",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

/* ═══════════════ AB ΒΑΣΙΛΟΠΟΥΛΟΣ BRAND THEME ═══════════════ */
:root {
    --bg:          #f4f8fc;
    --bg-elev:     #ffffff;
    --bg-card:     #ffffff;
    --bg-hover:    #eaf2fb;
    --border:      #d8e6f4;
    --border-soft: #e6eff7;
    --text:        #0a2540;
    --text-mut:    #5a7290;
    --text-dim:    #93a7c0;
    --brand:       #0072CE;
    --brand-2:     #005BA6;
    --brand-3:     #2b96e8;
    --brand-glow:  rgba(0,114,206,.28);
    --sky:         #2b96e8;
    --red:         #E2231A;
    --red-soft:    rgba(226,35,26,.1);
    --green:       #1aa260;
    --amber:       #e8920c;
    --violet:      #6d5bd0;
    --shadow:      0 10px 30px rgba(10,37,64,.08);
}

*, *::before, *::after { box-sizing: border-box; }
html, body, [class*="css"] {
    font-family: 'Inter', system-ui, sans-serif !important;
    background: var(--bg) !important;
    color: var(--text) !important;
}
.stApp { background: linear-gradient(135deg, #eef1f8 0%, #e6edf7 40%, #eaf0fa 100%) !important; }
#MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }
/* Φέρε το περιεχόμενο ψηλά (αφαίρεσε το προεπιλεγμένο κενό του Streamlit) */
[data-testid="stAppViewContainer"] > .main { padding-top: 0 !important; }
[data-testid="stMain"] { padding-top: 0 !important; }
[data-testid="stMainBlockContainer"] { padding-top: 1rem !important; }
.stApp [data-testid="stVerticalBlock"] { gap: .75rem !important; }
.block-container { padding: 0.5rem 2.5rem 6rem !important; max-width: 1280px !important; }
.stApp [data-testid="stDecoration"] { display: none !important; }
.kpi-value, .stat-num, [data-testid="stDataFrame"] td { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }

/* ═══════════════ SIDEBAR ═══════════════ */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ffffff 0%, #f0f7fd 100%) !important;
    border-right: 1px solid var(--border-soft) !important;
}
section[data-testid="stSidebar"] * { color: var(--text) !important; }
section[data-testid="stSidebar"] .stRadio > div { gap: .15rem !important; }
section[data-testid="stSidebar"] .stRadio label {
    padding: .65rem .9rem !important; border-radius: 11px !important;
    transition: background .15s, color .15s !important;
    font-size: .9rem !important; font-weight: 600 !important; cursor: pointer !important; width: 100% !important;
    color: var(--text-mut) !important;
}
section[data-testid="stSidebar"] .stRadio label:hover { background: var(--bg-hover) !important; color: var(--brand) !important; }

/* collapse button — εμφανές πλωτό κουμπί επαναφοράς */
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] {
    background: var(--brand) !important; border-radius: 0 12px 12px 0 !important;
    width: 36px !important; height: 64px !important;
    box-shadow: 3px 0 18px var(--brand-glow) !important;
    position: fixed !important; top: 1rem !important; left: 0 !important;
    z-index: 999990 !important; display: flex !important;
    align-items: center !important; justify-content: center !important;
    opacity: 1 !important; visibility: visible !important;
}
[data-testid="collapsedControl"] svg, [data-testid="stSidebarCollapsedControl"] svg {
    fill: #fff !important; color: #fff !important; width: 22px !important; height: 22px !important;
}
[data-testid="collapsedControl"]:hover, [data-testid="stSidebarCollapsedControl"]:hover {
    width: 44px !important; background: var(--brand-2) !important;
}
[data-testid="stSidebarCollapseButton"] button { background: var(--bg-hover) !important; border-radius: 8px !important; }
[data-testid="stSidebarCollapseButton"] svg { fill: var(--brand) !important; }

/* ═══════════════ PAGE HEADER (στυλ Folks) ═══════════════ */
.page-header {
    display: flex; align-items: center; gap: 1.1rem;
    margin: 0 0 1.25rem 0; padding-bottom: 0;
}
.page-header .icon {
    width: 54px; height: 54px; border-radius: 16px; display: flex; align-items: center; justify-content: center;
    font-size: 1.6rem; color: #fff;
    background: linear-gradient(135deg, var(--brand), var(--brand-2));
    box-shadow: 0 8px 22px var(--brand-glow); flex-shrink: 0;
}
.page-header h1 {
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.8rem; font-weight: 800;
    letter-spacing: -.025em; color: var(--text); margin: 0; line-height: 1.05;
}
.page-header .sub { font-size: .85rem; color: var(--text-mut); margin-top: .3rem; font-weight: 500; }

/* ═══════════════ SECTION LABEL ═══════════════ */
.section-label {
    font-size: .68rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
    color: var(--text-dim); margin: 1.75rem 0 .85rem; display: flex; align-items: center; gap: .65rem;
}
.section-label::after { content: ''; flex: 1; height: 1px; background: var(--border-soft); }

/* ═══════════════ KPI CARDS ═══════════════ */
.kpi-grid { display: grid; gap: 1.35rem; margin-bottom: 1.5rem; }
.kpi-2 { grid-template-columns: repeat(2, 1fr); }
.kpi-3 { grid-template-columns: repeat(3, 1fr); }
.kpi-4 { grid-template-columns: repeat(4, 1fr); }

.kpi-grid a { text-decoration: none !important; }
.kpi-card {
    position: relative; overflow: hidden;
    background: rgba(255,255,255,.55);
    backdrop-filter: blur(20px) saturate(160%);
    -webkit-backdrop-filter: blur(20px) saturate(160%);
    border: 1px solid rgba(255,255,255,.7); border-radius: 22px; padding: 1.65rem 1.75rem;
    transition: transform .18s cubic-bezier(.2,.8,.2,1), border-color .18s, box-shadow .18s;
    box-shadow: 0 8px 28px rgba(10,37,64,.08), inset 0 1px 0 rgba(255,255,255,.6);
}
.kpi-card:hover {
    transform: translateY(-4px);
    background: rgba(255,255,255,.7);
    box-shadow: 0 18px 42px rgba(10,37,64,.14), inset 0 1px 0 rgba(255,255,255,.7);
}
.kpi-card::after {
    content: ''; position: absolute; inset: 0 0 auto 0; height: 4px;
    background: linear-gradient(90deg, var(--accent, var(--brand)), transparent 85%);
}
.kpi-card .glow {
    position: absolute; top: -40%; right: -20%; width: 160px; height: 160px; border-radius: 50%;
    background: var(--accent, var(--brand)); filter: blur(55px); opacity: .12; pointer-events: none;
}
.kpi-label {
    font-size: .68rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    color: var(--text-mut); margin-bottom: .85rem; display: flex; align-items: center; gap: .4rem;
}
.kpi-value {
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.9rem; font-weight: 800;
    letter-spacing: -.025em; color: var(--text); line-height: 1;
}
.kpi-value.green  { color: var(--brand); }
.kpi-value.blue   { color: var(--sky); }
.kpi-value.red    { color: var(--red); }
.kpi-value.amber  { color: var(--amber); }
.kpi-value.violet { color: var(--violet); }
.kpi-sub { font-size: .76rem; color: var(--text-mut); margin-top: .6rem; }
.kpi-trend { font-size: .76rem; font-weight: 600; margin-top: .6rem; display: flex; align-items: center; gap: .3rem; }
.kpi-trend.up   { color: var(--green); }
.kpi-trend.down { color: var(--red); }
.kpi-trend.flat { color: var(--text-dim); }

/* ═══════════════ GRADIENT HERO CARDS (στυλ Flowlu) ═══════════════ */
.hero-card {
    position: relative; overflow: hidden; border-radius: 20px; padding: 1.6rem 1.75rem;
    color: #fff; min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;
    box-shadow: 0 12px 30px rgba(10,37,64,.18); transition: transform .2s, box-shadow .2s;
}
.hero-card:hover { transform: translateY(-4px); box-shadow: 0 20px 44px rgba(10,37,64,.26); }
.hero-card.grad-blue   { background: linear-gradient(135deg, #2b96e8 0%, #0072CE 100%); }
.hero-card.grad-violet { background: linear-gradient(135deg, #8b5cf6 0%, #6d5bd0 100%); }
.hero-card.grad-navy   { background: linear-gradient(135deg, #0a2540 0%, #1a4a7a 100%); }
.hero-card.grad-teal   { background: linear-gradient(135deg, #14b8a6 0%, #0d9488 100%); }
.hero-card::after {
    content: ''; position: absolute; top: -30%; right: -10%; width: 180px; height: 180px;
    border-radius: 50%; background: rgba(255,255,255,.12); pointer-events: none;
}
.hero-card::before {
    content: ''; position: absolute; bottom: -40%; left: 10%; width: 140px; height: 140px;
    border-radius: 50%; background: rgba(255,255,255,.07); pointer-events: none;
}
.hero-label {
    font-size: .72rem; font-weight: 600; letter-spacing: .04em; opacity: .9;
    display: flex; align-items: center; gap: .5rem; position: relative; z-index: 1;
}
.hero-icon {
    position: absolute; top: 1.4rem; right: 1.5rem; width: 38px; height: 38px; border-radius: 11px;
    background: rgba(255,255,255,.18); display: flex; align-items: center; justify-content: center;
    font-size: 1.15rem; z-index: 1;
}
.hero-value {
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 2.1rem; font-weight: 800;
    letter-spacing: -.03em; line-height: 1; position: relative; z-index: 1; font-variant-numeric: tabular-nums;
}
.hero-sub { font-size: .76rem; opacity: .88; position: relative; z-index: 1; font-weight: 500; }
.hero-sub b { font-weight: 700; }

/* ═══════════════ CHECK PAYMENT CARD ═══════════════ */
.check-card {
    position: relative; overflow: hidden;
    background: linear-gradient(135deg, rgba(0,114,206,.08), rgba(43,150,232,.04));
    border: 1px solid rgba(0,114,206,.3); border-radius: 18px; padding: 1.5rem 1.7rem; margin-top: 1.5rem;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 1rem;
}
.check-card .glow { position: absolute; top: -50%; left: 20%; width: 200px; height: 200px; border-radius: 50%; background: var(--brand); filter: blur(70px); opacity: .12; }

/* ═══════════════ DATE BADGE ═══════════════ */
.date-badge {
    display: inline-flex; align-items: center; gap: .5rem;
    background: rgba(255,255,255,.55); backdrop-filter: blur(14px) saturate(150%);
    -webkit-backdrop-filter: blur(14px) saturate(150%);
    border: 1px solid rgba(255,255,255,.7);
    border-radius: 12px; padding: .55rem 1rem; font-size: .8rem; font-weight: 600; color: var(--brand); margin-bottom: 1.35rem;
    box-shadow: 0 4px 14px rgba(10,37,64,.05);
}

/* ═══════════════ ALERTS ═══════════════ */
.alert { border-radius: 12px; padding: .9rem 1.15rem; font-size: .78rem; font-weight: 500; margin: .75rem 0; display: flex; gap: .55rem; align-items: flex-start; }
.alert-success { background: rgba(26,162,96,.1); border: 1px solid rgba(26,162,96,.4); color: var(--green); }
.alert-warn    { background: rgba(232,146,12,.1); border: 1px solid rgba(232,146,12,.4); color: var(--amber); }
.alert-error   { background: var(--red-soft); border: 1px solid rgba(226,35,26,.4); color: var(--red); }
.alert-info    { background: rgba(0,114,206,.08); border: 1px solid rgba(0,114,206,.3); color: var(--brand); }

/* ═══════════════ TABLE ═══════════════ */
[data-testid="stDataFrame"] { border: 1px solid rgba(255,255,255,.7) !important; border-radius: 18px !important; overflow: hidden !important; box-shadow: 0 8px 26px rgba(10,37,64,.08) !important; backdrop-filter: blur(16px) !important; -webkit-backdrop-filter: blur(16px) !important; }
[data-testid="stDataFrame"] th { background: rgba(238,246,253,.85) !important; color: var(--text-mut) !important; font-size: .66rem !important; letter-spacing: .08em !important; text-transform: uppercase !important; font-weight: 700 !important; padding-top: .6rem !important; padding-bottom: .6rem !important; }
[data-testid="stDataFrame"] td { background: rgba(255,255,255,.5) !important; color: var(--text) !important; font-size: .84rem !important; border-color: rgba(216,230,244,.6) !important; }

/* ═══════════════ BUTTONS ═══════════════ */
.stButton > button {
    border-radius: 10px !important; font-family: 'Inter', sans-serif !important; font-size: .8rem !important;
    font-weight: 600 !important; padding: .6rem 1.1rem !important; border: 1px solid var(--border) !important;
    background: #ffffff !important; color: var(--text) !important; transition: all .15s !important;
}
.stButton > button:hover { background: var(--bg-hover) !important; border-color: var(--brand) !important; transform: translateY(-1px); }
.btn-primary > button { background: linear-gradient(135deg, var(--brand), var(--brand-2)) !important; border: none !important; color: #fff !important; box-shadow: 0 4px 14px var(--brand-glow) !important; }
.btn-primary > button:hover { box-shadow: 0 6px 20px var(--brand-glow) !important; }

/* ═══════════════ TABS ═══════════════ */
[data-baseweb="tab-list"] { background: transparent !important; border-bottom: 1.5px solid var(--border) !important; gap: .5rem !important; margin-bottom: 1.5rem !important; }
[data-baseweb="tab"] { background: transparent !important; border: none !important; color: var(--text-mut) !important; font-size: .88rem !important; font-weight: 600 !important; padding: .85rem 1.25rem !important; transition: color .15s !important; }
[data-baseweb="tab"]:hover { color: var(--text) !important; }
[aria-selected="true"][data-baseweb="tab"] { color: var(--brand) !important; border-bottom: 2.5px solid var(--brand) !important; }

/* ═══════════════ INPUTS ═══════════════ */
.stDateInput > div > div > input, .stSelectbox > div > div, .stTextInput > div > div > input {
    background: #ffffff !important; border: 1px solid var(--border) !important; border-radius: 10px !important;
    color: var(--text) !important; font-family: 'Inter', sans-serif !important; font-size: .85rem !important;
}
label { color: var(--text-mut) !important; font-size: .76rem !important; font-weight: 600 !important; }

/* ═══════════════ EXPANDER (manual update) ═══════════════ */
[data-testid="stExpander"] { border: 1px solid rgba(255,255,255,.7) !important; border-radius: 16px !important; background: rgba(255,255,255,.5) !important; backdrop-filter: blur(16px) saturate(150%) !important; -webkit-backdrop-filter: blur(16px) saturate(150%) !important; box-shadow: 0 6px 20px rgba(10,37,64,.06) !important; }
[data-testid="stExpander"] summary { color: var(--text-mut) !important; font-size: .82rem !important; font-weight: 600 !important; }

/* ═══════════════ PROGRESS CARD ═══════════════ */
.prog-card { background: #ffffff; border: 1px solid var(--border); border-radius: 14px; padding: 1.2rem 1.4rem; margin: .75rem 0; }
.prog-title { font-size: .88rem; font-weight: 700; color: var(--text); margin-bottom: .4rem; }
.prog-sub { font-size: .72rem; color: var(--text-mut); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

hr { border-color: var(--border-soft) !important; margin: 1.5rem 0 !important; }

/* ═══════════════ YEAR ROW (timologiseis) ═══════════════ */
.year-row {
    display: flex; align-items: center; justify-content: space-between;
    background: rgba(255,255,255,.55); backdrop-filter: blur(16px) saturate(150%);
    -webkit-backdrop-filter: blur(16px) saturate(150%);
    border: 1px solid rgba(255,255,255,.7); border-radius: 16px; padding: 1.15rem 1.5rem; margin-bottom: .75rem;
    transition: all .15s; box-shadow: 0 6px 20px rgba(10,37,64,.06), inset 0 1px 0 rgba(255,255,255,.6);
}
.year-row:hover { background: rgba(255,255,255,.72); transform: translateX(3px); box-shadow: 0 10px 26px rgba(10,37,64,.1); }
.year-row .yr { font-family: 'Plus Jakarta Sans'; font-size: 1.15rem; font-weight: 800; color: var(--text); }
.year-row .amt { font-family: 'Plus Jakarta Sans'; font-size: 1.3rem; font-weight: 800; color: var(--brand); font-variant-numeric: tabular-nums; }
.year-row .cnt { font-size: .74rem; color: var(--text-mut); }

/* ═══════════════ MOBILE BOTTOM NAV ═══════════════ */
.mobile-only { display: none; }
@media (max-width: 820px) {
    section[data-testid="stSidebar"] {
        position: fixed !important; left: -9999px !important; width: 1px !important;
        min-width: 1px !important; opacity: 0 !important; pointer-events: none !important;
    }
    [data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    .block-container { padding: 1rem 1rem 6.5rem !important; }
    .page-header h1 { font-size: 1.3rem; }
    .page-header .icon { width: 42px; height: 42px; font-size: 1.25rem; }
    .kpi-3, .kpi-4 { grid-template-columns: 1fr !important; }
    .kpi-2 { grid-template-columns: 1fr !important; }
    .kpi-value { font-size: 1.55rem; }
    .mobile-only { display: block; }
}
</style>
""", unsafe_allow_html=True)



# ══════════════════════════════════════════════════════════════════════════════
# INVOICE PARSER & EMAIL FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def parse_invoice_xlsx(file_content, filename):
    """Parser βασισμένος στη λογική του my_app που δουλεύει σωστά."""
    records = []
    try:
        if filename.lower().endswith(('.xlsx', '.xls')):
            df_raw = pd.read_excel(io.BytesIO(file_content), header=None)
        else:
            try:
                df_raw = pd.read_csv(io.BytesIO(file_content), header=None, sep=None, engine='python')
            except:
                df_raw = pd.read_csv(io.BytesIO(file_content), header=None, encoding='cp1253', sep=None, engine='python')

        # Βρες header row (έως γραμμή 40)
        header_idx = -1
        for i in range(min(40, len(df_raw))):
            row_str = " ".join([str(x).upper() for x in df_raw.iloc[i].values if pd.notna(x)])
            if "ΤΥΠΟΣ" in row_str and "ΗΜΕΡΟΜΗΝΙΑ" in row_str:
                header_idx = i
                break
        if header_idx == -1:
            return records

        df = df_raw.iloc[header_idx + 1:].copy()
        headers = [str(h).strip().upper() for h in df_raw.iloc[header_idx].values]
        df.columns = headers
        df = df.loc[:, df.columns.notna()]
        df = df.loc[:, ~df.columns.str.contains('NAN|UNNAMED', case=False, na=False)]
        df = df.reset_index(drop=True)

        # Βρες τις στήλες — ίδια λογική με my_app
        col_date  = next((c for c in df.columns if 'ΗΜΕΡΟΜΗΝΙΑ' in c), None)
        col_value = next((c for c in df.columns if 'ΑΞΙΑ' in c or 'ΣΥΝΟΛΟ' in c), None)
        col_type  = next((c for c in df.columns if 'ΤΥΠΟΣ' in c), None)

        if not (col_date and col_value and col_type):
            return records

        temp = df[[col_date, col_type, col_value]].copy()
        temp.columns = ['date', 'type', 'value']
        temp['date'] = pd.to_datetime(temp['date'], errors='coerce')
        # Καθαρισμός αξίας — ακριβώς όπως my_app
        if temp['value'].dtype == object:
            temp['value'] = (temp['value'].astype(str)
                             .str.replace('€', '', regex=False)
                             .str.replace(',', '.', regex=False)
                             .str.strip())
        temp['value'] = pd.to_numeric(temp['value'], errors='coerce').fillna(0)
        temp['type'] = temp['type'].astype(str).str.strip()
        temp = temp.dropna(subset=['date'])
        temp = temp[temp['type'].str.lower() != 'nan']

        for _, row in temp.iterrows():
            records.append({"date": row['date'], "type": row['type'], "value": float(row['value'])})
    except:
        pass
    return records

def fetch_and_store_invoices(pw, limit=30):
    new_recs, errors = [], []
    try:
        with MailBox("imap.gmail.com").login(INVOICES_EMAIL_USER, pw) as mb:
            msgs = list(mb.fetch(AND(from_=INVOICES_EMAIL_SENDER), limit=limit, reverse=True))
            for msg in msgs:
                for att in msg.attachments:
                    fname = att.filename or ""
                    if fname.lower().endswith((".xlsx", ".xls", ".csv")):
                        new_recs.extend(parse_invoice_xlsx(att.payload, fname))
    except Exception as e:
        errors.append(str(e))
    saved = merge_invoices(new_recs)
    return saved, errors, len(new_recs)

def parse_timologiseis_xlsx(file_content):
    """Διαβάζει το Excel τιμολογήσεων και βρίσκει την τελευταία γραμμή
    με 'ΠΛΗΡΩΜΗ ΜΕ ΕΠΙΤΑΓΗ {ημερομηνία}' + το συνολικό ποσό."""
    import re as _re
    try:
        df_raw = pd.read_excel(io.BytesIO(file_content), header=None)
    except Exception:
        return None
    # Ψάξε όλες τις γραμμές για το κείμενο πληρωμής με επιταγή
    for i in range(len(df_raw) - 1, -1, -1):
        row = df_raw.iloc[i]
        row_text = " ".join([str(x) for x in row.values if pd.notna(x)])
        m = _re.search(r"ΠΛΗΡΩΜΗ\s+ΜΕ\s+ΕΠΙΤΑΓΗ\s+(\d{1,2})[./](\d{1,2})[./](\d{4})", row_text, _re.IGNORECASE)
        if m:
            try:
                check_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except Exception:
                continue
            # Το ποσό είναι στη στήλη 8 ("Ποσό Χρέωσης/Πίστωσης")
            amount = None
            if len(row.values) > 8:
                v8 = row.values[8]
                if isinstance(v8, (int, float)) and pd.notna(v8):
                    amount = float(v8)
                else:
                    xs = str(v8).replace("€", "").replace(" ", "").strip()
                    if "," in xs and "." in xs:
                        xs = xs.replace(".", "").replace(",", ".")
                    elif "," in xs:
                        xs = xs.replace(",", ".")
                    try:
                        amount = float(xs)
                    except Exception:
                        amount = None
            # Fallback: πρώτη δεκαδική τιμή (όχι ακέραιοι κωδικοί)
            if amount is None:
                for x in row.values:
                    if isinstance(x, float) and pd.notna(x) and x != int(x):
                        amount = float(x)
                        break
            if amount is not None:
                period_m = _re.search(r"ΠΕΡΙΟΔΟΥ?\s*([\d.]+\s*-\s*[\d.]+)", row_text)
                period = period_m.group(1).strip() if period_m else ""
                return {"check_date": check_date, "period": period, "amount": round(abs(amount), 2)}
    return None

def _is_timol_email(msg_or_hdr):
    """Ελέγχει αν ένα email είναι τιμολόγηση — χαλαρό φιλτράρισμα.
    Αρκεί το θέμα να περιέχει ΤΙΜΟΛΟΓΗΣΕΙΣ ή ο αποστολέας ab.gr."""
    subj = (getattr(msg_or_hdr, "subject", "") or "").upper()
    sender = (getattr(msg_or_hdr, "from_", "") or "").lower()
    if TIMOL_SUBJECT_KW in subj:
        return True
    if "ab.gr" in sender and ("ΤΙΜΟΛΟΓ" in subj or "ΒΑΣΙΛΟΠΟΥΛ" in subj):
        return True
    return False

def fetch_and_store_timologiseis(pw, limit=400):
    """Διαβάζει emails τιμολογήσεων και αποθηκεύει στο Google Sheets."""
    new_recs, errors = [], []
    _scanned = 0
    _matched = 0
    try:
        with MailBox("imap.gmail.com").login(TIMOL_EMAIL_USER, pw) as mb:
            msgs = list(mb.fetch(limit=limit, reverse=True, mark_seen=False))
            _scanned = len(msgs)
            for msg in msgs:
                if not _is_timol_email(msg):
                    continue
                _matched += 1
                for att in msg.attachments:
                    fname = att.filename or ""
                    if fname.lower().endswith((".xlsx", ".xls")):
                        rec = parse_timologiseis_xlsx(att.payload)
                        if rec:
                            new_recs.append(rec)
    except Exception as e:
        errors.append(str(e))
    saved = merge_timologiseis(new_recs)
    if not errors and _matched == 0:
        errors.append(f"Σαρώθηκαν {_scanned} emails αλλά κανένα δεν ταιριάζει με 'ΤΙΜΟΛΟΓΗΣΕΙΣ'. Ελέγξτε το θέμα/αποστολέα.")
    return saved, errors, len(new_recs)

def deep_scan_timologiseis(pw, limit=3000):
    """Βαθιά σάρωση ΟΛΩΝ των emails τιμολογήσεων (2 χρόνια)."""
    from imap_tools import AND
    cutoff = date.today() - timedelta(days=365 * DEEP_SCAN_YEARS)
    s = {"phase": "connect", "total": 0, "done": 0, "saved": 0, "cur": "", "err": None, "ok": False}
    yield s.copy()
    try:
        with MailBox("imap.gmail.com").login(TIMOL_EMAIL_USER, pw) as mb:
            s["phase"] = "listing"; yield s.copy()
            all_hdrs = list(mb.fetch(limit=limit, reverse=True, mark_seen=False, headers_only=True))
            hdrs = [h for h in all_hdrs
                    if h.date and h.date.date() >= cutoff
                    and _is_timol_email(h)]
            s["total"] = len(hdrs); s["phase"] = "fetch"; yield s.copy()
            if not hdrs:
                s["ok"] = True; yield s.copy(); return
            batch = []
            for i, h in enumerate(hdrs):
                s["done"] = i + 1
                s["cur"] = (h.subject or "")[:60]
                yield s.copy()
                try:
                    full = list(mb.fetch(AND(uid=str(h.uid)), mark_seen=False))
                    if not full: continue
                    for att in full[0].attachments:
                        fname = att.filename or ""
                        if fname.lower().endswith((".xlsx", ".xls")):
                            rec = parse_timologiseis_xlsx(att.payload)
                            if rec:
                                batch.append(rec)
                    if len(batch) >= BATCH_SIZE:
                        s["saved"] += merge_timologiseis(batch)
                        batch = []
                        yield s.copy()
                except: continue
            if batch:
                s["saved"] += merge_timologiseis(batch)
            s["ok"] = True; yield s.copy()
    except Exception as e:
        s["err"] = str(e); s["ok"] = True; yield s.copy()

def deep_scan_invoices(pw, limit=2000):
    """Βαθιά σάρωση ΟΛΩΝ των emails παραστατικών (2 χρόνια)."""
    from imap_tools import AND
    cutoff = date.today() - timedelta(days=365 * DEEP_SCAN_YEARS)
    s = {"phase": "connect", "total": 0, "done": 0, "saved": 0, "cur": "", "err": None, "ok": False}
    yield s.copy()
    try:
        with MailBox("imap.gmail.com").login(INVOICES_EMAIL_USER, pw) as mb:
            s["phase"] = "listing"; yield s.copy()
            all_hdrs = list(mb.fetch(
                AND(from_=INVOICES_EMAIL_SENDER),
                limit=limit, reverse=True, mark_seen=False, headers_only=True
            ))
            hdrs = [h for h in all_hdrs if h.date and h.date.date() >= cutoff]
            s["total"] = len(hdrs); s["phase"] = "fetch"; yield s.copy()
            if not hdrs:
                s["ok"] = True; yield s.copy(); return
            batch = []
            for i, h in enumerate(hdrs):
                s["done"] = i + 1
                s["cur"] = (h.subject or "")[:60]
                yield s.copy()
                try:
                    full = list(mb.fetch(AND(uid=str(h.uid)), mark_seen=False))
                    if not full: continue
                    for att in full[0].attachments:
                        fname = att.filename or ""
                        if fname.lower().endswith((".xlsx", ".xls", ".csv")):
                            batch.extend(parse_invoice_xlsx(att.payload, fname))
                    if len(batch) >= BATCH_SIZE:
                        s["saved"] += merge_invoices(batch)
                        batch = []
                        yield s.copy()
                except: continue
            if batch:
                s["saved"] += merge_invoices(batch)
            s["ok"] = True; yield s.copy()
    except Exception as e:
        s["err"] = str(e); s["ok"] = True; yield s.copy()

def extract_sales_from_pdf(pdf_bytes):
    r = {"date": None, "net_sales": None, "customers": None, "avg_basket": None}
    try:
        images = convert_from_bytes(pdf_bytes, dpi=180, first_page=1, last_page=1)
        if not images:
            return r
        t = pytesseract.image_to_string(
            images[0].rotate(90, expand=True),
            lang="ell+eng", config="--psm 6 --oem 3"
        )
        m = re.search(r"Run\s+[Oo0]n\s*[:\s]+(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t, re.IGNORECASE)
        if m:
            try: r["date"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except: pass
        if not r["date"]:
            m = re.search(r"\bFor\s+(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t, re.IGNORECASE)
            if m:
                try:
                    d_for = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    r["date"] = d_for - timedelta(days=1)
                except: pass
        m = re.search(r"Net[Dd]ay[Ss]al[Dd]is\s+([\d.,]+)", t, re.IGNORECASE)
        if not m:
            m = re.search(r"Ne[t7][Dd]ay\S+\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                v = float(raw)
                if 500 < v < 500000: r["net_sales"] = round(v, 2)
            except: pass
        m = re.search(r"Num[O0]fCus\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            try:
                v = int(re.sub(r"[.,]", "", m.group(1).split()[0]))
                if 10 < v < 5000: r["customers"] = v
            except: pass
        m = re.search(r"Avg[Ss]al[Cc]us\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            try:
                raw = m.group(1).replace(".", "").replace(",", ".")
                v = float(raw)
                if 1 < v < 1000: r["avg_basket"] = round(v, 2)
            except: pass
        if r["net_sales"] and r["customers"] and not r["avg_basket"]:
            ab = r["net_sales"] / r["customers"]
            if 1 < ab < 1000: r["avg_basket"] = round(ab, 2)
    except: pass
    return r

def _valid_sales_subj(subj):
    s = (subj or "").upper()
    return SALES_SUBJECT_KW in s or "SKYROS" in s

def fetch_sales_emails(pw, since=None, want_records=4, email_scan_limit=30):
    recs, errs, n = [], [], 0
    try:
        with MailBox("imap.gmail.com").login(SALES_EMAIL_USER, pw) as mb:
            for msg in mb.fetch(limit=email_scan_limit, reverse=True, mark_seen=False):
                if len(recs) >= want_records: break
                sender = (msg.from_ or "").lower()
                if SALES_EMAIL_SENDER.lower() not in sender: continue
                if not _valid_sales_subj(msg.subject): continue
                msg_dt = msg.date
                if msg_dt and hasattr(msg_dt, "tzinfo") and msg_dt.tzinfo:
                    msg_dt = msg_dt.replace(tzinfo=None)
                msg_d = msg_dt.date() if msg_dt else None
                if since and msg_d and msg_d < since: continue
                pdfs = [a for a in msg.attachments if a.filename and a.filename.lower().endswith(".pdf")]
                if not pdfs: continue
                n += 1
                for pdf in pdfs:
                    rec = extract_sales_from_pdf(pdf.payload)
                    if rec["date"] and rec["net_sales"] is not None:
                        recs.append(rec); break
    except Exception as e:
        errs.append(str(e))
    return recs, errs, n

def deep_scan_sales(pw):
    cutoff = date.today() - timedelta(days=365 * DEEP_SCAN_YEARS)
    s = {"phase":"connect","total":0,"done":0,"saved":0,"cur":"","err":None,"ok":False}
    yield s.copy()
    try:
        with MailBox("imap.gmail.com").login(SALES_EMAIL_USER, pw) as mb:
            s["phase"] = "listing"; yield s.copy()
            all_hdrs = list(mb.fetch(limit=3000, reverse=True, mark_seen=False, headers_only=True))
            hdrs = [h for h in all_hdrs
                    if h.date and h.date.date() >= cutoff
                    and SALES_EMAIL_SENDER.lower() in (h.from_ or "").lower()
                    and _valid_sales_subj(h.subject)]
            s["total"] = len(hdrs); s["phase"] = "ocr"; yield s.copy()
            if not hdrs:
                s["ok"] = True; yield s.copy(); return
            batch = []
            for i, h in enumerate(hdrs):
                s["done"] = i + 1; s["cur"] = (h.subject or "")[:60]; yield s.copy()
                try:
                    full = list(mb.fetch(AND(uid=str(h.uid)), mark_seen=False))
                    if not full: continue
                    pdfs = [a for a in full[0].attachments if a.filename and a.filename.lower().endswith(".pdf")]
                    if not pdfs: continue
                    for pdf in pdfs:
                        rec = extract_sales_from_pdf(pdf.payload)
                        if rec["date"] and rec["net_sales"] is not None:
                            batch.append(rec); break
                    if len(batch) >= BATCH_SIZE:
                        s["saved"] += merge_sales(batch); batch = []; yield s.copy()
                except: continue
            if batch:
                s["saved"] += merge_sales(batch)
            s["ok"] = True; yield s.copy()
    except Exception as e:
        s["err"] = str(e); s["ok"] = True; yield s.copy()

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _secret(key, fallback=""):
    try:
        v = st.secrets.get(key, "")
        return v if v else fallback
    except:
        return fallback

INV_PW   = _secret("EMAIL_PASS")
SALES_PW = _secret("SALES_EMAIL_PASS") or _secret("EMAIL_PASS")

def fmt(v, suffix=" €"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        r = round(float(v), 2)
        s = f"{r:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return s + suffix
    except:
        return "—"

def fmt_int(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        return f"{int(v):,}".replace(",", ".")
    except:
        return "—"

def trend_html(current, previous, unit="€", lower_is_better=False):
    if previous is None or previous == 0 or pd.isna(previous):
        return '<span class="kpi-trend flat">— χωρίς σύγκριση</span>'
    try:
        diff = current - previous
        pct  = diff / previous * 100
        arrow = "↑" if diff > 0 else "↓"
        cls   = ("up" if diff > 0 else "down") if not lower_is_better else ("down" if diff > 0 else "up")
        return f'<span class="kpi-trend {cls}">{arrow} {abs(pct):.1f}% vs προηγούμενη</span>'
    except:
        return '<span class="kpi-trend flat">—</span>'

def get_week_range(d):
    if isinstance(d, datetime): d = d.date()
    s = d - timedelta(days=d.weekday())
    return s, s + timedelta(days=6)

def prev_week_range(sw):
    return sw - timedelta(days=7), sw - timedelta(days=1)

# ── PLOTLY THEME ──────────────────────────────────────────────────────────────
def _title_color():
    return "#0a2540"

def _plot_layout():
    grid, line, txt = "#d8e6f4", "#d8e6f4", "#5a7290"
    return dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color=txt, size=11),
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis=dict(gridcolor=grid, linecolor=line, tickcolor=line),
        yaxis=dict(gridcolor=grid, linecolor=line, tickcolor=line),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=line),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=line, font_color="#0a2540"),
    )

# Backward compat
PLOT_LAYOUT = _plot_layout()

def sales_line_chart(df, title="Πωλήσεις"):
    df = df.sort_values("date")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["net_sales"],
        mode="lines+markers",
        name="Πωλήσεις",
        line=dict(color="#3fb950", width=2.5),
        marker=dict(size=6, color="#3fb950"),
        fill="tozeroy",
        fillcolor="rgba(63,185,80,0.07)",
        hovertemplate="<b>%{x}</b><br>%{y:,.2f}€<extra></extra>",
    ))
    if "customers" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["customers"],
            mode="lines",
            name="Πελάτες",
            line=dict(color="#58a6ff", width=1.8, dash="dot"),
            yaxis="y2",
            hovertemplate="<b>%{x}</b><br>%{y} πελάτες<extra></extra>",
        ))
        fig.update_layout(
            yaxis2=dict(overlaying="y", side="right", gridcolor="rgba(0,0,0,0)",
                        tickcolor="#30363d", tickfont=dict(color="#58a6ff", size=10)),
        )
    fig.update_layout(**_plot_layout(), title=dict(text=title, font=dict(size=13, color=_title_color())), height=280)
    return fig

def basket_bar_chart(df):
    df = df.sort_values("date")
    fig = go.Figure(go.Bar(
        x=df["date"], y=df["avg_basket"],
        marker_color="#bc8cff",
        hovertemplate="<b>%{x}</b><br>%{y:,.2f}€<extra></extra>",
    ))
    fig.update_layout(**_plot_layout(), title=dict(text="ΜΟ Καλαθιού", font=dict(size=13, color=_title_color())), height=220)
    return fig

def monthly_bar_chart(df_monthly):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_monthly["label"], y=df_monthly["net_sales"],
        marker_color="#238636",
        hovertemplate="<b>%{x}</b><br>%{y:,.2f}€<extra></extra>",
        name="Πωλήσεις",
    ))
    fig.update_layout(**_plot_layout(), title=dict(text="Μηνιαίες Πωλήσεις", font=dict(size=13, color=_title_color())), height=260)
    return fig

def invoices_donut(inv_total, crd_total):
    fig = go.Figure(go.Pie(
        labels=["Τιμολόγια", "Πιστωτικά"],
        values=[inv_total, crd_total],
        hole=.65,
        marker_colors=["#238636", "#da3633"],
        textinfo="percent",
        hovertemplate="<b>%{label}</b><br>%{value:,.2f}€<extra></extra>",
    ))
    fig.update_layout(
        **_plot_layout(),
        showlegend=True,
        height=220,
        annotations=[dict(text=f"{fmt(inv_total-crd_total)}", x=.5, y=.5,
                          font=dict(size=14, color=_title_color(), family="Inter"), showarrow=False)],
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION (desktop) + light theme
# ══════════════════════════════════════════════════════════════════════════════
PAGES = ["Επισκόπηση", "Πωλήσεις", "Παραστατικά", "Τιμολογήσεις", "Μήνας"]
PAGE_ICONS = {"Επισκόπηση": "🏠", "Πωλήσεις": "📈", "Παραστατικά": "🧾", "Τιμολογήσεις": "💳", "Μήνας": "📅"}

# Διάβασε τρέχουσα σελίδα από το URL (?page=...) — δουλεύει σε desktop & mobile
_qp_page = st.query_params.get("page", "Επισκόπηση")
if _qp_page not in PAGES:
    _qp_page = "Επισκόπηση"
if "active_page" not in st.session_state:
    st.session_state["active_page"] = _qp_page
if _qp_page != st.session_state["active_page"]:
    st.session_state["active_page"] = _qp_page
page = st.session_state["active_page"]

# Κρύβουμε εντελώς την προεπιλεγμένη sidebar του Streamlit — φτιάχνουμε δικό μας icon rail
st.markdown("""
<style>
section[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
.block-container { padding-left: 6.5rem !important; }
@media (max-width: 820px) { .block-container { padding-left: 1rem !important; } }
</style>
""", unsafe_allow_html=True)

# ── CUSTOM SIDEBAR (σκούρα μπάρα με εικονίδιο + κείμενο — στυλ Flowlu) ──
import urllib.parse as _u_rail
_rail_items = ""
for p in PAGES:
    _active = p == page
    _href = "?page=" + _u_rail.quote(p)
    _cls = "rail-item active" if _active else "rail-item"
    _rail_items += (
        f'<a href="{_href}" target="_self" class="{_cls}">'
        f'<span class="rail-ico">{PAGE_ICONS[p]}</span>'
        f'<span class="rail-lbl">{p}</span>'
        f'</a>'
    )

_rail_html = (
    '<div class="icon-rail">'
    '<div class="rail-logo">🏪</div>'
    '<div class="rail-nav">' + _rail_items + '</div>'
    '</div>'
)
st.markdown(_rail_html, unsafe_allow_html=True)

st.markdown("""
<style>
.icon-rail {
    position: fixed; top: 0; left: 0; bottom: 0; width: 5rem; z-index: 999990;
    background: linear-gradient(180deg, #0a2540 0%, #071b30 100%);
    border-right: 1px solid rgba(255,255,255,.06);
    display: flex; flex-direction: column; align-items: center;
    padding: 1.1rem 0; gap: .15rem;
    box-shadow: 2px 0 24px rgba(7,27,48,.18);
}
.rail-logo {
    width: 46px; height: 46px; border-radius: 14px; margin-bottom: 1.4rem;
    display: flex; align-items: center; justify-content: center; font-size: 1.45rem;
    background: linear-gradient(135deg, #2b96e8, #0072CE);
    box-shadow: 0 6px 18px rgba(43,150,232,.5); flex-shrink: 0;
}
.rail-nav { display: flex; flex-direction: column; gap: .2rem; width: 100%; align-items: center; }
.rail-item {
    position: relative; width: 4rem; padding: .65rem 0; border-radius: 12px;
    display: flex; flex-direction: column; align-items: center; gap: .25rem;
    text-decoration: none !important; transition: all .18s cubic-bezier(.2,.8,.2,1);
}
.rail-item .rail-ico { font-size: 1.35rem; line-height: 1; filter: grayscale(.4) opacity(.75); transition: filter .15s; }
.rail-item .rail-lbl { font-size: .58rem; font-weight: 600; color: #7a93b3; letter-spacing: .01em; transition: color .15s; text-align: center; }
.rail-item:hover { background: rgba(255,255,255,.06); }
.rail-item:hover .rail-ico { filter: none; }
.rail-item:hover .rail-lbl { color: #cfe0f2; }
.rail-item.active { background: linear-gradient(135deg, rgba(43,150,232,.25), rgba(0,114,206,.15)); }
.rail-item.active .rail-ico { filter: none; }
.rail-item.active .rail-lbl { color: #ffffff; }
.rail-item.active::before {
    content: ''; position: absolute; left: -0; top: 50%; transform: translateY(-50%);
    width: 3px; height: 26px; border-radius: 0 3px 3px 0; background: #2b96e8;
    left: calc(-1.5rem + 2px);
}
@media (max-width: 820px) { .icon-rail { display: none !important; } }
</style>
""", unsafe_allow_html=True)

today = date.today()

# ══════════════════════════════════════════════════════════════════════════════
# AUTO-UPDATE — Παραστατικά & Τιμολογήσεις ενημερώνονται αυτόματα ΚΑΘΕ 2 ΩΡΕΣ
# μέσω GitHub Actions (data_sync.yml), ΟΧΙ σε κάθε login (για ταχύτητα).
# Οι Πωλήσεις ενημερώνονται κάθε μισή ώρα 21:30→02:00 μέσω GitHub Actions (sales_sync.yml).
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# ΕΡΓΑΛΕΙΑ ΔΙΑΧΕΙΡΙΣΗΣ ΠΩΛΗΣΕΩΝ (διόρθωση / προσθήκη / έλεγχος)
# ══════════════════════════════════════════════════════════════════════════════
def _render_sales_fix(df_s):
    st.caption("Αν εντοπίσεις λάθος τιμή (π.χ. από εσφαλμένη ανάγνωση OCR), επίλεξε την ημερομηνία "
               "και διόρθωσε τα πεδία.")
    if df_s.empty:
        st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν εγγραφές προς διόρθωση.</div>', unsafe_allow_html=True)
        return
    _dates_list = sorted([d.date() if hasattr(d, "date") else d for d in df_s["date"]], reverse=True)
    _fix_date = st.selectbox("Ημερομηνία", _dates_list,
                             format_func=lambda d: f"{DAYS_GR[d.weekday()]} {d.strftime('%d/%m/%Y')}", key="fix_sales_date")
    _cur_row = df_s[df_s["date"].apply(lambda x: (x.date() if hasattr(x, "date") else x)) == _fix_date]
    _cur_net = float(_cur_row["net_sales"].iloc[0]) if not _cur_row.empty else 0.0
    _cur_cus = int(_cur_row["customers"].iloc[0]) if (not _cur_row.empty and pd.notna(_cur_row["customers"].iloc[0])) else 0
    _cur_bsk = float(_cur_row["avg_basket"].iloc[0]) if (not _cur_row.empty and pd.notna(_cur_row["avg_basket"].iloc[0])) else 0.0
    st.markdown(f'<div class="alert alert-info">Τρέχουσες → Πωλήσεις: <b>{fmt(_cur_net)}</b> · Πελάτες: <b>{_cur_cus}</b> · Καλάθι: <b>{fmt(_cur_bsk)}</b></div>', unsafe_allow_html=True)
    _f1, _f2, _f3 = st.columns(3)
    with _f1:
        _new_net = st.number_input("Καθαρές Πωλήσεις (€)", min_value=0.0, value=_cur_net, step=0.01, format="%.2f", key="fix_net")
    with _f2:
        _new_cus = st.number_input("Πελάτες", min_value=0, value=_cur_cus, step=1, key="fix_cus")
    with _f3:
        _new_bsk = st.number_input("ΜΟ Καλαθιού (€)", min_value=0.0, value=_cur_bsk, step=0.01, format="%.2f", key="fix_bsk")
    st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
    if st.button("💾 Αποθήκευση διόρθωσης", key="save_fix", use_container_width=True):
        _ns = _new_net if _new_net != _cur_net else None
        _nc = _new_cus if _new_cus != _cur_cus else None
        _nb = _new_bsk if _new_bsk != _cur_bsk else None
        if _ns is None and _nc is None and _nb is None:
            st.markdown('<div class="alert alert-warn">⚠️ Δεν άλλαξες καμία τιμή.</div>', unsafe_allow_html=True)
        else:
            with st.spinner("Αποθήκευση..."):
                _ok, _msg = update_sales_value(_fix_date, net_sales=_ns, customers=_nc, avg_basket=_nb)
            if _ok:
                _raw_load_sales.clear()
                st.markdown(f'<div class="alert alert-success">✅ {_msg}</div>', unsafe_allow_html=True)
                st.rerun()
            else:
                st.markdown(f'<div class="alert alert-error">❌ {_msg}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


def _render_sales_add(df_s):
    st.caption("Αν ο έλεγχος βρήκε κενό (χαμένη μέρα), πρόσθεσέ την εδώ χειροκίνητα.")
    _add_date = st.date_input("Ημερομηνία", today, key="add_sales_date")
    _exists = False
    if not df_s.empty:
        _exists = not df_s[df_s["date"].apply(lambda x: (x.date() if hasattr(x, "date") else x)) == _add_date].empty
    if _exists:
        st.markdown(f'<div class="alert alert-warn">⚠️ Η {_add_date.strftime("%d/%m/%Y")} υπάρχει ήδη. Χρησιμοποίησε τη «Διόρθωση».</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="alert alert-info">Νέα εγγραφή για <b>{DAYS_GR[_add_date.weekday()]} {_add_date.strftime("%d/%m/%Y")}</b></div>', unsafe_allow_html=True)
    _af1, _af2, _af3 = st.columns(3)
    with _af1:
        _add_net = st.number_input("Καθαρές Πωλήσεις (€)", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="add_net")
    with _af2:
        _add_cus = st.number_input("Πελάτες", min_value=0, value=0, step=1, key="add_cus")
    with _af3:
        _add_bsk = st.number_input("ΜΟ Καλαθιού (€)", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="add_bsk")
    st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
    if st.button("➕ Προσθήκη ημέρας", key="save_add", use_container_width=True, disabled=_exists):
        if _add_net <= 0:
            st.markdown('<div class="alert alert-warn">⚠️ Βάλε έγκυρη τιμή στις Καθαρές Πωλήσεις.</div>', unsafe_allow_html=True)
        else:
            _rec = {"date": _add_date.isoformat(), "net_sales": _add_net,
                    "customers": int(_add_cus) if _add_cus > 0 else None,
                    "avg_basket": _add_bsk if _add_bsk > 0 else (round(_add_net / _add_cus, 2) if _add_cus > 0 else None)}
            with st.spinner("Προσθήκη..."):
                _added = merge_sales([_rec])
            if _added:
                _raw_load_sales.clear()
                st.markdown(f'<div class="alert alert-success">✅ Προστέθηκε η {_add_date.strftime("%d/%m/%Y")}.</div>', unsafe_allow_html=True)
                st.rerun()
            else:
                st.markdown('<div class="alert alert-warn">ℹ️ Δεν προστέθηκε (ίσως υπάρχει ήδη).</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


def _render_sales_check():
    st.caption("Ελέγχει για διπλές ημερομηνίες ή χαμένες μέρες στις πωλήσεις.")
    if st.button("Εκτέλεση ελέγχου", key="run_sales_check", use_container_width=True):
        st.session_state["sales_check_done"] = True
    if st.session_state.get("sales_check_done"):
        with st.spinner("Έλεγχος..."):
            _q = check_sales_quality()
        _dups = _q.get("duplicates", [])
        _gaps = _q.get("gaps", [])
        if not _dups and not _gaps:
            st.markdown('<div class="alert alert-success">✅ Όλα εντάξει! Καμία διπλοεγγραφή ή κενό.</div>', unsafe_allow_html=True)
        if _dups:
            st.markdown(f'<div class="alert alert-warn">⚠️ Βρέθηκαν {len(_dups)} διπλές ημερομηνίες. Επίλεξε ποια να κρατήσεις:</div>', unsafe_allow_html=True)
            for _d in _dups:
                st.markdown(f'**📅 {_d["date"]}** — {len(_d["entries"])} εγγραφές:')
                for _e in _d["entries"]:
                    _bc1, _bc2 = st.columns([3, 1])
                    with _bc1:
                        st.markdown(f'<div style="padding:.4rem 0">Γραμμή {_e["row"]}: <b>{fmt(_e["net_sales"])}</b></div>', unsafe_allow_html=True)
                    with _bc2:
                        if st.button("🗑 Διαγραφή", key=f"del_sales_{_e['row']}", use_container_width=True):
                            _ok, _msg = delete_sheet_row("sales", _e["row"])
                            if _ok:
                                _raw_load_sales.clear()
                                st.success(_msg); st.rerun()
                            else:
                                st.error(_msg)
        if _gaps:
            _gaps_str = ", ".join(_gaps[:20]) + (" …" if len(_gaps) > 20 else "")
            st.markdown(f'<div class="alert alert-error">📭 Λείπουν {len(_gaps)} ημέρες: {_gaps_str}<br><br>Συμπλήρωσέ τες από την «➕ Προσθήκη».</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΕΠΙΣΚΟΠΗΣΗ (Overview) — 3 κάρτες, χωρίς γραφήματα
# ══════════════════════════════════════════════════════════════════════════════
if page == "Επισκόπηση":
    st.markdown("""
<div class="page-header">
<div class="icon">🏠</div>
<div><h1>Επισκόπηση</h1><div class="sub">Συνοπτική εικόνα τρέχουσας εβδομάδας</div></div>
</div>
""", unsafe_allow_html=True)

    df_s = load_sales()
    df_i = load_invoices()
    df_t = load_timologiseis()

    # Επιλογή εβδομάδας: ΠΑΝΤΑ η τρέχουσα εβδομάδα (Δευτ→Κυρ).
    # Κάθε Δευτέρα ξεκινά αυτόματα νέα εβδομάδα — τα παλιά δεδομένα παραμένουν
    # αποθηκευμένα στο αρχείο, αλλά το Overview δείχνει πάντα την τρέχουσα εβδομάδα.
    # Όσο περνούν οι μέρες, η εβδομάδα συμπληρώνεται με τα νέα στοιχεία.
    sw_cur, ew_cur   = get_week_range(today)
    psw_cur, pew_cur = prev_week_range(sw_cur)
    sw, ew, psw, pew = sw_cur, ew_cur, psw_cur, pew_cur
    _wlabel = "Τρέχουσα εβδομάδα"

    st.markdown(f'<div class="date-badge">🗓 {DAYS_GR[today.weekday()]} {today.strftime("%d/%m/%Y")} · Τρέχουσα εβδομάδα</div>', unsafe_allow_html=True)

    # ── Πωλήσεις: ΣΗΜΕΡΑ vs ΠΕΡΣΙ ίδια ημερομηνία ──
    # Φτιάχνουμε βοηθητική στήλη με καθαρές ημερομηνίες (date) για ασφαλείς συγκρίσεις
    if not df_s.empty:
        _sdates = df_s["date"].apply(lambda x: x.date() if hasattr(x, "date") else x)
    else:
        _sdates = pd.Series([], dtype=object)

    def _day_sales(d):
        if df_s.empty:
            return None
        m = df_s[_sdates == d]
        return m["net_sales"].sum() if not m.empty else None

    today_sales = _day_sales(today)
    # «Πέρσι σαν σήμερα» = ίδια ΜΕΡΑ της εβδομάδας πέρσι (όχι ίδια ημερομηνία).
    # 364 ημέρες πίσω (= 52 εβδομάδες) πέφτει πάντα στην ίδια ημέρα της εβδομάδας,
    # στην αντίστοιχη εβδομάδα της περσινής χρονιάς.
    ly_same_date = today - timedelta(days=364)
    ly_day_sales = _day_sales(ly_same_date)
    today_dow = DAYS_GR[today.weekday()]
    ly_dow    = DAYS_GR[ly_same_date.weekday()]

    # ── Εβδομάδα ΩΣ ΤΩΡΑ (Δευτ→σήμερα) vs ΠΕΡΣΙ ίδιες ημέρες ──
    wk_start, _wk_end_full = get_week_range(today)
    days_elapsed = (today - wk_start).days  # 0=Δευτ ... 6=Κυρ
    wtd_end = today
    if not df_s.empty:
        wtd_mask = (_sdates >= wk_start) & (_sdates <= wtd_end)
        wtd_sum = df_s[wtd_mask]["net_sales"].sum()
    else:
        wtd_sum = 0

    # Περσινές ανάλογες μέρες: ίδια ημερομηνία έναρξης εβδομάδας πέρσι, ίδιο πλήθος ημερών
    ly_wk_start = wk_start.replace(year=wk_start.year - 1)
    ly_wtd_end  = ly_wk_start + timedelta(days=days_elapsed)
    if not df_s.empty:
        ly_wtd_mask = (_sdates >= ly_wk_start) & (_sdates <= ly_wtd_end)
        _ly_wtd_df = df_s[ly_wtd_mask]
        ly_wtd_sum = _ly_wtd_df["net_sales"].sum() if not _ly_wtd_df.empty else None
    else:
        ly_wtd_sum = None

    # Εύρος ημερών για ετικέτα (π.χ. "Δευ–Τρι")
    _wd_first = DAYS_GR[wk_start.weekday()]
    _wd_last  = DAYS_GR[wtd_end.weekday()]
    _wtd_label = _wd_first if days_elapsed == 0 else f"{_wd_first}–{_wd_last}"

    # Τιμολόγια (καθαρό) εβδομάδας
    inv_net_ov = 0
    if not df_i.empty:
        mask_ov = (df_i["date"] >= pd.Timestamp(sw)) & (df_i["date"] <= pd.Timestamp(ew) + pd.Timedelta(hours=23, minutes=59))
        wi_ov = df_i.loc[mask_ov]
        if not wi_ov.empty:
            _inv = wi_ov[~wi_ov["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
            _crd = wi_ov[wi_ov["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
            inv_net_ov = _inv - _crd

    # Επιταγή που "πέφτει" σε αυτή την εβδομάδα (εβδομάδα πριν την ημ. επιταγής)
    check_html = ""
    if not df_t.empty:
        for _, _row in df_t.iterrows():
            _cd = _row["check_date"]
            if pd.isna(_cd):
                continue
            _cd_date = _cd.date() if hasattr(_cd, "date") else _cd
            _wb_start, _ = get_week_range(_cd_date - timedelta(days=7))
            if sw == _wb_start:
                check_html = (
                    '<a href="?page=%CE%A4%CE%B9%CE%BC%CE%BF%CE%BB%CE%BF%CE%B3%CE%AE%CF%83%CE%B5%CE%B9%CF%82" target="_self" style="text-decoration:none">'
                    '<div class="kpi-card" style="--accent:#3b82f6"><div class="glow"></div>'
                    '<div class="kpi-label">💳 Πληρωμή με Επιταγή →</div>'
                    f'<div class="kpi-value blue">{fmt(_row["amount"])}</div>'
                    f'<div class="kpi-sub">Ημ. επιταγής: <b style="color:var(--text)">{_cd_date.strftime("%d/%m/%Y")}</b></div>'
                    '</div></a>'
                )
                break
    if not check_html:
        check_html = (
            '<a href="?page=%CE%A4%CE%B9%CE%BC%CE%BF%CE%BB%CE%BF%CE%B3%CE%AE%CF%83%CE%B5%CE%B9%CF%82" target="_self" style="text-decoration:none">'
            '<div class="kpi-card" style="--accent:#5a6b8c">'
            '<div class="kpi-label">💳 Πληρωμή με Επιταγή →</div>'
            '<div class="kpi-value" style="color:var(--text-dim);font-size:1.25rem">—</div>'
            '<div class="kpi-sub">Καμία επιταγή αυτή την εβδομάδα</div></div></a>'
        )

    def _pct_html(cur, ref):
        if ref is None or ref == 0:
            return '<span style="color:var(--text-dim)">— χωρίς περσινά</span>'
        diff = cur - ref; pct = diff / ref * 100
        col = "#1aa260" if diff >= 0 else "#E2231A"; arr = "↑" if diff >= 0 else "↓"
        return f'<span style="color:{col};font-weight:700">{arr} {abs(pct):.1f}%</span>'

    def _pct_html_w(cur, ref):
        # Έκδοση για σκούρες gradient κάρτες (λευκό/ανοιχτό κείμενο)
        if ref is None or ref == 0:
            return '<span style="opacity:.85">— χωρίς περσινά</span>'
        diff = cur - ref; pct = diff / ref * 100
        bg = "rgba(255,255,255,.25)"; arr = "↑" if diff >= 0 else "↓"
        return f'<span style="background:{bg};padding:.1rem .45rem;border-radius:6px;font-weight:700">{arr} {abs(pct):.1f}%</span>'

    import urllib.parse as _u
    _lnk_sales = "?page=" + _u.quote("Πωλήσεις")
    _lnk_inv   = "?page=" + _u.quote("Παραστατικά")

    # ── Gradient hero cards (στυλ Flowlu) ──
    _today_val = fmt(today_sales) if today_sales is not None else "—"
    _ly_val = fmt(ly_day_sales) if ly_day_sales is not None else "—"
    # Hero 1: ΣΗΜΕΡΑ (μπλε gradient)
    _hero_today = (
        f'<a href="{_lnk_sales}" target="_self" style="text-decoration:none">'
        '<div class="hero-card grad-blue">'
        '<div class="hero-icon">📅</div>'
        f'<div class="hero-label">Σήμερα · {today_dow} {today.strftime("%d/%m")}</div>'
        f'<div class="hero-value">{_today_val}</div>'
        f'<div class="hero-sub">🕐 Πέρσι {ly_dow} {ly_same_date.strftime("%d/%m")}: <b>{_ly_val}</b> · {_pct_html_w(today_sales or 0, ly_day_sales)}</div>'
        '</div></a>'
    )
    # Hero 2: ΕΒΔΟΜΑΔΑ ΩΣ ΤΩΡΑ (μωβ gradient)
    _hero_week = (
        f'<a href="{_lnk_sales}" target="_self" style="text-decoration:none">'
        '<div class="hero-card grad-violet">'
        '<div class="hero-icon">📊</div>'
        f'<div class="hero-label">Εβδομάδα ως τώρα · {_wtd_label}</div>'
        f'<div class="hero-value">{fmt(wtd_sum)}</div>'
        f'<div class="hero-sub">vs πέρσι ίδιες μέρες: {_pct_html_w(wtd_sum, ly_wtd_sum)}</div>'
        '</div></a>'
    )

    _ov_row1 = '<div class="kpi-grid kpi-2">' + _hero_today + _hero_week + '</div>'
    st.markdown(_ov_row1, unsafe_allow_html=True)

    # Δεύτερη σειρά: Τιμολόγια (καθαρό) + Πληρωμή με Επιταγή (λευκές κάρτες)
    _ov_row2 = (
        '<div class="kpi-grid kpi-2">'
        f'<a href="{_lnk_inv}" target="_self" style="text-decoration:none">'
        '<div class="kpi-card" style="--accent:#0072CE"><div class="glow"></div>'
        '<div class="kpi-label">Τιμολόγια (καθαρό) →</div>'
        f'<div class="kpi-value green">{fmt(inv_net_ov)}</div>'
        '<div class="kpi-sub">Σύνολο εβδομάδας</div></div></a>'
        f'{check_html}'
        '</div>'
    )
    st.markdown(_ov_row2, unsafe_allow_html=True)

    # ── Γράφημα: εβδομαδιαία πορεία φέτος vs πέρσι ──
    if not df_s.empty:
        st.markdown('<div class="section-label">📊 Εβδομαδιαία πορεία — φέτος vs πέρσι</div>', unsafe_allow_html=True)
        _dfc = df_s.copy()
        _dfc["d"] = _dfc["date"].apply(lambda x: x.date() if hasattr(x, "date") else x)
        # Εβδομάδα του έτους (ISO) + έτος
        _dfc["isoyear"] = _dfc["d"].apply(lambda d: d.isocalendar()[0])
        _dfc["isoweek"] = _dfc["d"].apply(lambda d: d.isocalendar()[1])
        _cur_year = today.isocalendar()[0]
        _cur_week = today.isocalendar()[1]

        # Σύνολα ανά εβδομάδα για φέτος & πέρσι
        def _weekly_series(year):
            _sub = _dfc[_dfc["isoyear"] == year]
            if _sub.empty:
                return {}
            g = _sub.groupby("isoweek").agg(sales=("net_sales", "sum"), custs=("customers", "sum"))
            return g

        _g_cur = _weekly_series(_cur_year)
        _g_prev = _weekly_series(_cur_year - 1)

        # Εύρος εβδομάδων: 1 έως τρέχουσα εβδομάδα
        _weeks = list(range(1, _cur_week + 1))
        import pandas as _pd2
        _sales_chart = _pd2.DataFrame(index=_weeks)
        _sales_chart["Φέτος"] = [(_g_cur.loc[w, "sales"] if (len(_g_cur) and w in _g_cur.index) else None) for w in _weeks]
        _sales_chart["Πέρσι"] = [(_g_prev.loc[w, "sales"] if (len(_g_prev) and w in _g_prev.index) else None) for w in _weeks]
        _sales_chart.index.name = "Εβδομάδα"

        st.markdown('<div style="font-size:.78rem;color:var(--text-mut);margin:.3rem 0 .5rem">Καθαρές πωλήσεις ανά εβδομάδα (€)</div>', unsafe_allow_html=True)
        st.line_chart(_sales_chart, height=260, color=["#0072CE", "#8b5cf6"])

        _cust_chart = _pd2.DataFrame(index=_weeks)
        _cust_chart["Φέτος"] = [(_g_cur.loc[w, "custs"] if (len(_g_cur) and w in _g_cur.index) else None) for w in _weeks]
        _cust_chart["Πέρσι"] = [(_g_prev.loc[w, "custs"] if (len(_g_prev) and w in _g_prev.index) else None) for w in _weeks]
        _cust_chart.index.name = "Εβδομάδα"
        st.markdown('<div style="font-size:.78rem;color:var(--text-mut);margin:1rem 0 .5rem">Πελάτες ανά εβδομάδα</div>', unsafe_allow_html=True)
        st.line_chart(_cust_chart, height=260, color=["#10b981", "#f59e0b"])

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΠΩΛΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Πωλήσεις":
    st.markdown("""
<div class="page-header">
<div class="icon">📈</div>
<div><h1>Πωλήσεις</h1><div class="sub">Εβδομαδιαία & ετήσια ανάλυση</div></div>
</div>
""", unsafe_allow_html=True)

    df_s = load_sales()
    if df_s.empty:
        st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα πωλήσεων ακόμη.</div>', unsafe_allow_html=True)
        st.stop()

    # ── Εργαλεία διαχείρισης (κάτω από τον τίτλο) ──
    with st.expander("🛠 Εργαλεία διαχείρισης (διόρθωση · προσθήκη · έλεγχος)"):
        _tool_tab1, _tool_tab2, _tool_tab3 = st.tabs(["✏️ Διόρθωση", "➕ Προσθήκη", "🔍 Έλεγχος"])
        with _tool_tab1:
            _render_sales_fix(df_s)
        with _tool_tab2:
            _render_sales_add(df_s)
        with _tool_tab3:
            _render_sales_check()

    t_wk, t_yr = st.tabs(["Εβδομαδιαία", "Ετήσια"])

    with t_wk:
        # Μικρότερο πεδίο ημερομηνίας (σε στενή στήλη)
        _dcol, _ = st.columns([1, 2])
        with _dcol:
            sel_s = st.date_input("Επίλεξε ημέρα", today, key="sales_wk_date")

        _sdates_w = df_s["date"].apply(lambda x: x.date() if hasattr(x, "date") else x)

        def _day_net(d):
            m = df_s[_sdates_w == d]
            return m["net_sales"].sum() if not m.empty else None

        # Είναι μελλοντική μέρα; (δεν έχει ταμείο ακόμα)
        _is_future = sel_s > today
        _day_has_data = _day_net(sel_s) is not None

        if _is_future or not _day_has_data:
            # ── Μελλοντική/κενή μέρα: δείξε «σαν εκείνη τη μέρα πέρσι» ──
            _ly_day = sel_s - timedelta(days=364)
            _ly_dow = DAYS_GR[_ly_day.weekday()]
            _sel_dow = DAYS_GR[sel_s.weekday()]
            _ly_net = _day_net(_ly_day)
            _ly_row = df_s[_sdates_w == _ly_day]
            _ly_cst = int(_ly_row["customers"].iloc[0]) if (not _ly_row.empty and pd.notna(_ly_row["customers"].iloc[0])) else None
            _ly_avg = float(_ly_row["avg_basket"].iloc[0]) if (not _ly_row.empty and pd.notna(_ly_row["avg_basket"].iloc[0])) else None
            st.markdown(f'<div class="date-badge">🗓 {_sel_dow} {sel_s.strftime("%d/%m/%Y")} · {"μελλοντική μέρα" if _is_future else "χωρίς ταμείο ακόμα"}</div>', unsafe_allow_html=True)
            _ly_net_txt = fmt(_ly_net) if _ly_net is not None else "—"
            _ly_cst_txt = fmt_int(_ly_cst) if _ly_cst is not None else "—"
            _ly_avg_txt = fmt(_ly_avg) if _ly_avg is not None else "—"
            st.markdown(
                '<div class="kpi-grid kpi-3">'
                '<div class="kpi-card" style="--accent:#10b981"><div class="glow"></div>'
                '<div class="kpi-label">Καθαρές Πωλήσεις</div>'
                '<div class="kpi-value green">0,00 €</div>'
                f'<div style="margin-top:.85rem;padding-top:.7rem;border-top:1px solid var(--border-soft)">'
                f'<div class="kpi-sub" style="font-weight:700;color:var(--text)">🕐 Σαν {_ly_dow} {_ly_day.strftime("%d/%m/%y")} (πέρσι)</div>'
                f'<div class="kpi-value violet" style="font-size:1.2rem;margin-top:.25rem">{_ly_net_txt}</div></div></div>'
                '<div class="kpi-card" style="--accent:#3b82f6"><div class="glow"></div>'
                '<div class="kpi-label">Πελάτες</div>'
                '<div class="kpi-value blue">0</div>'
                f'<div style="margin-top:.85rem;padding-top:.7rem;border-top:1px solid var(--border-soft)">'
                f'<div class="kpi-sub" style="font-weight:700;color:var(--text)">🕐 Πέρσι</div>'
                f'<div class="kpi-value violet" style="font-size:1.2rem;margin-top:.25rem">{_ly_cst_txt}</div></div></div>'
                '<div class="kpi-card" style="--accent:#8b5cf6"><div class="glow"></div>'
                '<div class="kpi-label">ΜΟ Καλαθιού</div>'
                '<div class="kpi-value violet">—</div>'
                f'<div style="margin-top:.85rem;padding-top:.7rem;border-top:1px solid var(--border-soft)">'
                f'<div class="kpi-sub" style="font-weight:700;color:var(--text)">🕐 Πέρσι</div>'
                f'<div class="kpi-value violet" style="font-size:1.2rem;margin-top:.25rem">{_ly_avg_txt}</div></div></div>'
                '</div>',
                unsafe_allow_html=True
            )
        else:
            # ── Κανονική εβδομάδα: σύγκριση ΜΕΧΡΙ την επιλεγμένη μέρα (όχι όλη η εβδομάδα) ──
            sw, ew = get_week_range(sel_s)
            _elapsed = (sel_s - sw).days  # 0=Δευτ ... 6=Κυρ (μέχρι την επιλεγμένη μέρα)
            # Φέτος: Δευτ→επιλεγμένη μέρα
            w_df = df_s[(_sdates_w >= sw) & (_sdates_w <= sel_s)]
            # Πέρσι: αντίστοιχη εβδομάδα (364 μέρες πίσω), ΜΕΧΡΙ την αντίστοιχη μέρα
            _ly_sw = sw - timedelta(days=364)
            _ly_sel = sel_s - timedelta(days=364)
            pw_df = df_s[(_sdates_w >= _ly_sw) & (_sdates_w <= _ly_sel)]

            _sel_dow = DAYS_GR[sel_s.weekday()]
            st.markdown(f'<div class="date-badge">🗓 Δευτ. {sw.strftime("%d/%m")} → {_sel_dow} {sel_s.strftime("%d/%m/%Y")} (εβδομάδα ως τη μέρα)</div>', unsafe_allow_html=True)

            tot = w_df["net_sales"].sum(); cst = w_df["customers"].sum(); avg = w_df["avg_basket"].mean()
            p_tot = pw_df["net_sales"].sum() if not pw_df.empty else None
            p_cst = pw_df["customers"].sum() if not pw_df.empty else None
            p_avg = pw_df["avg_basket"].mean() if not pw_df.empty else None
            st.markdown(f"""
<div class="kpi-grid kpi-3">
<div class="kpi-card" style="--accent:#10b981"><div class="glow"></div>
<div class="kpi-label">Καθαρές Πωλήσεις</div>
<div class="kpi-value green">{fmt(tot)}</div>{trend_html(tot, p_tot)}
<div class="kpi-sub">vs πέρσι ίδιες μέρες (ως {_sel_dow})</div></div>
<div class="kpi-card" style="--accent:#3b82f6"><div class="glow"></div>
<div class="kpi-label">Πελάτες</div>
<div class="kpi-value blue">{fmt_int(cst)}</div>{trend_html(cst, p_cst, unit="")}
<div class="kpi-sub">vs πέρσι ίδιες μέρες</div></div>
<div class="kpi-card" style="--accent:#8b5cf6"><div class="glow"></div>
<div class="kpi-label">ΜΟ Καλαθιού</div>
<div class="kpi-value violet">{fmt(avg)}</div>{trend_html(avg, p_avg)}
<div class="kpi-sub">vs πέρσι ίδιες μέρες</div></div>
</div>
""", unsafe_allow_html=True)
            st.markdown('<div class="section-label">Αναλυτικά ανά ημέρα</div>', unsafe_allow_html=True)
            disp = w_df.copy(); disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
            disp = disp.sort_values("date", ascending=False)
            st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).style.format({
                "ΠΩΛΗΣΕΙΣ": lambda v: fmt(v), "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—",
                "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—"}),
                use_container_width=True, hide_index=True)

    with t_yr:
        _yrs = sorted({(d.year if hasattr(d, "year") else d.year) for d in df_s["date"]}, reverse=True)
        sy = st.selectbox("Έτος", _yrs, key="sales_yr_sel")
        st.markdown(f'<div class="date-badge">🗓 Έτος {sy}</div>', unsafe_allow_html=True)
        y_df = df_s[df_s["date"].apply(lambda d: d.year) == sy]
        py_df = df_s[df_s["date"].apply(lambda d: d.year) == (sy - 1)]
        if not y_df.empty:
            y_tot = y_df["net_sales"].sum()
            y_cst = y_df["customers"].sum() if "customers" in y_df.columns else None
            y_avg = y_df["net_sales"].mean()
            py_tot = py_df["net_sales"].sum() if not py_df.empty else None
            st.markdown(f"""
<div class="kpi-grid kpi-3">
<div class="kpi-card" style="--accent:#0072CE"><div class="glow"></div>
<div class="kpi-label">Σύνολο Έτους</div><div class="kpi-value green">{fmt(y_tot)}</div>{trend_html(y_tot, py_tot)}</div>
<div class="kpi-card" style="--accent:#2b96e8"><div class="glow"></div>
<div class="kpi-label">Ημερήσιος ΜΟ</div><div class="kpi-value blue">{fmt(y_avg)}</div></div>
<div class="kpi-card" style="--accent:#6d5bd0"><div class="glow"></div>
<div class="kpi-label">Πελάτες (σύνολο)</div><div class="kpi-value violet">{fmt_int(y_cst) if y_cst else '—'}</div></div>
</div>
""", unsafe_allow_html=True)
            # Ανάλυση ανά μήνα (μήνες + αθροίσματα)
            st.markdown('<div class="section-label">Ανάλυση ανά μήνα</div>', unsafe_allow_html=True)
            _months_html = ""
            for _mn in range(1, 13):
                _mdf = y_df[y_df["date"].apply(lambda d: d.month) == _mn]
                if _mdf.empty:
                    continue
                _mtot = _mdf["net_sales"].sum()
                _mcst = int(_mdf["customers"].sum()) if "customers" in _mdf.columns and _mdf["customers"].notna().any() else 0
                _mdays = len(_mdf)
                _months_html += (
                    '<div class="year-row">'
                    f'<div><span class="yr">{MONTHS_GR[_mn-1]}</span> &nbsp;<span class="cnt">· {_mdays} ημέρες · {_mcst} πελάτες</span></div>'
                    f'<span class="amt">{fmt(_mtot)}</span>'
                    '</div>'
                )
            st.markdown(_months_html, unsafe_allow_html=True)
            _csv = y_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).copy()
            _csv["ΗΜΕΡΟΜΗΝΙΑ"] = _csv["ΗΜΕΡΟΜΗΝΙΑ"].apply(lambda d: d.strftime("%d/%m/%Y"))
            _csv = _csv.to_csv(index=False).encode("utf-8-sig")
            st.download_button(f"↓ Λήψη CSV — Έτος {sy}", _csv, f"sales_{sy}.csv", "text/csv", key="sales_dl")
        else:
            st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτό το έτος.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΠΑΡΑΣΤΑΤΙΚΑ — χωρίς πίτα
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Παραστατικά":
    st.markdown("""
<div class="page-header">
<div class="icon">🧾</div>
<div><h1>Παραστατικά</h1><div class="sub">Τιμολόγια & πιστωτικά</div></div>
</div>
""", unsafe_allow_html=True)

    df_inv = load_invoices()

    # ── Εργαλεία διαχείρισης (κάτω από τον τίτλο) ──
    with st.expander("🛠 Εργαλεία διαχείρισης (έλεγχος διπλών & κενών)"):
        st.caption("Ελέγχει για πανομοιότυπες εγγραφές (ίδια ημερομηνία+τύπος+αξία) ή χαμένες μέρες.")
        if st.button("Εκτέλεση ελέγχου", key="run_inv_check", use_container_width=True):
            st.session_state["inv_check_done"] = True
        if st.session_state.get("inv_check_done"):
            with st.spinner("Έλεγχος..."):
                _qi = check_invoices_quality()
            _idups = _qi.get("duplicates", [])
            _igaps = _qi.get("gaps", [])
            if not _idups and not _igaps:
                st.markdown('<div class="alert alert-success">✅ Όλα εντάξει! Καμία πανομοιότυπη εγγραφή ή κενό.</div>', unsafe_allow_html=True)
            if _idups:
                st.markdown(f'<div class="alert alert-warn">⚠️ Βρέθηκαν {len(_idups)} πανομοιότυπες εγγραφές. Διάγραψε τις περιττές:</div>', unsafe_allow_html=True)
                for _d in _idups:
                    st.markdown(f'**📅 {_d["date"]}** · {_d["type"]} · <b>{fmt(_d["value"])}</b> — {len(_d["rows"])} ίδιες εγγραφές:', unsafe_allow_html=True)
                    # Κράτα την πρώτη, πρόσφερε διαγραφή για τις υπόλοιπες
                    for _ri in _d["rows"][1:]:
                        _ic1, _ic2 = st.columns([3, 1])
                        with _ic1:
                            st.markdown(f'<div style="padding:.4rem 0">Διπλή στη γραμμή {_ri}</div>', unsafe_allow_html=True)
                        with _ic2:
                            if st.button("🗑 Διαγραφή", key=f"del_inv_{_ri}", use_container_width=True):
                                _ok, _msg = delete_sheet_row("invoices", _ri)
                                if _ok:
                                    _raw_load_invoices.clear()
                                    st.success(_msg); st.rerun()
                                else:
                                    st.error(_msg)
            if _igaps:
                _ig_str = ", ".join(_igaps[:20]) + (" …" if len(_igaps) > 20 else "")
                st.markdown(f'<div class="alert alert-error">📭 Λείπουν {len(_igaps)} εργάσιμες μέρες: {_ig_str}<br><br>Πάτησε «Ενημέρωση Παραστατικών» στο κάτω μέρος για να τις τραβήξεις.</div>', unsafe_allow_html=True)

    t_wk, t_yr = st.tabs(["Εβδομαδιαία", "Ετήσια"])

    with t_wk:
        if df_inv.empty:
            st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα παραστατικών ακόμη.</div>', unsafe_allow_html=True)
        else:
            sel_i = st.date_input("Επίλεξε ημέρα", today, key="inv_wk_date")
            sw, ew = get_week_range(sel_i)
            st.markdown(f'<div class="date-badge">🗓 Δευτ. {sw.strftime("%d/%m/%Y")} — Κυρ. {ew.strftime("%d/%m/%Y")}</div>', unsafe_allow_html=True)
            mask = (df_inv["date"] >= pd.Timestamp(sw)) & (df_inv["date"] <= pd.Timestamp(ew) + pd.Timedelta(hours=23, minutes=59))
            w_df = df_inv.loc[mask]
            if not w_df.empty:
                inv_v = w_df[~w_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                crd_v = w_df[w_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                st.markdown(f"""
<div class="kpi-grid kpi-3">
<div class="kpi-card" style="--accent:#10b981"><div class="glow"></div>
<div class="kpi-label">Τιμολόγια</div><div class="kpi-value green">{fmt(inv_v)}</div></div>
<div class="kpi-card" style="--accent:#ef4444"><div class="glow"></div>
<div class="kpi-label">Πιστωτικά</div><div class="kpi-value red">-{fmt(crd_v)}</div></div>
<div class="kpi-card" style="--accent:#3b82f6"><div class="glow"></div>
<div class="kpi-label">Καθαρό</div><div class="kpi-value blue">{fmt(inv_v - crd_v)}</div></div>
</div>
""", unsafe_allow_html=True)
                st.markdown('<div class="section-label">Αναλυτικά</div>', unsafe_allow_html=True)
                disp = w_df.copy(); disp["date"] = disp["date"].dt.strftime("%d/%m/%Y")
                disp = disp.sort_values("date", ascending=False)
                st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).style.format({"ΑΞΙΑ": lambda v: fmt(v)}),
                    use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

    with t_yr:
        if df_inv.empty:
            st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα.</div>', unsafe_allow_html=True)
        else:
            _yrs = sorted(df_inv["date"].dt.year.unique(), reverse=True)
            sy = st.selectbox("Έτος", _yrs, key="inv_yr_sel")
            st.markdown(f'<div class="date-badge">🗓 Έτος {sy}</div>', unsafe_allow_html=True)
            y_df = df_inv[df_inv["date"].dt.year == sy]
            if not y_df.empty:
                inv_y = y_df[~y_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                crd_y = y_df[y_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                st.markdown(f"""
<div class="kpi-grid kpi-3">
<div class="kpi-card" style="--accent:#0072CE"><div class="glow"></div>
<div class="kpi-label">Τιμολόγια</div><div class="kpi-value green">{fmt(inv_y)}</div></div>
<div class="kpi-card" style="--accent:#E2231A"><div class="glow"></div>
<div class="kpi-label">Πιστωτικά</div><div class="kpi-value red">-{fmt(crd_y)}</div></div>
<div class="kpi-card" style="--accent:#2b96e8"><div class="glow"></div>
<div class="kpi-label">Σύνολο Έτους</div><div class="kpi-value blue">{fmt(inv_y - crd_y)}</div></div>
</div>
""", unsafe_allow_html=True)
                # Ανάλυση ανά μήνα (μήνες + καθαρά αθροίσματα)
                st.markdown('<div class="section-label">Ανάλυση ανά μήνα (καθαρό)</div>', unsafe_allow_html=True)
                _months_html = ""
                for _mn in range(1, 13):
                    _mdf = y_df[y_df["date"].dt.month == _mn]
                    if _mdf.empty:
                        continue
                    _minv = _mdf[~_mdf["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                    _mcrd = _mdf[_mdf["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                    _mnet = _minv - _mcrd
                    _months_html += (
                        '<div class="year-row">'
                        f'<div><span class="yr">{MONTHS_GR[_mn-1]}</span> &nbsp;<span class="cnt">· Τιμ. {fmt(_minv)} · Πιστ. {fmt(_mcrd)}</span></div>'
                        f'<span class="amt">{fmt(_mnet)}</span>'
                        '</div>'
                    )
                st.markdown(_months_html, unsafe_allow_html=True)
                _csv = y_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).copy()
                _csv["ΗΜΕΡΟΜΗΝΙΑ"] = _csv["ΗΜΕΡΟΜΗΝΙΑ"].dt.strftime("%d/%m/%Y")
                _csv = _csv.to_csv(index=False).encode("utf-8-sig")
                st.download_button(f"↓ Λήψη CSV — Έτος {sy}", _csv, f"invoices_{sy}.csv", "text/csv", key="inv_dl")
            else:
                st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτό το έτος.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΤΙΜΟΛΟΓΗΣΕΙΣ — σύνολο ανά έτος, χωρίς βαθιά σάρωση
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Τιμολογήσεις":
    st.markdown("""
<div class="page-header">
<div class="icon">💳</div>
<div><h1>Τιμολογήσεις</h1><div class="sub">Πληρωμές με επιταγή ανά έτος</div></div>
</div>
""", unsafe_allow_html=True)

    df_t = load_timologiseis()
    if df_t.empty:
        st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν τιμολογήσεις ακόμη.</div>', unsafe_allow_html=True)
    else:
        # Επόμενη επιταγή
        future = df_t[df_t["check_date"] >= pd.Timestamp(today)].sort_values("check_date")
        next_check = future.iloc[0] if not future.empty else None
        _next_html = ""
        if next_check is not None:
            _next_html = f"""
            <div class="check-card">
                <div class="glow"></div>
                <div>
                    <div style="font-size:.64rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#60a5fa;margin-bottom:.45rem">💳 Επόμενη Επιταγή</div>
                    <div style="font-size:.82rem;color:var(--text-mut)">Ημερομηνία: <b style="color:var(--text)">{next_check["check_date"].strftime("%d/%m/%Y")}</b>{f' · Περίοδος: {next_check["period"]}' if next_check.get("period") else ''}</div>
                </div>
                <div style="font-family:'Plus Jakarta Sans';font-size:1.7rem;font-weight:800;color:#60a5fa">{fmt(next_check["amount"])}</div>
            </div>"""
            st.markdown(_next_html, unsafe_allow_html=True)

        # ── Συνολικό ποσό ανά έτος: ΑΓΟΡΕΣ (επιταγές) + ΠΩΛΗΣΕΙΣ ──
        st.markdown('<div class="section-label">Συνολικό ποσό ανά έτος</div>', unsafe_allow_html=True)
        df_t2 = df_t.copy()
        df_t2["year"] = df_t2["check_date"].dt.year
        by_year = df_t2.groupby("year").agg(total=("amount", "sum"), count=("amount", "size")).reset_index().sort_values("year", ascending=False)

        # Φόρτωσε πωλήσεις για σύνολο ανά έτος
        _df_sales_y = load_sales()
        _sales_by_year = {}
        if not _df_sales_y.empty:
            _tmp = _df_sales_y.copy()
            _tmp["year"] = _tmp["date"].apply(lambda d: d.year if hasattr(d, "year") else d.year)
            _sales_by_year = _tmp.groupby("year")["net_sales"].sum().to_dict()

        # Ποιο έτος είναι ανοιχτό (drill-down) — από το URL ?ty=YEAR
        import urllib.parse as _u_ty
        _open_year = st.query_params.get("ty", "")

        # Επικεφαλίδα στηλών
        st.markdown(
            '<div style="display:flex;align-items:center;justify-content:space-between;'
            'padding:.5rem 1.5rem .4rem;font-size:.64rem;font-weight:700;letter-spacing:.08em;'
            'text-transform:uppercase;color:var(--text-dim)">'
            '<span style="flex:0 0 auto">Έτος</span>'
            '<span style="display:flex;gap:2.5rem"><span style="width:120px;text-align:right">Αγορές</span>'
            '<span style="width:120px;text-align:right">Πωλήσεις</span></span>'
            '</div>',
            unsafe_allow_html=True
        )

        for _, r in by_year.iterrows():
            _yr = int(r["year"])
            _purch = r["total"]
            _sales_v = _sales_by_year.get(_yr, None)
            _is_open = str(_yr) == str(_open_year)
            # Link: αν είναι ανοιχτό, κλικ το κλείνει· αλλιώς το ανοίγει
            _href = "?page=" + _u_ty.quote("Τιμολογήσεις") + ("" if _is_open else f"&ty={_yr}")
            _arrow = "▾" if _is_open else "▸"
            _sales_txt = fmt(_sales_v) if _sales_v is not None else "—"
            st.markdown(
                f'<a href="{_href}" target="_self" style="text-decoration:none">'
                f'<div class="year-row" style="{"border-color:var(--brand);" if _is_open else ""}">'
                f'<div style="display:flex;align-items:center;gap:.6rem">'
                f'<span style="color:var(--brand);font-weight:700">{_arrow}</span>'
                f'<span class="yr">{_yr}</span> '
                f'<span class="cnt">· {int(r["count"])} επιταγές</span></div>'
                f'<div style="display:flex;gap:2.5rem;align-items:center">'
                f'<span class="amt" style="width:120px;text-align:right">{fmt(_purch)}</span>'
                f'<span class="amt" style="width:120px;text-align:right;color:var(--sky)">{_sales_txt}</span>'
                f'</div></div></a>',
                unsafe_allow_html=True
            )
            # Drill-down: αν ανοιχτό, δείξε μήνες από κάτω
            if _is_open:
                _ty_df = df_t2[df_t2["year"] == _yr].copy()
                _ty_df["month"] = _ty_df["check_date"].dt.month
                # Μηνιαίες πωλήσεις του έτους
                _sm_month = {}
                if not _df_sales_y.empty:
                    _smdf = _df_sales_y[_df_sales_y["date"].apply(lambda d: d.year) == _yr].copy()
                    if not _smdf.empty:
                        _smdf["m"] = _smdf["date"].apply(lambda d: d.month)
                        _sm_month = _smdf.groupby("m")["net_sales"].sum().to_dict()
                _mhtml = ""
                for _mn in range(1, 13):
                    _mdf = _ty_df[_ty_df["month"] == _mn]
                    _mpurch = _mdf["amount"].sum() if not _mdf.empty else 0
                    _msales = _sm_month.get(_mn, None)
                    if _mdf.empty and _msales is None:
                        continue
                    _mstxt = fmt(_msales) if _msales is not None else "—"
                    _mptxt = fmt(_mpurch) if _mpurch > 0 else "—"
                    _mhtml += (
                        '<div style="display:flex;align-items:center;justify-content:space-between;'
                        'padding:.7rem 1.5rem;margin-left:1.5rem;border-left:2px solid var(--border);'
                        'background:#f7fbff;border-radius:0 10px 10px 0;margin-bottom:.35rem">'
                        f'<span style="font-weight:600;color:var(--text)">{MONTHS_GR[_mn-1]}</span>'
                        f'<div style="display:flex;gap:2.5rem">'
                        f'<span style="width:120px;text-align:right;font-weight:700;color:var(--brand);font-variant-numeric:tabular-nums">{_mptxt}</span>'
                        f'<span style="width:120px;text-align:right;font-weight:700;color:var(--sky);font-variant-numeric:tabular-nums">{_mstxt}</span>'
                        f'</div></div>'
                    )
                if _mhtml:
                    st.markdown(_mhtml, unsafe_allow_html=True)

        # ── Αναλυτικός πίνακας με Πωλήσεις περιόδου + αρ. επιταγής + διαφορά ──
        st.markdown('<div class="section-label">Όλες οι τιμολογήσεις</div>', unsafe_allow_html=True)

        # Φόρτωσε πωλήσεις για υπολογισμό «πωλήσεων περιόδου»
        _df_sales_t = load_sales()
        _sdates_t = _df_sales_t["date"].apply(lambda x: x.date() if hasattr(x, "date") else x) if not _df_sales_t.empty else None

        def _parse_period(period_str, ref_year):
            """Μετατρέπει περίοδο σε (start_date, end_date).
            Δέχεται μορφές: 'ΗΗ.ΜΜ.ΕΕΕΕ - ΗΗ.ΜΜ.ΕΕΕΕ' ή 'ΗΗ.ΜΜ - ΗΗ.ΜΜ'.
            Επιστρέφει (None, None) αν αποτύχει."""
            import re as _re_p
            s = str(period_str)
            # Πρώτα δοκίμασε πλήρεις ημερομηνίες με έτος: ΗΗ.ΜΜ.ΕΕΕΕ - ΗΗ.ΜΜ.ΕΕΕΕ
            m = _re_p.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})\s*-\s*(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
            if m:
                try:
                    start = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    end = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
                    return start, end
                except Exception:
                    return None, None
            # Αλλιώς: ΗΗ.ΜΜ - ΗΗ.ΜΜ (χωρίς έτος) — χρησιμοποίησε το ref_year
            m = _re_p.search(r"(\d{1,2})[./](\d{1,2})\s*-\s*(\d{1,2})[./](\d{1,2})", s)
            if m:
                d1, m1, d2, m2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                try:
                    start = date(ref_year, m1, d1)
                    end_year = ref_year + 1 if m2 < m1 else ref_year
                    end = date(end_year, m2, d2)
                    return start, end
                except Exception:
                    return None, None
            return None, None

        def _sales_in_range(start, end):
            if _df_sales_t is None or _df_sales_t.empty or start is None:
                return None
            _mask = (_sdates_t >= start) & (_sdates_t <= end)
            _sub = _df_sales_t[_mask]
            return _sub["net_sales"].sum() if not _sub.empty else None

        # Επικεφαλίδες στηλών
        st.markdown(
            '<div style="display:grid;grid-template-columns:1.1fr 1.3fr 1fr 1.1fr 1.1fr 1.1fr 1fr;gap:.5rem;'
            'padding:.5rem .8rem;font-size:.6rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;'
            'color:var(--text-dim);border-bottom:1.5px solid var(--border)">'
            '<span>Ημ. Επιταγής</span><span>Περίοδος</span><span style="text-align:right">Ποσό</span>'
            '<span style="text-align:right">Πωλ. Περιόδου</span><span style="text-align:right">Πέρσι Τιμολ.</span>'
            '<span>Αρ. Επιταγής</span><span style="text-align:right">Διαφορά</span>'
            '</div>',
            unsafe_allow_html=True
        )

        for _idx, _trow in df_t.iterrows():
            _cd = _trow["check_date"]
            _cd_date = _cd.date() if hasattr(_cd, "date") else _cd
            _period = _trow.get("period", "")
            _amount = _trow["amount"]
            _row_num = int(_trow["_row"]) if "_row" in _trow and pd.notna(_trow["_row"]) else None
            _chk_num = _trow.get("check_number", "") if "check_number" in _trow else ""

            # Πωλήσεις περιόδου (φέτος)
            # Πωλήσεις περιόδου = οι 7 ημέρες ΠΡΙΝ την ημ. επιταγής.
            # Π.χ. επιταγή 08/07 → πωλήσεις 01/07 έως 07/07 (οι 7 μέρες ακριβώς πριν).
            _pe = _cd_date - timedelta(days=1)   # μία μέρα πριν την επιταγή (π.χ. 07/07)
            _ps = _cd_date - timedelta(days=7)   # 7 μέρες πριν (π.χ. 01/07)
            _sales_period = _sales_in_range(_ps, _pe)

            # Πέρσι τιμολόγηση ίδιας περιόδου (επιταγή ~364 μέρες πριν)
            _ly_cd = _cd_date - timedelta(days=364)
            _ly_amount = None
            if not df_t.empty:
                _ly_window = df_t[df_t["check_date"].apply(lambda x: abs(((x.date() if hasattr(x,"date") else x) - _ly_cd).days) <= 3)]
                if not _ly_window.empty:
                    _ly_amount = _ly_window.iloc[0]["amount"]

            # Διαφορά = Πωλήσεις περιόδου − Ποσό
            _diff = (_sales_period - _amount) if _sales_period is not None else None
            _diff_color = "#1aa260" if (_diff is not None and _diff >= 0) else "#E2231A"

            _c1, _c2, _c3, _c4, _c5, _c6, _c7 = st.columns([1.1, 1.3, 1, 1.1, 1.1, 1.1, 1])
            with _c1:
                st.markdown(f'<div style="padding-top:.5rem;font-weight:600;font-size:.82rem">{_cd_date.strftime("%d/%m/%Y")}</div>', unsafe_allow_html=True)
            with _c2:
                st.markdown(f'<div style="padding-top:.5rem;font-size:.82rem;color:var(--text-mut)">{_period or "—"}</div>', unsafe_allow_html=True)
            with _c3:
                st.markdown(f'<div style="padding-top:.5rem;text-align:right;font-weight:700;font-size:.82rem">{fmt(_amount)}</div>', unsafe_allow_html=True)
            with _c4:
                _sp_txt = fmt(_sales_period) if _sales_period is not None else "—"
                st.markdown(f'<div style="padding-top:.5rem;text-align:right;font-weight:700;color:var(--brand);font-size:.82rem">{_sp_txt}</div>', unsafe_allow_html=True)
            with _c5:
                _ly_txt = fmt(_ly_amount) if _ly_amount is not None else "—"
                st.markdown(f'<div style="padding-top:.5rem;text-align:right;color:var(--violet);font-size:.82rem">{_ly_txt}</div>', unsafe_allow_html=True)
            with _c6:
                _new_chk = st.text_input("αρ", value=_chk_num, key=f"chk_{_row_num}_{_idx}", label_visibility="collapsed", placeholder="—")
                if _new_chk != _chk_num and _row_num:
                    _ok, _msg = update_timologiseis_check_number(_row_num, _new_chk)
                    if _ok:
                        load_timologiseis.clear()
                        st.rerun()
            with _c7:
                _diff_txt = fmt(_diff) if _diff is not None else "—"
                st.markdown(f'<div style="padding-top:.5rem;text-align:right;font-weight:700;color:{_diff_color};font-size:.82rem">{_diff_txt}</div>', unsafe_allow_html=True)

        _csv = df_t.drop(columns=["_row"], errors="ignore").to_csv(index=False).encode("utf-8-sig")
        st.download_button("↓ Λήψη CSV", _csv, "timologiseis.csv", "text/csv", key="timol_dl")

        # ── Έλεγχος ποιότητας δεδομένων (διπλά + κενές εβδομάδες) ──
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        with st.expander("🔍 Έλεγχος δεδομένων (διπλά & κενά)"):
            st.caption("Ελέγχει για διπλές ημερομηνίες επιταγής ή χαμένες εβδομάδες.")
            if st.button("Εκτέλεση ελέγχου", key="run_timol_check", use_container_width=True):
                st.session_state["timol_check_done"] = True
            if st.session_state.get("timol_check_done"):
                with st.spinner("Έλεγχος..."):
                    _qt = check_timologiseis_quality()
                _tdups = _qt.get("duplicates", [])
                _tgaps = _qt.get("gaps", [])
                if not _tdups and not _tgaps:
                    st.markdown('<div class="alert alert-success">✅ Όλα εντάξει! Καμία διπλοεγγραφή ή κενό.</div>', unsafe_allow_html=True)
                if _tdups:
                    st.markdown(f'<div class="alert alert-warn">⚠️ Βρέθηκαν {len(_tdups)} διπλές ημερομηνίες επιταγής. Επίλεξε ποια να κρατήσεις:</div>', unsafe_allow_html=True)
                    for _d in _tdups:
                        st.markdown(f'**📅 {_d["date"]}** — {len(_d["entries"])} εγγραφές:')
                        for _e in _d["entries"]:
                            _tbc1, _tbc2 = st.columns([3, 1])
                            with _tbc1:
                                st.markdown(f'<div style="padding:.4rem 0">Γραμμή {_e["row"]}: <b>{fmt(_e["amount"])}</b></div>', unsafe_allow_html=True)
                            with _tbc2:
                                if st.button("🗑 Διαγραφή", key=f"del_timol_{_e['row']}", use_container_width=True):
                                    _ok, _msg = delete_sheet_row("timologiseis", _e["row"])
                                    if _ok:
                                        load_timologiseis.clear()
                                        st.success(_msg); st.rerun()
                                    else:
                                        st.error(_msg)
                if _tgaps:
                    _gtxt = ""
                    for _g in _tgaps[:15]:
                        _gtxt += f'• Μεταξύ <b>{_g["after"]}</b> και <b>{_g["before"]}</b> ({_g["gap_days"]} μέρες, ~{_g["approx_missing"]} εβδομάδες) <br>'
                    st.markdown(f'<div class="alert alert-error">📭 Πιθανές χαμένες εβδομάδες:<br><br>{_gtxt}</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΜΗΝΑΣ — όλες οι τιμολογήσεις ανά μήνα + έξοδα μήνα
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Μήνας":
    st.markdown("""
<div class="page-header">
<div class="icon">📅</div>
<div><h1>Μήνας</h1><div class="sub">Τιμολογήσεις & έξοδα ανά μήνα</div></div>
</div>
""", unsafe_allow_html=True)

    df_t = load_timologiseis()
    if df_t.empty:
        st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν τιμολογήσεις ακόμη.</div>', unsafe_allow_html=True)
        st.stop()

    # Επιλογή έτους + μήνα
    _yrs_m = sorted({(d.year if hasattr(d, "year") else d.year) for d in df_t["check_date"]}, reverse=True)
    _mc1, _mc2 = st.columns(2)
    with _mc1:
        _sel_year_m = st.selectbox("Έτος", _yrs_m, key="month_year_sel")
    with _mc2:
        _sel_month_m = st.selectbox("Μήνας", list(range(1, 13)),
                                    format_func=lambda m: MONTHS_GR[m - 1],
                                    index=(today.month - 1), key="month_month_sel")

    # Φιλτράρισμα τιμολογήσεων του επιλεγμένου μήνα (βάσει ημ. επιταγής)
    _month_df = df_t[df_t["check_date"].apply(lambda d: (d.year == _sel_year_m and d.month == _sel_month_m))].copy()
    _month_df = _month_df.sort_values("check_date")

    st.markdown(f'<div class="date-badge">🗓 {MONTHS_GR[_sel_month_m-1]} {_sel_year_m} · {len(_month_df)} τιμολογήσεις</div>', unsafe_allow_html=True)

    if _month_df.empty:
        st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν τιμολογήσεις για αυτόν τον μήνα.</div>', unsafe_allow_html=True)
        st.stop()

    # Πωλήσεις για υπολογισμούς
    _df_sales_m = load_sales()
    _sdates_m = _df_sales_m["date"].apply(lambda x: x.date() if hasattr(x, "date") else x) if not _df_sales_m.empty else None

    def _sales_range_m(start, end):
        if _df_sales_m is None or _df_sales_m.empty or start is None:
            return None
        _mask = (_sdates_m >= start) & (_sdates_m <= end)
        _sub = _df_sales_m[_mask]
        return _sub["net_sales"].sum() if not _sub.empty else None

    # Επικεφαλίδες (9 στήλες)
    st.markdown(
        '<div style="display:grid;grid-template-columns:.95fr 1.15fr .85fr .9fr .9fr .9fr .85fr .9fr .9fr;gap:.4rem;'
        'padding:.5rem .7rem;font-size:.56rem;font-weight:700;letter-spacing:.03em;text-transform:uppercase;'
        'color:var(--text-dim);border-bottom:1.5px solid var(--border)">'
        '<span>Ημ. Επιταγής</span><span>Περίοδος</span><span style="text-align:right">Ποσό</span>'
        '<span style="text-align:right">Πωλ. Περιόδου</span><span style="text-align:right">Πέρσι Τιμολ.</span>'
        '<span style="text-align:right">Πέρσι Πωλ.</span><span>Αρ. Επιταγής</span>'
        '<span>Έξοδα Μήνα</span><span style="text-align:right">Διαφορά</span>'
        '</div>',
        unsafe_allow_html=True
    )

    _sum_amount = 0.0
    _sum_sales = 0.0
    _sum_expenses = 0.0
    _sum_diff = 0.0

    for _idx, _trow in _month_df.iterrows():
        _cd = _trow["check_date"]
        _cd_date = _cd.date() if hasattr(_cd, "date") else _cd
        _period = _trow.get("period", "")
        _amount = _trow["amount"]
        _row_num = int(_trow["_row"]) if "_row" in _trow and pd.notna(_trow["_row"]) else None
        _chk_num = _trow.get("check_number", "") if "check_number" in _trow else ""
        _exp_val = _trow.get("expenses", "") if "expenses" in _trow else ""

        # Πωλήσεις περιόδου = 7 μέρες πριν την ημ. επιταγής
        _pe = _cd_date - timedelta(days=1)
        _ps = _cd_date - timedelta(days=7)
        _sales_period = _sales_range_m(_ps, _pe)

        # Πέρσι: επιταγή 364 μέρες πριν
        _ly_cd = _cd_date - timedelta(days=364)
        _ly_amount = None
        _ly_window = df_t[df_t["check_date"].apply(lambda x: abs(((x.date() if hasattr(x,"date") else x) - _ly_cd).days) <= 3)]
        if not _ly_window.empty:
            _ly_amount = _ly_window.iloc[0]["amount"]
        # Πέρσι πωλήσεις = 7 μέρες πριν την περσινή επιταγή
        _ly_pe = _ly_cd - timedelta(days=1)
        _ly_ps = _ly_cd - timedelta(days=7)
        _ly_sales = _sales_range_m(_ly_ps, _ly_pe)

        # Έξοδα (parse)
        try:
            _exp_num = float(str(_exp_val).replace("€", "").replace(",", ".").strip()) if _exp_val else 0.0
        except Exception:
            _exp_num = 0.0

        # Διαφορά = Πωλήσεις περιόδου − Ποσό − Έξοδα
        _diff = None
        if _sales_period is not None:
            _diff = _sales_period - _amount - _exp_num
        _diff_color = "#1aa260" if (_diff is not None and _diff >= 0) else "#E2231A"

        # Αθροίσματα
        _sum_amount += _amount
        if _sales_period is not None: _sum_sales += _sales_period
        _sum_expenses += _exp_num
        if _diff is not None: _sum_diff += _diff

        _c1, _c2, _c3, _c4, _c5, _c6, _c7, _c8, _c9 = st.columns([.95, 1.15, .85, .9, .9, .9, .85, .9, .9])
        with _c1:
            st.markdown(f'<div style="padding-top:.5rem;font-weight:600;font-size:.76rem">{_cd_date.strftime("%d/%m/%Y")}</div>', unsafe_allow_html=True)
        with _c2:
            st.markdown(f'<div style="padding-top:.5rem;font-size:.72rem;color:var(--text-mut)">{_period or "—"}</div>', unsafe_allow_html=True)
        with _c3:
            st.markdown(f'<div style="padding-top:.5rem;text-align:right;font-weight:700;font-size:.76rem">{fmt(_amount)}</div>', unsafe_allow_html=True)
        with _c4:
            _sp_txt = fmt(_sales_period) if _sales_period is not None else "—"
            st.markdown(f'<div style="padding-top:.5rem;text-align:right;font-weight:700;color:var(--brand);font-size:.76rem">{_sp_txt}</div>', unsafe_allow_html=True)
        with _c5:
            _ly_txt = fmt(_ly_amount) if _ly_amount is not None else "—"
            st.markdown(f'<div style="padding-top:.5rem;text-align:right;color:var(--violet);font-size:.76rem">{_ly_txt}</div>', unsafe_allow_html=True)
        with _c6:
            _lys_txt = fmt(_ly_sales) if _ly_sales is not None else "—"
            st.markdown(f'<div style="padding-top:.5rem;text-align:right;color:#0ea5e9;font-size:.76rem">{_lys_txt}</div>', unsafe_allow_html=True)
        with _c7:
            _new_chk = st.text_input("αρ", value=_chk_num, key=f"mchk_{_row_num}_{_idx}", label_visibility="collapsed", placeholder="—")
            if _new_chk != _chk_num and _row_num:
                _ok, _msg = update_timologiseis_check_number(_row_num, _new_chk)
                if _ok:
                    load_timologiseis.clear(); st.rerun()
        with _c8:
            _new_exp = st.text_input("εξ", value=_exp_val, key=f"mexp_{_row_num}_{_idx}", label_visibility="collapsed", placeholder="0")
            if _new_exp != _exp_val and _row_num:
                _ok, _msg = update_timologiseis_expenses(_row_num, _new_exp)
                if _ok:
                    load_timologiseis.clear(); st.rerun()
        with _c9:
            _diff_txt = fmt(_diff) if _diff is not None else "—"
            st.markdown(f'<div style="padding-top:.5rem;text-align:right;font-weight:700;color:{_diff_color};font-size:.76rem">{_diff_txt}</div>', unsafe_allow_html=True)

    # Σύνολα μήνα
    _tot_color = "#1aa260" if _sum_diff >= 0 else "#E2231A"
    st.markdown(
        '<div style="display:grid;grid-template-columns:.95fr 1.15fr .85fr .9fr .9fr .9fr .85fr .9fr .9fr;gap:.4rem;'
        'padding:.8rem .7rem;margin-top:.5rem;border-top:2px solid var(--brand);font-weight:800;font-size:.8rem">'
        '<span>ΣΥΝΟΛΟ</span><span></span>'
        f'<span style="text-align:right">{fmt(_sum_amount)}</span>'
        f'<span style="text-align:right;color:var(--brand)">{fmt(_sum_sales)}</span>'
        '<span></span><span></span><span></span>'
        f'<span style="text-align:right">{fmt(_sum_expenses)}</span>'
        f'<span style="text-align:right;color:{_tot_color}">{fmt(_sum_diff)}</span>'
        '</div>',
        unsafe_allow_html=True
    )

# ══════════════════════════════════════════════════════════════════════════════
# ΔΙΑΚΡΙΤΙΚΗ ΕΝΗΜΕΡΩΣΗ (όχι στην κεφαλίδα) — κάτω από το περιεχόμενο
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)
with st.expander("⟳ Χειροκίνητη ενημέρωση δεδομένων"):
    st.caption("Τα Παραστατικά & οι Τιμολογήσεις ενημερώνονται αυτόματα κάθε 2 ώρες. "
               "Οι Πωλήσεις ενημερώνονται αυτόματα κάθε μισή ώρα από τις 21:30 ως τις 02:00. "
               "Πατήστε εδώ μόνο αν θέλετε άμεση ενημέρωση τώρα.")
    _ec1, _ec2, _ec3 = st.columns(3)
    with _ec1:
        if st.button("Ενημέρωση Πωλήσεων", key="manual_sales", use_container_width=True):
            if SALES_PW:
                with st.spinner("Σύνδεση & ανάγνωση (OCR)..."):
                    _ex = _raw_load_sales()
                    if _ex is not None and not _ex.empty:
                        _maxd = max(_ex["date"])
                        _maxd = _maxd.date() if hasattr(_maxd, "date") else _maxd
                        _since = _maxd - timedelta(days=4)
                    else:
                        _since = None
                    _recs, _errs_s, _n = fetch_sales_emails(SALES_PW, since=_since, want_records=60, email_scan_limit=120)
                if _errs_s:
                    st.markdown(f'<div class="alert alert-error">❌ {_errs_s[0]}</div>', unsafe_allow_html=True)
                else:
                    _saved_s = merge_sales(_recs) if _recs else 0
                    _raw_load_sales.clear()
                    if _saved_s:
                        st.markdown(f'<div class="alert alert-success">✅ {_saved_s} νέες ημέρες από {_n} email.</div>', unsafe_allow_html=True)
                        st.rerun()
                    else:
                        st.markdown('<div class="alert alert-info">ℹ️ Καμία νέα εγγραφή. (Το OCR τρέχει πλήρως κάθε βράδυ 23:00.)</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="alert alert-error">❌ Λείπει το SALES_EMAIL_PASS.</div>', unsafe_allow_html=True)
    with _ec2:
        if st.button("Ενημέρωση Παραστατικών", key="manual_inv", use_container_width=True):
            if INV_PW:
                with st.spinner("Σύνδεση & αποθήκευση..."):
                    _saved, _errs, _total = fetch_and_store_invoices(INV_PW, limit=60)
                if _errs:
                    st.markdown(f'<div class="alert alert-error">❌ {_errs[0]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="alert alert-success">✅ {_total} εγγραφές — {_saved} νέες.</div>', unsafe_allow_html=True)
                    _raw_load_invoices.clear(); st.rerun()
            else:
                st.markdown('<div class="alert alert-error">❌ Λείπει το EMAIL_PASS.</div>', unsafe_allow_html=True)
    with _ec3:
        if st.button("Ενημέρωση Τιμολογήσεων", key="manual_timol", use_container_width=True):
            if SALES_PW:
                with st.spinner("Σύνδεση & ανάγνωση..."):
                    _saved_t, _errs_t, _total_t = fetch_and_store_timologiseis(SALES_PW, limit=200)
                if _errs_t:
                    st.markdown(f'<div class="alert alert-error">❌ {_errs_t[0]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="alert alert-success">✅ {_total_t} βρέθηκαν — {_saved_t} νέες.</div>', unsafe_allow_html=True)
                    load_timologiseis.clear(); st.rerun()
            else:
                st.markdown('<div class="alert alert-error">❌ Λείπει το SALES_EMAIL_PASS.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# MOBILE BOTTOM NAVIGATION — πραγματικά links (?page=) που δουλεύουν σε iframe
# ══════════════════════════════════════════════════════════════════════════════
_botnav_items = ""
for p in PAGES:
    _active = "#10b981" if p == page else "#8696b5"
    import urllib.parse as _u
    _href = "?page=" + _u.quote(p)
    _botnav_items += (
        f'<a href="{_href}" target="_self" style="flex:1;text-decoration:none;display:flex;'
        f'flex-direction:column;align-items:center;gap:3px;padding:7px 0;color:{_active}">'
        f'<span style="font-size:1.2rem;line-height:1">{PAGE_ICONS[p]}</span>'
        f'<span style="font-size:.62rem;font-weight:600">{p}</span></a>'
    )

_botnav = (
    '<div class="mobile-only" style="position:fixed;bottom:0;left:0;right:0;z-index:99999;'
    'background:rgba(11,18,32,.97);backdrop-filter:blur(16px);border-top:1px solid var(--border);'
    'display:flex;padding:2px 4px">' + _botnav_items + '</div>'
)
st.markdown(_botnav, unsafe_allow_html=True)

# Κρύψε το Streamlit status widget (κόκκινη μπαλίτσα + στρογγυλό κάτω δεξιά) σε κινητό
st.markdown("""
<style>
@media (max-width: 820px) {
    [data-testid="stStatusWidget"], [data-testid="stToolbar"],
    [data-testid="manage-app-button"], .stDeployButton,
    iframe[title="streamlit_status"] { display: none !important; visibility: hidden !important; }
    div[data-testid="stStatusWidget"] { display:none !important; }
}
</style>
""", unsafe_allow_html=True)
