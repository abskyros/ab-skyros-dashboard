"""
app.py — ΑΒ Σκύρος Dashboard
ΕΚΔΟΣΗ: v3.1 — AB Vasilopoulos branding · date-fix · today/week comparison
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
    load_timologiseis, merge_timologiseis,
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
.stApp { background: radial-gradient(ellipse 130% 90% at 50% -15%, #e3f0fb 0%, var(--bg) 55%) !important; }
#MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }
.block-container { padding: 1.75rem 2.25rem 6rem !important; max-width: 1240px !important; }
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

/* collapse button */
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] {
    background: var(--brand) !important; border-radius: 0 12px 12px 0 !important;
    width: 30px !important; height: 60px !important; box-shadow: 3px 0 16px var(--brand-glow) !important;
}
[data-testid="collapsedControl"] svg, [data-testid="stSidebarCollapsedControl"] svg { fill: #fff !important; color: #fff !important; }
[data-testid="stSidebarCollapseButton"] button { background: var(--bg-hover) !important; border-radius: 8px !important; }
[data-testid="stSidebarCollapseButton"] svg { fill: var(--brand) !important; }

/* ═══════════════ PAGE HEADER ═══════════════ */
.page-header {
    display: flex; align-items: center; gap: 1rem;
    margin-bottom: 1.75rem; padding-bottom: 1.25rem; border-bottom: 1px solid var(--border-soft);
}
.page-header .icon {
    width: 50px; height: 50px; border-radius: 14px; display: flex; align-items: center; justify-content: center;
    font-size: 1.5rem; color: #fff;
    background: linear-gradient(135deg, var(--brand), var(--brand-2));
    box-shadow: 0 6px 20px var(--brand-glow);
}
.page-header h1 {
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.55rem; font-weight: 800;
    letter-spacing: -.02em; color: var(--text); margin: 0; line-height: 1.1;
}
.page-header .sub { font-size: .8rem; color: var(--text-mut); margin-top: .2rem; }

/* ═══════════════ SECTION LABEL ═══════════════ */
.section-label {
    font-size: .68rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
    color: var(--text-dim); margin: 1.75rem 0 .85rem; display: flex; align-items: center; gap: .65rem;
}
.section-label::after { content: ''; flex: 1; height: 1px; background: var(--border-soft); }

/* ═══════════════ KPI CARDS ═══════════════ */
.kpi-grid { display: grid; gap: 1.1rem; margin-bottom: 1.5rem; }
.kpi-2 { grid-template-columns: repeat(2, 1fr); }
.kpi-3 { grid-template-columns: repeat(3, 1fr); }
.kpi-4 { grid-template-columns: repeat(4, 1fr); }

.kpi-grid a { text-decoration: none !important; }
.kpi-card {
    position: relative; overflow: hidden;
    background: linear-gradient(160deg, #ffffff 0%, #f7fbff 100%);
    border: 1px solid var(--border); border-radius: 18px; padding: 1.4rem 1.5rem;
    transition: transform .18s cubic-bezier(.2,.8,.2,1), border-color .18s, box-shadow .18s;
    box-shadow: 0 4px 16px rgba(10,37,64,.05);
}
.kpi-card:hover {
    transform: translateY(-3px);
    border-color: color-mix(in srgb, var(--accent, var(--brand)) 55%, var(--border));
    box-shadow: 0 14px 32px rgba(10,37,64,.12);
}
.kpi-card::after {
    content: ''; position: absolute; inset: 0 0 auto 0; height: 4px;
    background: linear-gradient(90deg, var(--accent, var(--brand)), transparent 85%);
}
.kpi-card .glow {
    position: absolute; top: -40%; right: -20%; width: 160px; height: 160px; border-radius: 50%;
    background: var(--accent, var(--brand)); filter: blur(60px); opacity: .1; pointer-events: none;
}
.kpi-label {
    font-size: .64rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
    color: var(--text-mut); margin-bottom: .65rem; display: flex; align-items: center; gap: .4rem;
}
.kpi-value {
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.7rem; font-weight: 800;
    letter-spacing: -.02em; color: var(--text); line-height: 1;
}
.kpi-value.green  { color: var(--brand); }
.kpi-value.blue   { color: var(--sky); }
.kpi-value.red    { color: var(--red); }
.kpi-value.amber  { color: var(--amber); }
.kpi-value.violet { color: var(--violet); }
.kpi-sub { font-size: .72rem; color: var(--text-mut); margin-top: .5rem; }
.kpi-trend { font-size: .72rem; font-weight: 600; margin-top: .5rem; display: flex; align-items: center; gap: .3rem; }
.kpi-trend.up   { color: var(--green); }
.kpi-trend.down { color: var(--red); }
.kpi-trend.flat { color: var(--text-dim); }

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
    background: rgba(0,114,206,.08); border: 1px solid rgba(0,114,206,.25);
    border-radius: 10px; padding: .5rem .9rem; font-size: .76rem; font-weight: 600; color: var(--brand); margin-bottom: 1.25rem;
}

/* ═══════════════ ALERTS ═══════════════ */
.alert { border-radius: 12px; padding: .9rem 1.15rem; font-size: .78rem; font-weight: 500; margin: .75rem 0; display: flex; gap: .55rem; align-items: flex-start; }
.alert-success { background: rgba(26,162,96,.1); border: 1px solid rgba(26,162,96,.4); color: var(--green); }
.alert-warn    { background: rgba(232,146,12,.1); border: 1px solid rgba(232,146,12,.4); color: var(--amber); }
.alert-error   { background: var(--red-soft); border: 1px solid rgba(226,35,26,.4); color: var(--red); }
.alert-info    { background: rgba(0,114,206,.08); border: 1px solid rgba(0,114,206,.3); color: var(--brand); }

/* ═══════════════ TABLE ═══════════════ */
[data-testid="stDataFrame"] { border: 1px solid var(--border) !important; border-radius: 14px !important; overflow: hidden !important; box-shadow: 0 4px 14px rgba(10,37,64,.05) !important; }
[data-testid="stDataFrame"] th { background: #eef6fd !important; color: var(--text-mut) !important; font-size: .64rem !important; letter-spacing: .08em !important; text-transform: uppercase !important; font-weight: 700 !important; }
[data-testid="stDataFrame"] td { background: #ffffff !important; color: var(--text) !important; font-size: .82rem !important; border-color: var(--border-soft) !important; }

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
[data-baseweb="tab-list"] { background: transparent !important; border-bottom: 1px solid var(--border-soft) !important; gap: .25rem !important; }
[data-baseweb="tab"] { background: transparent !important; border: none !important; color: var(--text-mut) !important; font-size: .8rem !important; font-weight: 600 !important; padding: .65rem 1.1rem !important; }
[aria-selected="true"][data-baseweb="tab"] { color: var(--brand) !important; border-bottom: 2px solid var(--brand) !important; }

/* ═══════════════ INPUTS ═══════════════ */
.stDateInput > div > div > input, .stSelectbox > div > div, .stTextInput > div > div > input {
    background: #ffffff !important; border: 1px solid var(--border) !important; border-radius: 10px !important;
    color: var(--text) !important; font-family: 'Inter', sans-serif !important; font-size: .85rem !important;
}
label { color: var(--text-mut) !important; font-size: .76rem !important; font-weight: 600 !important; }

/* ═══════════════ EXPANDER (manual update) ═══════════════ */
[data-testid="stExpander"] { border: 1px solid var(--border) !important; border-radius: 12px !important; background: #ffffff !important; }
[data-testid="stExpander"] summary { color: var(--text-mut) !important; font-size: .82rem !important; font-weight: 600 !important; }

/* ═══════════════ PROGRESS CARD ═══════════════ */
.prog-card { background: #ffffff; border: 1px solid var(--border); border-radius: 14px; padding: 1.2rem 1.4rem; margin: .75rem 0; }
.prog-title { font-size: .88rem; font-weight: 700; color: var(--text); margin-bottom: .4rem; }
.prog-sub { font-size: .72rem; color: var(--text-mut); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

hr { border-color: var(--border-soft) !important; margin: 1.5rem 0 !important; }

/* ═══════════════ YEAR ROW (timologiseis) ═══════════════ */
.year-row {
    display: flex; align-items: center; justify-content: space-between;
    background: #ffffff; border: 1px solid var(--border); border-radius: 14px; padding: 1rem 1.4rem; margin-bottom: .7rem;
    transition: border-color .15s, transform .15s; box-shadow: 0 3px 12px rgba(10,37,64,.04);
}
.year-row:hover { border-color: var(--brand); transform: translateX(3px); }
.year-row .yr { font-family: 'Plus Jakarta Sans'; font-size: 1.1rem; font-weight: 800; color: var(--text); }
.year-row .amt { font-family: 'Plus Jakarta Sans'; font-size: 1.25rem; font-weight: 800; color: var(--brand); font-variant-numeric: tabular-nums; }
.year-row .cnt { font-size: .72rem; color: var(--text-mut); }

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
PAGES = ["Επισκόπηση", "Πωλήσεις", "Παραστατικά", "Τιμολογήσεις"]
PAGE_ICONS = {"Επισκόπηση": "◆", "Πωλήσεις": "▲", "Παραστατικά": "▤", "Τιμολογήσεις": "✦"}

# Διάβασε τρέχουσα σελίδα από το URL (?page=...) — δουλεύει σε desktop & mobile
_qp_page = st.query_params.get("page", "Επισκόπηση")
if _qp_page not in PAGES:
    _qp_page = "Επισκόπηση"
if "active_page" not in st.session_state:
    st.session_state["active_page"] = _qp_page
if _qp_page != st.session_state["active_page"]:
    st.session_state["active_page"] = _qp_page

with st.sidebar:
    st.markdown("""
