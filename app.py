"""
app.py — ΑΒ Σκύρος Dashboard v2
Dark mode · Professional UI · Plotly Charts · KPI Trends
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
SALES_SUBJECT_KW      = "ΑΒ ΣΚΥΡΟΣ"
BATCH_SIZE            = 25
DEEP_SCAN_YEARS       = 2

MONTHS_GR = [
    "Ιανουάριος","Φεβρουάριος","Μάρτιος","Απρίλιος",
    "Μάιος","Ιούνιος","Ιούλιος","Αύγουστος",
    "Σεπτέμβριος","Οκτώβριος","Νοέμβριος","Δεκέμβριος"
]

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ΑΒ Σκύρος",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DARK THEME CSS ────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Theme Variables ── */
:root {
    --bg-primary:    #0d1117;
    --bg-secondary:  #161b22;
    --bg-tertiary:   #21262d;
    --border:        #30363d;
    --text-primary:  #e6edf3;
    --text-muted:    #8b949e;
    --accent-green:  #238636;
    --accent-green2: #2ea043;
    --accent-green3: #3fb950;
}
body.light-mode, body.light-mode [class*="css"] {
    --bg-primary:    #ffffff;
    --bg-secondary:  #f6f8fa;
    --bg-tertiary:   #eaeef2;
    --border:        #d0d7de;
    --text-primary:  #1f2328;
    --text-muted:    #656d76;
    --accent-green:  #1a7f37;
    --accent-green2: #1f883d;
    --accent-green3: #2da44e;
}

/* ── Base ── */
*, *::before, *::after { box-sizing: border-box; }
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
    background: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}
.stApp { background: var(--bg-primary) !important; }
#MainMenu, footer, header { visibility: hidden !important; }
.block-container {
    padding: 2rem 2.5rem 4rem !important;
    max-width: 1280px !important;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] * { color: var(--text-primary) !important; }
section[data-testid="stSidebar"] .stSelectbox > div > div {
    background: var(--bg-tertiary) !important;
    border: 1px solid var(--border) !important;
}

/* ── Page header ── */
.page-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 2rem;
    padding-bottom: 1.25rem;
    border-bottom: 1px solid var(--border);
}
.page-header .icon {
    font-size: 2rem;
    background: linear-gradient(135deg, #238636, #2ea043);
    border-radius: 12px;
    width: 52px; height: 52px;
    display: flex; align-items: center; justify-content: center;
}
.page-header h1 {
    font-size: 1.5rem;
    font-weight: 700;
    color: #e6edf3;
    margin: 0;
}
.page-header .sub {
    font-size: .78rem;
    color: #8b949e;
    margin-top: .15rem;
}

/* ── Section label ── */
.section-label {
    font-size: .62rem;
    font-weight: 700;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin: 2rem 0 .75rem;
    display: flex;
    align-items: center;
    gap: .5rem;
}
.section-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
}

/* ── KPI Cards ── */
.kpi-grid { display: grid; gap: 1rem; margin-bottom: 1.5rem; }
.kpi-3 { grid-template-columns: repeat(3, 1fr); }
.kpi-4 { grid-template-columns: repeat(4, 1fr); }
@media(max-width:680px) { .kpi-3, .kpi-4 { grid-template-columns: 1fr 1fr; } }

.kpi-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 1.2rem 1.4rem;
    position: relative;
    overflow: hidden;
    transition: border-color .2s, transform .15s;
}
.kpi-card:hover { border-color: #30363d; transform: translateY(-1px); }
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent, #238636);
}
.kpi-label {
    font-size: .6rem;
    font-weight: 700;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: .5rem;
}
.kpi-value {
    font-size: 1.4rem;
    font-weight: 800;
    color: var(--text-primary);
    line-height: 1;
}
.kpi-value.green { color: #3fb950; }
.kpi-value.red   { color: #f85149; }
.kpi-value.blue  { color: #58a6ff; }
.kpi-value.purple{ color: #bc8cff; }
.kpi-trend {
    font-size: .68rem;
    font-weight: 600;
    margin-top: .45rem;
    display: flex;
    align-items: center;
    gap: .25rem;
}
.kpi-trend.up   { color: #3fb950; }
.kpi-trend.down { color: #f85149; }
.kpi-trend.flat { color: #8b949e; }

/* ── Date Range Badge ── */
.date-badge {
    display: inline-flex;
    align-items: center;
    gap: .5rem;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: .45rem .85rem;
    font-size: .75rem;
    font-weight: 600;
    color: #58a6ff;
    margin-bottom: 1.25rem;
}

/* ── Alerts ── */
.alert {
    border-radius: 10px;
    padding: .85rem 1.1rem;
    font-size: .75rem;
    font-weight: 500;
    margin: .75rem 0;
    display: flex;
    align-items: flex-start;
    gap: .5rem;
}
.alert-success { background: rgba(35,134,54,.12); border: 1px solid var(--accent-green); color: var(--accent-green3); }
.alert-warn    { background: rgba(210,153,34,.1); border: 1px solid #d29922; color: #e3b341; }
.alert-error   { background: rgba(218,54,51,.1); border: 1px solid #da3633; color: #f85149; }
.alert-info    { background: rgba(31,111,235,.1); border: 1px solid #1f6feb; color: #58a6ff; }

/* ── Table ── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}
[data-testid="stDataFrame"] th {
    background: var(--bg-secondary) !important;
    color: var(--text-muted) !important;
    font-size: .6rem !important;
    letter-spacing: .1em !important;
    text-transform: uppercase !important;
    font-weight: 700 !important;
}
[data-testid="stDataFrame"] td {
    background: var(--bg-primary) !important;
    color: var(--text-primary) !important;
    font-size: .8rem !important;
    border-color: var(--border) !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: .78rem !important;
    font-weight: 600 !important;
    padding: .55rem 1rem !important;
    border: 1px solid #30363d !important;
    background: var(--bg-tertiary) !important;
    color: var(--text-primary) !important;
    transition: all .15s !important;
}
.stButton > button:hover {
    background: var(--border) !important;
    border-color: #58a6ff !important;
}
.btn-primary > button {
    background: #238636 !important;
    border-color: #2ea043 !important;
    color: #fff !important;
}
.btn-primary > button:hover { background: #2ea043 !important; }
.btn-blue > button {
    background: #1f6feb !important;
    border-color: #388bfd !important;
    color: #fff !important;
}
.btn-danger > button {
    background: #da3633 !important;
    border-color: #f85149 !important;
    color: #fff !important;
}

/* ── Tabs ── */
[data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid var(--border) !important;
    gap: .1rem !important;
}
[data-baseweb="tab"] {
    background: transparent !important;
    border: none !important;
    color: var(--text-muted) !important;
    font-size: .72rem !important;
    font-weight: 600 !important;
    letter-spacing: .08em !important;
    text-transform: uppercase !important;
    padding: .6rem 1rem !important;
}
[aria-selected="true"][data-baseweb="tab"] {
    color: #58a6ff !important;
    border-bottom: 2px solid #58a6ff !important;
    background: transparent !important;
}

/* ── Inputs ── */
.stDateInput > div > div > input,
.stSelectbox > div > div,
.stTextInput > div > div > input {
    background: var(--bg-tertiary) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
    font-family: 'Inter', sans-serif !important;
    font-size: .82rem !important;
}
label { color: var(--text-muted) !important; font-size: .72rem !important; font-weight: 600 !important; }

/* ── Progress ── */
.prog-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
    margin: .75rem 0;
}
.prog-title { font-size: .85rem; font-weight: 700; color: var(--text-primary); margin-bottom: .4rem; }
.prog-sub   { font-size: .7rem; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ── Divider ── */
hr { border-color: var(--border) !important; margin: 1.5rem 0 !important; }

/* ════ SIDEBAR EXPAND BUTTON — αδύνατο να μην φαίνεται ════ */
/* Όλα τα πιθανά selectors για το κουμπί ανοίγματος */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"],
button[aria-label="Open sidebar"],
button[aria-label="expand"] {
    background: #ff4b4b !important;
    border-radius: 0 12px 12px 0 !important;
    width: 42px !important;
    min-width: 42px !important;
    height: 70px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    box-shadow: 3px 0 20px rgba(255,75,75,0.7) !important;
    opacity: 1 !important;
    visibility: visible !important;
    z-index: 999999 !important;
    position: fixed !important;
    top: 80px !important;
    left: 0 !important;
}
[data-testid="collapsedControl"] svg,
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="stExpandSidebarButton"] svg,
button[aria-label="Open sidebar"] svg {
    color: #ffffff !important;
    fill: #ffffff !important;
    width: 24px !important;
    height: 24px !important;
}
[data-testid="collapsedControl"] button,
[data-testid="stSidebarCollapsedControl"] button {
    background: transparent !important;
    border: none !important;
}
/* Κουμπί κλεισίματος (μέσα στη sidebar) */
[data-testid="stSidebarCollapseButton"] button {
    background: #ff4b4b !important;
    border-radius: 8px !important;
    color: white !important;
    border: none !important;
}
[data-testid="stSidebarCollapseButton"] svg {
    fill: white !important;
    color: white !important;
}

/* ── Sidebar nav items ── */
.nav-item {
    display: flex;
    align-items: center;
    gap: .75rem;
    padding: .65rem 1rem;
    border-radius: 8px;
    cursor: pointer;
    font-size: .82rem;
    font-weight: 500;
    color: #8b949e;
    margin: .15rem 0;
    transition: all .15s;
}
.nav-item:hover { background: #21262d; color: #e6edf3; }
.nav-item.active { background: rgba(35,134,54,.15); color: var(--accent-green3); font-weight: 600; }
.nav-icon { font-size: 1rem; width: 20px; text-align: center; }

/* ── Summary strip ── */
.summary-strip {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: .6rem;
    background: #0d2316;
    border: 1px solid #238636;
    border-radius: 10px;
    padding: .9rem 1rem;
    margin: 1rem 0;
}
.ss-item { font-size: .72rem; color: #8b949e; }
.ss-item span { display: block; font-size: .88rem; font-weight: 700; color: #3fb950; margin-top: .15rem; }

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
    return "#e6edf3" if st.session_state.get("theme", "dark") == "dark" else "#1f2328"

def _plot_layout():
    """Επιστρέφει layout ανάλογα με το theme (dark/light)."""
    _dark = st.session_state.get("theme", "dark") == "dark"
    if _dark:
        grid, line, txt, hover_bg, hover_txt = "#21262d", "#30363d", "#8b949e", "#161b22", "#e6edf3"
    else:
        grid, line, txt, hover_bg, hover_txt = "#d0d7de", "#d0d7de", "#656d76", "#ffffff", "#1f2328"
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color=txt, size=11),
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis=dict(gridcolor=grid, linecolor=line, tickcolor=line),
        yaxis=dict(gridcolor=grid, linecolor=line, tickcolor=line),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=line),
        hoverlabel=dict(bgcolor=hover_bg, bordercolor=line, font_color=hover_txt),
    )

# Backward compat: PLOT_LAYOUT ως property-like (αξιολογείται κάθε φορά)
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
# SIDEBAR NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    # Theme state
    if "theme" not in st.session_state:
        st.session_state["theme"] = "dark"

    _is_dark = st.session_state["theme"] == "dark"
    _theme_icon  = "☀️" if _is_dark else "🌙"
    _theme_label = "Ημέρα" if _is_dark else "Νύχτα"

    st.markdown(f"""
    <div style="padding:.5rem 0 1rem">
        <div style="display:flex;align-items:center;justify-content:space-between">
            <div style="display:flex;align-items:center;gap:.75rem">
                <div style="background:linear-gradient(135deg,#238636,#2ea043);border-radius:10px;
                            width:40px;height:40px;display:flex;align-items:center;
                            justify-content:center;font-size:1.2rem">🏢</div>
                <div>
                    <div style="font-size:.95rem;font-weight:700;color:var(--text-primary)">ΑΒ Σκύρος</div>
                    <div style="font-size:.65rem;color:var(--text-muted)">Dashboard v2</div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button(f"{_theme_icon} {_theme_label}", key="theme_toggle", use_container_width=True):
        st.session_state["theme"] = "light" if _is_dark else "dark"
        st.rerun()

    # Inject LIGHT theme — δυνατά selectors που πιάνουν τα πάντα
    _theme_css = "" if _is_dark else """
    <style>
    .stApp, .stApp > div, [data-testid="stAppViewContainer"],
    [data-testid="stMain"], .main, .block-container,
    section.main, [data-testid="stMainBlockContainer"] {
        background: #ffffff !important;
        background-color: #ffffff !important;
        color: #1f2328 !important;
    }
    [data-testid="stHeader"] { background: #ffffff !important; }
    section[data-testid="stSidebar"], section[data-testid="stSidebar"] > div {
        background: #f6f8fa !important;
        border-right: 1px solid #d0d7de !important;
    }
    section[data-testid="stSidebar"] * { color: #1f2328 !important; }
    .kpi-card { background: #f6f8fa !important; border-color: #d0d7de !important; }
    .kpi-value { color: #1f2328 !important; }
    .kpi-value.green { color: #1a7f37 !important; }
    .kpi-value.blue  { color: #0969da !important; }
    .kpi-value.red   { color: #cf222e !important; }
    .kpi-value.purple{ color: #8250df !important; }
    .kpi-label, .section-label, label { color: #656d76 !important; }
    .date-badge { background: #ddf4ff !important; border-color: #54aeff !important; color: #0969da !important; }
    .page-header { border-bottom-color: #d0d7de !important; }
    .page-header h1 { color: #1f2328 !important; }
    .page-header .sub { color: #656d76 !important; }
    .section-label::after { background: #d0d7de !important; }
    [data-baseweb="tab-list"] { border-bottom-color: #d0d7de !important; }
    [data-baseweb="tab"] { color: #656d76 !important; }
    [aria-selected="true"][data-baseweb="tab"] { color: #0969da !important; border-bottom-color: #0969da !important; }
    hr { border-color: #d0d7de !important; }
    .prog-card { background: #f6f8fa !important; border-color: #d0d7de !important; }
    .prog-title { color: #1f2328 !important; }
    .prog-sub { color: #656d76 !important; }
    [data-testid="stDataFrame"] th { background: #f6f8fa !important; color: #656d76 !important; }
    [data-testid="stDataFrame"] td { background: #ffffff !important; color: #1f2328 !important; border-color: #d0d7de !important; }
    [data-testid="stDataFrame"] { border-color: #d0d7de !important; }
    .stButton > button { background: #f6f8fa !important; color: #1f2328 !important; border-color: #d0d7de !important; }
    .stButton > button:hover { background: #eaeef2 !important; }
    .btn-primary > button { background: #1f883d !important; color: white !important; }
    .stDateInput > div > div > input, .stSelectbox > div > div, .stTextInput > div > div > input {
        background: #f6f8fa !important; border-color: #d0d7de !important; color: #1f2328 !important;
    }
    .stRadio label { color: #1f2328 !important; }
    </style>
    """
    if _theme_css:
        st.markdown(_theme_css, unsafe_allow_html=True)

    st.markdown('<div style="font-size:.6rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#8b949e;margin-bottom:.5rem">ΜΕΝΟΥ</div>', unsafe_allow_html=True)

    page = st.radio(
        "Σελίδα",
        ["🏢 Overview", "💼 Πωλήσεις", "📋 Παραστατικά"],
        label_visibility="collapsed",
    )

    st.markdown("<hr>", unsafe_allow_html=True)

    # ── Οδηγία για sidebar ──
    st.markdown("""
    <div style="font-size:.62rem;color:#484f58;text-align:center;padding:.5rem 0;line-height:1.6">
        Για να κλείσετε/ανοίξετε<br>το μενού χρησιμοποιήστε<br>
        το <b style="color:#8b949e">≡</b> στην επάνω αριστερά γωνία
    </div>
    """, unsafe_allow_html=True)

    # Live stats in sidebar
    df_s_sb  = load_sales()
    df_i_sb  = load_invoices()
    today_sb = date.today()

    if not df_s_sb.empty:
        latest = max(df_s_sb["date"])
        st.markdown(f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:.85rem 1rem">
            <div style="font-size:.58rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#8b949e;margin-bottom:.6rem">Τελευταία Ενημέρωση</div>
            <div style="font-size:.85rem;font-weight:700;color:#3fb950">{latest.strftime('%d/%m/%Y')}</div>
            <div style="font-size:.68rem;color:#8b949e;margin-top:.2rem">{len(df_s_sb)} εγγραφές στο σύνολο</div>
        </div>
        """, unsafe_allow_html=True)

today = date.today()

# ══════════════════════════════════════════════════════════════════════════════
# AUTO-UPDATE ON APP OPEN (τρέχει μία φορά ανά session)
# ══════════════════════════════════════════════════════════════════════════════
import threading

def _background_auto_update():
    """Background thread — δεν αγγίζει Streamlit state, δεν μπλοκάρει UI."""
    try:
        if SALES_PW:
            _ex = _raw_load_sales()
            _since = (max(_ex["date"]) - timedelta(days=3)) if (_ex is not None and not _ex.empty) else None
            _recs, _, _ = fetch_sales_emails(SALES_PW, since=_since, want_records=60, email_scan_limit=200)
            if _recs:
                merge_sales(_recs)
                _raw_load_sales.clear()
    except Exception:
        pass
    try:
        if INV_PW:
            fetch_and_store_invoices(INV_PW, limit=30)
            _raw_load_invoices.clear()
    except Exception:
        pass

if "auto_updated" not in st.session_state:
    st.session_state["auto_updated"] = True
    _t = threading.Thread(target=_background_auto_update, daemon=True)
    _t.start()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
if page == "🏢 Overview":
    st.markdown("""
    <div class="page-header">
        <div class="icon">🏢</div>
        <div><h1>Overview</h1><div class="sub">Γενική εικόνα · Τρέχουσα εβδομάδα</div></div>
    </div>
    """, unsafe_allow_html=True)

    df_s = load_sales()
    df_i = load_invoices()

    # Αν η τρέχουσα εβδομάδα δεν έχει δεδομένα → δείξε την προηγούμενη
    sw_cur, ew_cur   = get_week_range(today)
    psw_cur, pew_cur = prev_week_range(sw_cur)

    if not df_s.empty:
        _has_cur = not df_s[(df_s["date"] >= sw_cur) & (df_s["date"] <= ew_cur)].empty
        if _has_cur:
            sw, ew, psw, pew = sw_cur, ew_cur, psw_cur, pew_cur
            _label = "Τρέχουσα εβδομάδα"
        else:
            sw, ew = psw_cur, pew_cur
            psw, pew = prev_week_range(sw)
            _label = "Τελευταία εβδομάδα με δεδομένα"
    else:
        sw, ew, psw, pew = sw_cur, ew_cur, psw_cur, pew_cur
        _label = "Τρέχουσα εβδομάδα"

    st.markdown(f'<div class="date-badge">📅 {sw.strftime("%d/%m/%Y")} — {ew.strftime("%d/%m/%Y")} &nbsp;|&nbsp; {_label}</div>', unsafe_allow_html=True)

    # ── 2 KPI cards μόνο ──
    w_df  = df_s[(df_s["date"] >= sw)  & (df_s["date"] <= ew)]  if not df_s.empty else pd.DataFrame()
    pw_df = df_s[(df_s["date"] >= psw) & (df_s["date"] <= pew)] if not df_s.empty else pd.DataFrame()

    cur_sales  = w_df["net_sales"].sum()  if not w_df.empty else 0
    prev_sales = pw_df["net_sales"].sum() if not pw_df.empty else None

    # Παραστατικά εβδομάδας
    inv_net_ov = 0
    prev_inv_net_ov = None
    if not df_i.empty:
        mask_ov  = (df_i["date"] >= pd.Timestamp(sw))  & (df_i["date"] <= pd.Timestamp(ew)  + pd.Timedelta(hours=23, minutes=59))
        mask_pov = (df_i["date"] >= pd.Timestamp(psw)) & (df_i["date"] <= pd.Timestamp(pew) + pd.Timedelta(hours=23, minutes=59))
        wi_ov    = df_i.loc[mask_ov]
        pwi_ov   = df_i.loc[mask_pov]
        if not wi_ov.empty:
            _inv = wi_ov[~wi_ov["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
            _crd = wi_ov[wi_ov["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
            inv_net_ov = _inv - _crd
        if not pwi_ov.empty:
            _pinv = pwi_ov[~pwi_ov["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
            _pcrd = pwi_ov[pwi_ov["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
            prev_inv_net_ov = _pinv - _pcrd

    st.markdown(f"""
    <div class="kpi-grid kpi-3" style="max-width:700px">
        <div class="kpi-card" style="--accent:#3fb950">
            <div class="kpi-label">Καθαρές Πωλήσεις</div>
            <div class="kpi-value green">{fmt(cur_sales)}</div>
            {trend_html(cur_sales, prev_sales)}
        </div>
        <div class="kpi-card" style="--accent:#58a6ff">
            <div class="kpi-label">Τιμολόγια (καθαρό)</div>
            <div class="kpi-value blue">{fmt(inv_net_ov)}</div>
            {trend_html(inv_net_ov, prev_inv_net_ov)}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Combined chart: Πωλήσεις + Τιμολόγια ──
    if not w_df.empty or (not df_i.empty and not wi_ov.empty):
        fig_ov = go.Figure()
        if not w_df.empty:
            _s = w_df.sort_values("date")
            fig_ov.add_trace(go.Bar(
                x=_s["date"], y=_s["net_sales"],
                name="Πωλήσεις",
                marker_color="#3fb950",
                hovertemplate="<b>%{x}</b><br>Πωλήσεις: %{y:,.2f}€<extra></extra>",
            ))
        if not df_i.empty and not wi_ov.empty:
            # Ομαδοποίηση τιμολογίων ανά ημέρα
            _inv_day = wi_ov.copy()
            _inv_day["day"] = _inv_day["date"].dt.date
            _inv_grp = _inv_day.groupby("day")["value"].sum().reset_index()
            _inv_grp.columns = ["date", "value"]
            _inv_grp = _inv_grp.sort_values("date")
            fig_ov.add_trace(go.Bar(
                x=_inv_grp["date"], y=_inv_grp["value"],
                name="Τιμολόγια",
                marker_color="#58a6ff",
                hovertemplate="<b>%{x}</b><br>Τιμολόγια: %{y:,.2f}€<extra></extra>",
            ))
        fig_ov.update_layout(
            **_plot_layout(),
            barmode="group",
            title=dict(text="Πωλήσεις & Τιμολόγια — Τρέχουσα Εβδομάδα", font=dict(size=13, color=_title_color())),
            height=300,
        )
        st.plotly_chart(fig_ov, use_container_width=True, key="ov_combined_chart")
    else:
        st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΠΩΛΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
elif page == "💼 Πωλήσεις":
    st.markdown("""
    <div class="page-header">
        <div class="icon">💼</div>
        <div><h1>Πωλήσεις</h1><div class="sub">Εβδομαδιαία & Μηνιαία ανάλυση</div></div>
    </div>
    """, unsafe_allow_html=True)

    # ── Κουμπιά Ενημέρωσης ──
    _sc1, _sc2, _sc3 = st.columns([1.8, 2.0, 4])
    with _sc1:
        st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
        _s_inc = st.button("🔁 Ενημέρωση", key="sales_refresh", use_container_width=True)
        st.markdown('<div style="font-size:.62rem;color:#8b949e;margin-top:.2rem">Τελευταίες μέρες</div></div>', unsafe_allow_html=True)
    with _sc2:
        st.markdown('<div class="btn-danger">', unsafe_allow_html=True)
        _s_deep = st.button("🔍 Βαθιά Σάρωση 2 Χρόνων", key="sales_deep", use_container_width=True)
        st.markdown('<div style="font-size:.62rem;color:#8b949e;margin-top:.2rem">Πλήρες ιστορικό — αργό</div></div>', unsafe_allow_html=True)
    _s_status = st.empty()

    if _s_inc and SALES_PW:
        with st.spinner("Σύνδεση & ανάγνωση..."):
            _ex = _raw_load_sales()
            _since = (max(_ex["date"]) - timedelta(days=3)) if (_ex is not None and not _ex.empty) else None
            _recs, _errs, _n = fetch_sales_emails(SALES_PW, since=_since, want_records=60, email_scan_limit=200)
        if _errs:
            _s_status.markdown(f'<div class="alert alert-error">❌ {_errs[0]}</div>', unsafe_allow_html=True)
        else:
            _saved = merge_sales(_recs) if _recs else 0
            _raw_load_sales.clear()
            _s_status.markdown(f'<div class="alert alert-success">✅ {_saved} νέες εγγραφές από {_n} email.</div>', unsafe_allow_html=True)
            st.rerun()
    elif _s_inc and not SALES_PW:
        _s_status.markdown('<div class="alert alert-error">❌ Δεν βρέθηκε SALES_EMAIL_PASS.</div>', unsafe_allow_html=True)

    if _s_deep and SALES_PW:
        _s_status.markdown('<div class="alert alert-warn">⏳ Βαθιά Σάρωση — μην κλείσετε τη σελίδα...</div>', unsafe_allow_html=True)
        _pb = st.progress(0)
        _ib = st.empty()
        for _st_s in deep_scan_sales(SALES_PW):
            if _st_s["err"]:
                _ib.markdown(f'<div class="alert alert-error">❌ {_st_s["err"]}</div>', unsafe_allow_html=True)
                break
            if _st_s["phase"] == "connect":
                _ib.markdown('<div class="prog-card"><div class="prog-title">Σύνδεση...</div></div>', unsafe_allow_html=True)
            elif _st_s["phase"] == "listing":
                _ib.markdown('<div class="prog-card"><div class="prog-title">Ανάκτηση λίστας emails...</div></div>', unsafe_allow_html=True)
            elif _st_s["phase"] == "ocr":
                _tt = _st_s["total"]; _dd = _st_s["done"]
                _pct = int(_dd / _tt * 100) if _tt else 0
                _pb.progress(_pct)
                _ib.markdown(f'''<div class="prog-card">
                    <div class="prog-title">OCR: {_dd}/{_tt} ({_pct}%)</div>
                    <div class="prog-sub">Αποθηκεύτηκαν: {_st_s["saved"]} — {_st_s["cur"]}</div>
                </div>''', unsafe_allow_html=True)
            if _st_s["ok"]:
                _pb.progress(100)
                _ib.empty()
                _s_status.markdown(f'<div class="alert alert-success">✅ {_st_s["total"]} emails → {_st_s["saved"]} εγγραφές.</div>', unsafe_allow_html=True)
                _raw_load_sales.clear()
                st.rerun()
    elif _s_deep and not SALES_PW:
        _s_status.markdown('<div class="alert alert-error">❌ Δεν βρέθηκε SALES_EMAIL_PASS.</div>', unsafe_allow_html=True)

    df_s = load_sales()

    if df_s.empty:
        st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα. Πατήστε Ενημέρωση.</div>', unsafe_allow_html=True)
        st.stop()

    t_wk, t_mo = st.tabs(["Εβδομαδιαία", "Μηνιαία"])

    # ── WEEKLY (Δευτέρα–Κυριακή) ──
    with t_wk:
        sel_s = st.date_input("Επίλεξε ημέρα:", today, key="sales_wk_date")
        sw, ew   = get_week_range(sel_s)
        psw, pew = prev_week_range(sw)
        offset   = 0  # χρησιμοποιείται μόνο για chart keys

        st.markdown(f'<div class="date-badge">📅 Δευτ. {sw.strftime("%d/%m/%Y")} — Κυρ. {ew.strftime("%d/%m/%Y")}</div>', unsafe_allow_html=True)

        w_df  = df_s[(df_s["date"] >= sw)  & (df_s["date"] <= ew)]
        pw_df = df_s[(df_s["date"] >= psw) & (df_s["date"] <= pew)]

        if not w_df.empty:
            tot   = w_df["net_sales"].sum()
            cst   = w_df["customers"].sum()
            avg   = w_df["avg_basket"].mean()
            p_tot = pw_df["net_sales"].sum()   if not pw_df.empty else None
            p_cst = pw_df["customers"].sum()   if not pw_df.empty else None
            p_avg = pw_df["avg_basket"].mean() if not pw_df.empty else None

            st.markdown(f"""
            <div class="kpi-grid kpi-3">
                <div class="kpi-card" style="--accent:#3fb950">
                    <div class="kpi-label">Καθαρές Πωλήσεις</div>
                    <div class="kpi-value green">{fmt(tot)}</div>
                    {trend_html(tot, p_tot)}
                </div>
                <div class="kpi-card" style="--accent:#58a6ff">
                    <div class="kpi-label">Πελάτες</div>
                    <div class="kpi-value blue">{fmt_int(cst)}</div>
                    {trend_html(cst, p_cst, unit="")}
                </div>
                <div class="kpi-card" style="--accent:#bc8cff">
                    <div class="kpi-label">ΜΟ Καλαθιού</div>
                    <div class="kpi-value purple">{fmt(avg)}</div>
                    {trend_html(avg, p_avg)}
                </div>
            </div>
            """, unsafe_allow_html=True)

            c1, c2 = st.columns([3, 2])
            with c1:
                st.plotly_chart(sales_line_chart(w_df), use_container_width=True, key=f"sales_wk_line_{offset}")
            with c2:
                st.plotly_chart(basket_bar_chart(w_df), use_container_width=True, key=f"sales_wk_bar_{offset}")

            st.markdown('<div class="section-label">Αναλυτικά</div>', unsafe_allow_html=True)
            disp = w_df.copy()
            disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
            disp = disp.sort_values("date", ascending=False)
            st.dataframe(
                disp.rename(columns={
                    "date": "ΗΜΕΡΟΜΗΝΙΑ", "net_sales": "ΠΩΛΗΣΕΙΣ",
                    "customers": "ΠΕΛΑΤΕΣ", "avg_basket": "ΜΟ ΚΑΛΑΘΙΟΥ"
                }).style.format({
                    "ΠΩΛΗΣΕΙΣ": lambda v: fmt(v),
                    "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—",
                    "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—",
                }),
                use_container_width=True, hide_index=True,
            )
        else:
            st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

    # ── MONTHLY με πλοήγηση ←→ ──
    with t_mo:
        _ca, _cb = st.columns(2)
        with _ca:
            sm = st.selectbox("Μήνας", range(1,13), format_func=lambda x: MONTHS_GR[x-1], index=today.month-1, key="sales_mo_sel")
        with _cb:
            _yrs_s = sorted({r.year for r in df_s["date"]}, reverse=True)
            sy = st.selectbox("Έτος", _yrs_s, key="sales_yr_sel")
        mo_off = 0  # για chart keys

        m_df = df_s[(df_s["date"].apply(lambda d: d.month) == sm) & (df_s["date"].apply(lambda d: d.year) == sy)]
        pm   = sm - 1 if sm > 1 else 12
        py   = sy if sm > 1 else sy - 1
        pm_df = df_s[(df_s["date"].apply(lambda d: d.month) == pm) & (df_s["date"].apply(lambda d: d.year) == py)]

        if not m_df.empty:
            tot   = m_df["net_sales"].sum()
            avg   = m_df["net_sales"].mean()
            best  = m_df["net_sales"].max()
            cst   = m_df["customers"].sum() if "customers" in m_df.columns else None
            p_tot = pm_df["net_sales"].sum() if not pm_df.empty else None

            st.markdown(f"""
            <div class="kpi-grid kpi-4">
                <div class="kpi-card" style="--accent:#3fb950">
                    <div class="kpi-label">Σύνολο Μήνα</div>
                    <div class="kpi-value green">{fmt(tot)}</div>
                    {trend_html(tot, p_tot)}
                </div>
                <div class="kpi-card" style="--accent:#58a6ff">
                    <div class="kpi-label">Ημερήσιος ΜΟ</div>
                    <div class="kpi-value blue">{fmt(avg)}</div>
                </div>
                <div class="kpi-card" style="--accent:#e3b341">
                    <div class="kpi-label">Καλύτερη Ημέρα</div>
                    <div class="kpi-value" style="color:#e3b341">{fmt(best)}</div>
                </div>
                <div class="kpi-card" style="--accent:#bc8cff">
                    <div class="kpi-label">Πελάτες (σύνολο)</div>
                    <div class="kpi-value purple">{fmt_int(cst) if cst else '—'}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.plotly_chart(sales_line_chart(m_df, f"Πωλήσεις {MONTHS_GR[sm-1]} {sy}"), use_container_width=True, key=f"sales_mo_line_{mo_off}")

            # Τάση 12 μηνών
            st.markdown('<div class="section-label">Τάση 12 Μηνών</div>', unsafe_allow_html=True)
            monthly_rows = []
            for i in range(11, -1, -1):
                _ref = today.month - 1 + mo_off - i
                _mm  = (_ref % 12) + 1
                _yy  = today.year + (_ref // 12)
                sub  = df_s[(df_s["date"].apply(lambda d: d.month) == _mm) & (df_s["date"].apply(lambda d: d.year) == _yy)]
                if not sub.empty:
                    monthly_rows.append({"label": f"{MONTHS_GR[_mm-1][:3]} {_yy}", "net_sales": sub["net_sales"].sum()})
            if monthly_rows:
                st.plotly_chart(monthly_bar_chart(pd.DataFrame(monthly_rows)), use_container_width=True, key=f"sales_mo_trend_{mo_off}")

            st.markdown('<div class="section-label">Αναλυτικά</div>', unsafe_allow_html=True)
            disp = m_df.copy()
            disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
            disp = disp.sort_values("date", ascending=False)
            st.dataframe(
                disp.rename(columns={
                    "date": "ΗΜΕΡΟΜΗΝΙΑ", "net_sales": "ΠΩΛΗΣΕΙΣ",
                    "customers": "ΠΕΛΑΤΕΣ", "avg_basket": "ΜΟ ΚΑΛΑΘΙΟΥ",
                }).style.format({
                    "ΠΩΛΗΣΕΙΣ": lambda v: fmt(v),
                    "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—",
                    "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—",
                }),
                use_container_width=True, hide_index=True,
            )
            csv = m_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).to_csv(index=False).encode("utf-8-sig")
            st.download_button(f"📥 Λήψη CSV — {MONTHS_GR[sm-1]} {sy}", csv, f"sales_{sy}_{sm:02d}.csv", "text/csv", key=f"sales_dl_{mo_off}")
        else:
            st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτόν τον μήνα.</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ΠΑΡΑΣΤΑΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📋 Παραστατικά":
    st.markdown("""
    <div class="page-header">
        <div class="icon">📋</div>
        <div><h1>Παραστατικά</h1><div class="sub">Τιμολόγια & Πιστωτικά</div></div>
    </div>
    """, unsafe_allow_html=True)

    # ── Κουμπί Ενημέρωσης ──
    _ic1, _ic2 = st.columns([1.9, 4])
    with _ic1:
        st.markdown('<div class="btn-primary">', unsafe_allow_html=True)
        _i_inc = st.button("🔁 Ενημέρωση Παραστατικών", key="inv_refresh_v2", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    _i_status = st.empty()

    if _i_inc and INV_PW:
        with st.spinner("Σύνδεση & αποθήκευση..."):
            _saved_i, _errs_i, _total_i = fetch_and_store_invoices(INV_PW, limit=50)
        if _errs_i:
            _i_status.markdown(f'<div class="alert alert-error">❌ {_errs_i[0]}</div>', unsafe_allow_html=True)
        else:
            _i_status.markdown(f'<div class="alert alert-success">✅ {_total_i} εγγραφές — {_saved_i} νέες αποθηκεύτηκαν.</div>', unsafe_allow_html=True)
            _raw_load_invoices.clear()
            st.rerun()
    elif _i_inc and not INV_PW:
        _i_status.markdown('<div class="alert alert-error">❌ Δεν βρέθηκε EMAIL_PASS στα Secrets.</div>', unsafe_allow_html=True)

    df_inv = load_invoices()

    t_wk, t_mo = st.tabs(["Εβδομαδιαία", "Μηνιαία"])

    # ── WEEKLY (Δευτέρα–Κυριακή) με ←→ ──
    with t_wk:
        if df_inv.empty:
            st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα. Πατήστε "Ανανέωση Παραστατικών".</div>', unsafe_allow_html=True)
        else:
            sel_i = st.date_input("Επίλεξε ημέρα:", today, key="inv_wk_date")
            sw, ew = get_week_range(sel_i)
            inv_wk_off = 0  # για chart keys

            st.markdown(f'<div class="date-badge">📅 Δευτ. {sw.strftime("%d/%m/%Y")} — Κυρ. {ew.strftime("%d/%m/%Y")}</div>', unsafe_allow_html=True)

            mask = (df_inv["date"] >= pd.Timestamp(sw)) & (df_inv["date"] <= pd.Timestamp(ew) + pd.Timedelta(hours=23, minutes=59))
            w_df = df_inv.loc[mask]

            if not w_df.empty:
                inv_v = w_df[~w_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                crd_v = w_df[w_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                net_v = inv_v - crd_v

                c1, c2 = st.columns([2, 1])
                with c1:
                    st.markdown(f"""
                    <div class="kpi-grid kpi-3">
                        <div class="kpi-card" style="--accent:#3fb950">
                            <div class="kpi-label">Τιμολόγια</div>
                            <div class="kpi-value green">{fmt(inv_v)}</div>
                        </div>
                        <div class="kpi-card" style="--accent:#f85149">
                            <div class="kpi-label">Πιστωτικά</div>
                            <div class="kpi-value red">-{fmt(crd_v)}</div>
                        </div>
                        <div class="kpi-card" style="--accent:#58a6ff">
                            <div class="kpi-label">Καθαρό</div>
                            <div class="kpi-value blue">{fmt(net_v)}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                with c2:
                    if inv_v > 0 or crd_v > 0:
                        st.plotly_chart(invoices_donut(inv_v, crd_v), use_container_width=True, key=f"inv_wk_donut_{inv_wk_off}")

                disp = w_df.copy()
                disp["date"] = disp["date"].dt.strftime("%d/%m/%Y")
                disp = disp.sort_values("date", ascending=False)
                st.dataframe(
                    disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).style.format({"ΑΞΙΑ": lambda v: fmt(v, " €")}),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

    # ── MONTHLY με ←→ ──
    with t_mo:
        if df_inv.empty:
            st.markdown('<div class="alert alert-warn">⚠️ Δεν υπάρχουν δεδομένα.</div>', unsafe_allow_html=True)
        else:
            _ia, _ib = st.columns(2)
            with _ia:
                sm = st.selectbox("Μήνας", range(1,13), format_func=lambda x: MONTHS_GR[x-1], index=today.month-1, key="inv_mo_sel")
            with _ib:
                _yrs_i = sorted(df_inv["date"].dt.year.unique(), reverse=True)
                sy = st.selectbox("Έτος", _yrs_i, key="inv_yr_sel")
            inv_mo_off = 0  # για chart keys

            m_df = df_inv[(df_inv["date"].dt.month == sm) & (df_inv["date"].dt.year == sy)]

            if not m_df.empty:
                inv_m = m_df[~m_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                crd_m = m_df[m_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()

                c1, c2 = st.columns([2, 1])
                with c1:
                    st.markdown(f"""
                    <div class="kpi-grid kpi-3">
                        <div class="kpi-card" style="--accent:#3fb950">
                            <div class="kpi-label">Τιμολόγια</div>
                            <div class="kpi-value green">{fmt(inv_m)}</div>
                        </div>
                        <div class="kpi-card" style="--accent:#f85149">
                            <div class="kpi-label">Πιστωτικά</div>
                            <div class="kpi-value red">-{fmt(crd_m)}</div>
                        </div>
                        <div class="kpi-card" style="--accent:#58a6ff">
                            <div class="kpi-label">Σύνολο Μήνα</div>
                            <div class="kpi-value blue">{fmt(inv_m - crd_m)}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                with c2:
                    if inv_m > 0 or crd_m > 0:
                        st.plotly_chart(invoices_donut(inv_m, crd_m), use_container_width=True, key=f"inv_mo_donut_{inv_mo_off}")

                disp = m_df.copy()
                disp["date"] = disp["date"].dt.strftime("%d/%m/%Y")
                disp = disp.sort_values("date", ascending=False)
                st.dataframe(
                    disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).style.format({"ΑΞΙΑ": lambda v: fmt(v, " €")}),
                    use_container_width=True, hide_index=True,
                )
                csv = m_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).to_csv(index=False).encode("utf-8-sig")
                st.download_button(f"📥 Λήψη {MONTHS_GR[sm-1]} {sy}", csv, f"invoices_{sy}_{sm:02d}.csv", "text/csv", key=f"inv_dl_{inv_mo_off}")
            else:
                st.markdown('<div class="alert alert-info">ℹ️ Δεν υπάρχουν εγγραφές για αυτόν τον μήνα.</div>', unsafe_allow_html=True)