<div style="padding:.5rem 0 1.25rem">
<div style="display:flex;align-items:center;gap:.8rem">
<div style="background:linear-gradient(135deg,#0072CE,#005BA6);border-radius:13px;width:46px;height:46px;display:flex;align-items:center;justify-content:center;font-size:1.35rem;box-shadow:0 6px 18px rgba(0,114,206,.4)">🏪</div>
<div>
<div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:1.05rem;font-weight:800;color:var(--text);letter-spacing:-.01em">ΑΒ Σκύρος</div>
<div style="font-size:.66rem;color:var(--text-mut);letter-spacing:.04em">ΑΝΑΛΥΤΙΚΑ ΠΩΛΗΣΕΩΝ</div>
</div>
</div>
</div>
""", unsafe_allow_html=True)

    st.markdown('<div style="font-size:.62rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--text-dim);margin:.4rem 0 .5rem">Μενού</div>', unsafe_allow_html=True)

    _page_labels = [f"{PAGE_ICONS[p]}  {p}" for p in PAGES]
    _sel = st.radio("Σελίδα", _page_labels, label_visibility="collapsed",
                    index=PAGES.index(st.session_state["active_page"]))
    _sel_page = PAGES[_page_labels.index(_sel)]
    if _sel_page != st.session_state["active_page"]:
        st.session_state["active_page"] = _sel_page
        st.query_params["page"] = _sel_page
        st.rerun()
    page = st.session_state["active_page"]

today = date.today()

# ══════════════════════════════════════════════════════════════════════════════
# AUTO-UPDATE — Παραστατικά & Τιμολογήσεις σε κάθε είσοδο (background thread)
# Οι Πωλήσεις ενημερώνονται αυτόματα κάθε βράδυ 23:00 μέσω GitHub Actions.
# ══════════════════════════════════════════════════════════════════════════════
import threading

def _background_auto_update():
    try:
        if INV_PW:
            fetch_and_store_invoices(INV_PW, limit=40)
            _raw_load_invoices.clear()
    except Exception:
        pass
    try:
        if SALES_PW:
            fetch_and_store_timologiseis(SALES_PW, limit=120)
            load_timologiseis.clear()
    except Exception:
        pass

if "auto_updated" not in st.session_state:
    st.session_state["auto_updated"] = True
    threading.Thread(target=_background_auto_update, daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΕΠΙΣΚΟΠΗΣΗ (Overview) — 3 κάρτες, χωρίς γραφήματα
# ══════════════════════════════════════════════════════════════════════════════
if page == "Επισκόπηση":
    st.markdown("""
<div class="page-header">
<div class="icon">◆</div>
<div><h1>Επισκόπηση</h1><div class="sub">Συνοπτική εικόνα τρέχουσας εβδομάδας</div></div>
</div>
""", unsafe_allow_html=True)

    df_s = load_sales()
    df_i = load_invoices()
    df_t = load_timologiseis()

    # Επιλογή εβδομάδας: τρέχουσα αν έχει δεδομένα, αλλιώς η τελευταία με δεδομένα
    sw_cur, ew_cur   = get_week_range(today)
    psw_cur, pew_cur = prev_week_range(sw_cur)
    if not df_s.empty:
        _has_cur = not df_s[(df_s["date"] >= pd.Timestamp(sw_cur)) & (df_s["date"] <= pd.Timestamp(ew_cur))].empty
        if _has_cur:
            sw, ew, psw, pew = sw_cur, ew_cur, psw_cur, pew_cur
            _wlabel = "Τρέχουσα εβδομάδα"
        else:
            sw, ew = psw_cur, pew_cur
            psw, pew = prev_week_range(sw)
            _wlabel = "Τελευταία εβδομάδα με δεδομένα"
    else:
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
    ly_same_date = today.replace(year=today.year - 1)
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

    import urllib.parse as _u
    _lnk_sales = "?page=" + _u.quote("Πωλήσεις")
    _lnk_inv   = "?page=" + _u.quote("Παραστατικά")

    # Περιεχόμενο κάρτας Πωλήσεων (Α: σήμερα vs πέρσι ίδια μέρα, Β: εβδομάδα ως τώρα vs ανάλογες περσινές)
    _today_val = fmt(today_sales) if today_sales is not None else "—"
    _today_block = (
        f'<div class="kpi-value green">{_today_val}</div>'
        f'<div class="kpi-sub" style="margin-top:.55rem">'
        f'<b style="color:var(--text)">{today_dow} {today.strftime("%d/%m")}</b> σήμερα'
        f'</div>'
        f'<div class="kpi-sub" style="margin-top:.2rem">'
        f'Πέρσι {ly_dow} {ly_same_date.strftime("%d/%m")}: '
        f'{fmt(ly_day_sales) if ly_day_sales is not None else "—"} {_pct_html(today_sales or 0, ly_day_sales)}'
        f'</div>'
    )
    _week_block = (
        f'<div style="margin-top:.85rem;padding-top:.7rem;border-top:1px solid var(--border-soft)">'
        f'<div class="kpi-sub" style="font-weight:700;color:var(--text)">Εβδομάδα ως τώρα ({_wtd_label})</div>'
        f'<div class="kpi-value green" style="font-size:1.15rem;margin-top:.25rem">{fmt(wtd_sum)}</div>'
        f'<div class="kpi-sub" style="margin-top:.2rem">'
        f'Πέρσι ίδιες μέρες: {fmt(ly_wtd_sum) if ly_wtd_sum is not None else "—"} {_pct_html(wtd_sum, ly_wtd_sum)}'
        f'</div></div>'
    )

    _ov_cards = (
        '<div class="kpi-grid kpi-3">'
        f'<a href="{_lnk_sales}" target="_self" style="text-decoration:none">'
        '<div class="kpi-card" style="--accent:#0072CE"><div class="glow"></div>'
        '<div class="kpi-label">Καθαρές Πωλήσεις →</div>'
        f'{_today_block}{_week_block}</div></a>'
        f'<a href="{_lnk_inv}" target="_self" style="text-decoration:none">'
        '<div class="kpi-card" style="--accent:#0072CE"><div class="glow"></div>'
        '<div class="kpi-label">Τιμολόγια (καθαρό) →</div>'
        f'<div class="kpi-value green">{fmt(inv_net_ov)}</div>'
        '<div class="kpi-sub">Σύνολο εβδομάδας</div></div></a>'
        f'{check_html}'
        '</div>'
    )
    st.markdown(_ov_cards, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΠΩΛΗΣΕΙΣ — χωρίς γραφήματα, χωρίς βαθιά σάρωση
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Πωλήσεις":
    st.markdown("""
<div class="page-header">
<div class="icon">▲</div>
<div><h1>Πωλήσεις</h1><div class="sub">Εβδομαδιαία & μηνιαία ανάλυση</div></div>
</div>
""", unsafe_allow_html=True)

    df_s = load_sales()
    if df_s.empty:
        st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα πωλήσεων ακόμη.</div>', unsafe_allow_html=True)
        st.stop()

    t_wk, t_mo = st.tabs(["Εβδομαδιαία", "Μηνιαία"])

    with t_wk:
        sel_s = st.date_input("Επίλεξε ημέρα", today, key="sales_wk_date")
        sw, ew = get_week_range(sel_s); psw, pew = prev_week_range(sw)
        st.markdown(f'<div class="date-badge">🗓 Δευτ. {sw.strftime("%d/%m/%Y")} — Κυρ. {ew.strftime("%d/%m/%Y")}</div>', unsafe_allow_html=True)
        w_df  = df_s[(df_s["date"] >= pd.Timestamp(sw))  & (df_s["date"] <= pd.Timestamp(ew))]
        pw_df = df_s[(df_s["date"] >= pd.Timestamp(psw)) & (df_s["date"] <= pd.Timestamp(pew))]
        if not w_df.empty:
            tot = w_df["net_sales"].sum(); cst = w_df["customers"].sum(); avg = w_df["avg_basket"].mean()
            p_tot = pw_df["net_sales"].sum() if not pw_df.empty else None
            p_cst = pw_df["customers"].sum() if not pw_df.empty else None
            p_avg = pw_df["avg_basket"].mean() if not pw_df.empty else None
            st.markdown(f"""
<div class="kpi-grid kpi-3">
<div class="kpi-card" style="--accent:#10b981"><div class="glow"></div>
<div class="kpi-label">Καθαρές Πωλήσεις</div>
<div class="kpi-value green">{fmt(tot)}</div>{trend_html(tot, p_tot)}</div>
<div class="kpi-card" style="--accent:#3b82f6"><div class="glow"></div>
<div class="kpi-label">Πελάτες</div>
<div class="kpi-value blue">{fmt_int(cst)}</div>{trend_html(cst, p_cst, unit="")}</div>
<div class="kpi-card" style="--accent:#8b5cf6"><div class="glow"></div>
<div class="kpi-label">ΜΟ Καλαθιού</div>
<div class="kpi-value violet">{fmt(avg)}</div>{trend_html(avg, p_avg)}</div>
</div>
""", unsafe_allow_html=True)
            st.markdown('<div class="section-label">Αναλυτικά ανά ημέρα</div>', unsafe_allow_html=True)
            disp = w_df.copy(); disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
            disp = disp.sort_values("date", ascending=False)
            st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).style.format({
                "ΠΩΛΗΣΕΙΣ": lambda v: fmt(v), "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—",
                "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—"}),
                use_container_width=True, hide_index=True)
        else:
            st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

    with t_mo:
        _ca, _cb = st.columns(2)
        with _ca:
            sm = st.selectbox("Μήνας", range(1,13), format_func=lambda x: MONTHS_GR[x-1], index=today.month-1, key="sales_mo_sel")
        with _cb:
            _yrs = sorted({r.year for r in df_s["date"]}, reverse=True)
            sy = st.selectbox("Έτος", _yrs, key="sales_yr_sel")
        st.markdown(f'<div class="date-badge">🗓 {MONTHS_GR[sm-1]} {sy}</div>', unsafe_allow_html=True)
        m_df = df_s[(df_s["date"].apply(lambda d: d.month) == sm) & (df_s["date"].apply(lambda d: d.year) == sy)]
        pm = sm-1 if sm>1 else 12; py = sy if sm>1 else sy-1
        pm_df = df_s[(df_s["date"].apply(lambda d: d.month) == pm) & (df_s["date"].apply(lambda d: d.year) == py)]
        if not m_df.empty:
            tot = m_df["net_sales"].sum(); avg = m_df["net_sales"].mean(); best = m_df["net_sales"].max()
            cst = m_df["customers"].sum() if "customers" in m_df.columns else None
            p_tot = pm_df["net_sales"].sum() if not pm_df.empty else None
            st.markdown(f"""
<div class="kpi-grid kpi-4">
<div class="kpi-card" style="--accent:#10b981"><div class="glow"></div>
<div class="kpi-label">Σύνολο Μήνα</div><div class="kpi-value green">{fmt(tot)}</div>{trend_html(tot, p_tot)}</div>
<div class="kpi-card" style="--accent:#3b82f6"><div class="glow"></div>
<div class="kpi-label">Ημερήσιος ΜΟ</div><div class="kpi-value blue">{fmt(avg)}</div></div>
<div class="kpi-card" style="--accent:#f59e0b"><div class="glow"></div>
<div class="kpi-label">Καλύτερη Ημέρα</div><div class="kpi-value amber">{fmt(best)}</div></div>
<div class="kpi-card" style="--accent:#8b5cf6"><div class="glow"></div>
<div class="kpi-label">Πελάτες (σύνολο)</div><div class="kpi-value violet">{fmt_int(cst) if cst else '—'}</div></div>
</div>
""", unsafe_allow_html=True)
            st.markdown('<div class="section-label">Αναλυτικά ανά ημέρα</div>', unsafe_allow_html=True)
            disp = m_df.copy(); disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
            disp = disp.sort_values("date", ascending=False)
            st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).style.format({
                "ΠΩΛΗΣΕΙΣ": lambda v: fmt(v), "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—",
                "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—"}),
                use_container_width=True, hide_index=True)
            _csv = m_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).to_csv(index=False).encode("utf-8-sig")
            st.download_button(f"↓ Λήψη CSV — {MONTHS_GR[sm-1]} {sy}", _csv, f"sales_{sy}_{sm:02d}.csv", "text/csv", key="sales_dl")
        else:
            st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτόν τον μήνα.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΠΑΡΑΣΤΑΤΙΚΑ — χωρίς πίτα
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Παραστατικά":
    st.markdown("""
<div class="page-header">
<div class="icon">▤</div>
<div><h1>Παραστατικά</h1><div class="sub">Τιμολόγια & πιστωτικά</div></div>
</div>
""", unsafe_allow_html=True)

    df_inv = load_invoices()
    t_wk, t_mo = st.tabs(["Εβδομαδιαία", "Μηνιαία"])

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

    with t_mo:
        if df_inv.empty:
            st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα.</div>', unsafe_allow_html=True)
        else:
            _ia, _ib = st.columns(2)
            with _ia:
                sm = st.selectbox("Μήνας", range(1,13), format_func=lambda x: MONTHS_GR[x-1], index=today.month-1, key="inv_mo_sel")
            with _ib:
                _yrs = sorted(df_inv["date"].dt.year.unique(), reverse=True)
                sy = st.selectbox("Έτος", _yrs, key="inv_yr_sel")
            st.markdown(f'<div class="date-badge">🗓 {MONTHS_GR[sm-1]} {sy}</div>', unsafe_allow_html=True)
            m_df = df_inv[(df_inv["date"].dt.month == sm) & (df_inv["date"].dt.year == sy)]
            if not m_df.empty:
                inv_m = m_df[~m_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                crd_m = m_df[m_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                st.markdown(f"""
<div class="kpi-grid kpi-3">
<div class="kpi-card" style="--accent:#10b981"><div class="glow"></div>
<div class="kpi-label">Τιμολόγια</div><div class="kpi-value green">{fmt(inv_m)}</div></div>
<div class="kpi-card" style="--accent:#ef4444"><div class="glow"></div>
<div class="kpi-label">Πιστωτικά</div><div class="kpi-value red">-{fmt(crd_m)}</div></div>
<div class="kpi-card" style="--accent:#3b82f6"><div class="glow"></div>
<div class="kpi-label">Σύνολο Μήνα</div><div class="kpi-value blue">{fmt(inv_m - crd_m)}</div></div>
</div>
""", unsafe_allow_html=True)
                st.markdown('<div class="section-label">Αναλυτικά</div>', unsafe_allow_html=True)
                disp = m_df.copy(); disp["date"] = disp["date"].dt.strftime("%d/%m/%Y")
                disp = disp.sort_values("date", ascending=False)
                st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).style.format({"ΑΞΙΑ": lambda v: fmt(v)}),
                    use_container_width=True, hide_index=True)
                _csv = m_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).to_csv(index=False).encode("utf-8-sig")
                st.download_button(f"↓ Λήψη {MONTHS_GR[sm-1]} {sy}", _csv, f"invoices_{sy}_{sm:02d}.csv", "text/csv", key="inv_dl")
            else:
                st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτόν τον μήνα.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΤΙΜΟΛΟΓΗΣΕΙΣ — σύνολο ανά έτος, χωρίς βαθιά σάρωση
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Τιμολογήσεις":
    st.markdown("""
<div class="page-header">
<div class="icon">✦</div>
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

        # Σύνολο ανά έτος
        st.markdown('<div class="section-label">Συνολικό ποσό ανά έτος</div>', unsafe_allow_html=True)
        df_t2 = df_t.copy()
        df_t2["year"] = df_t2["check_date"].dt.year
        by_year = df_t2.groupby("year").agg(total=("amount", "sum"), count=("amount", "size")).reset_index().sort_values("year", ascending=False)
        rows_html = ""
        for _, r in by_year.iterrows():
            rows_html += f"""
            <div class="year-row">
                <div><span class="yr">{int(r['year'])}</span> &nbsp;<span class="cnt">· {int(r['count'])} επιταγές</span></div>
                <span class="amt">{fmt(r['total'])}</span>
            </div>"""
        st.markdown(rows_html, unsafe_allow_html=True)

        # Αναλυτικός πίνακας
        st.markdown('<div class="section-label">Όλες οι τιμολογήσεις</div>', unsafe_allow_html=True)
        disp_t = df_t.copy()
        disp_t["check_date"] = disp_t["check_date"].dt.strftime("%d/%m/%Y")
        disp_t = disp_t.rename(columns={"check_date":"ΗΜΕΡ. ΕΠΙΤΑΓΗΣ","period":"ΠΕΡΙΟΔΟΣ","amount":"ΠΟΣΟ"})
        st.dataframe(disp_t.style.format({"ΠΟΣΟ": lambda v: fmt(v)}), use_container_width=True, hide_index=True)
        _csv = df_t.to_csv(index=False).encode("utf-8-sig")
        st.download_button("↓ Λήψη CSV", _csv, "timologiseis.csv", "text/csv", key="timol_dl")

# ══════════════════════════════════════════════════════════════════════════════
# ΔΙΑΚΡΙΤΙΚΗ ΕΝΗΜΕΡΩΣΗ (όχι στην κεφαλίδα) — κάτω από το περιεχόμενο
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)
with st.expander("⟳ Χειροκίνητη ενημέρωση δεδομένων"):
    st.caption("Τα Παραστατικά & οι Τιμολογήσεις ενημερώνονται αυτόματα σε κάθε είσοδο. "
               "Οι Πωλήσεις ενημερώνονται αυτόματα κάθε βράδυ στις 23:00. "
               "Πατήστε εδώ μόνο αν θέλετε άμεση ενημέρωση τώρα.")
    _ec1, _ec2, _ec3 = st.columns(3)
    with _ec1:
        if st.button("Ενημέρωση Πωλήσεων", key="manual_sales", use_container_width=True):
            if SALES_PW:
                with st.spinner("Σύνδεση & ανάγνωση (OCR)..."):
                    _ex = _raw_load_sales()
                    _since = (max(_ex["date"]) - timedelta(days=4)) if (_ex is not None and not _ex.empty) else None
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
