"""
app.py — ΑΒ Σκύρος Dashboard
ΕΚΔΟΣΗ: v5.0 GLASSMORPHISM — ημιδιάφανες κάρτες με blur
(Αν βλέπεις αυτή τη γραμμή στο GitHub, ανέβηκε η ΣΩΣΤΗ έκδοση)
"""

import streamlit as st
import pandas as pd
import io, re
from datetime import datetime, date, timedelta
from imap_tools import MailBox, AND

# ΣΗΜΑΝΤΙΚΟ: pdf2image/pytesseract ΔΕΝ γίνονται import εδώ.
# Χρειάζονται system libs (poppler/tesseract) που ΔΕΝ υπάρχουν στο Streamlit Cloud
# και το import τους προκαλεί crash (segmentation fault).
# Το OCR τρέχει μόνο στο GitHub Actions (sales_sync.py). Εδώ φορτώνεται lazy, μόνο αν χρειαστεί.
_OCR_OK = None
def _load_ocr():
    """Φορτώνει OCR μόνο όταν χρειάζεται. Επιστρέφει (convert_from_bytes, pytesseract) ή (None, None)."""
    global _OCR_OK
    try:
        from pdf2image import convert_from_bytes as _cfb
        import pytesseract as _pt
        _OCR_OK = True
        return _cfb, _pt
    except Exception:
        _OCR_OK = False
        return None, None

# ΤΕΣΤ Β: ΧΩΡΙΣ gsheets — stub αντί για πραγματικές συναρτήσεις
import pandas as _pd_stub
def _empty_df(*a, **k): return _pd_stub.DataFrame()
_empty_df.clear = lambda: None
def _noop(*a, **k): return None
_noop.clear = lambda: None
_raw_load_sales = _empty_df
_raw_load_invoices = _empty_df
load_timologiseis = _empty_df
merge_sales = merge_invoices = merge_timologiseis = _noop
update_sales_value = _noop
update_timologiseis_check_number = update_timologiseis_expenses = _noop
check_sales_quality = check_timologiseis_quality = check_invoices_quality = _noop
delete_sheet_row = _noop

# ── ΦΟΡΤΩΣΗ ΔΕΔΟΜΕΝΩΝ ─────────────────────────────────────────────────────────
# ΣΗΜΑΝΤΙΚΟ: Το gsheets_helper κάνει ΗΔΗ όλη τη μετατροπή (x100 → ευρώ),
# την αφαίρεση διπλών και τη μείωση μνήμης (float32).
# Το παλιό wrapper με .copy() + .apply() ανά κελί ΔΕΝ είχε cache και ξανάτρεχε
# σε ΚΑΘΕ rerun — με 10.000+ παραστατικά έσκαγε τη μνήμη (segmentation fault).
# Χρησιμοποιούμε απευθείας τις cached συναρτήσεις.
load_sales = _raw_load_sales
load_invoices = _raw_load_invoices
# ──────────────────────────────────────────────────────────────────────────────

# ── CONFIG ────────────────────────────────────────────────────────────────────
INVOICES_EMAIL_USER   = "abf.skyros@gmail.com"
INVOICES_EMAIL_SENDER = "Notifications@WeDoConnect.com"
SALES_EMAIL_USER      = "ftoulisgm@gmail.com"
SALES_EMAIL_SENDER    = "abf.skyros@gmail.com"
# Τιμολογήσεις (επιταγές) — έρχονται στο abf.skyros από fr.georgios.manos.ftoylis@ab.gr
TIMOL_EMAIL_USER      = "abf.skyros@gmail.com"
TIMOL_EMAIL_SENDER    = "fr.georgios.manos.ftoylis@ab.gr"
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
DAYS_GR_FULL = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

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

/* ═══════════════ CORPORATE / STRIPE-STYLE THEME ═══════════════ */
:root {
    --bg:          #f6f8fb;
    --bg-elev:     #ffffff;
    --bg-card:     #ffffff;
    --bg-hover:    #f0f4f9;
    --border:      #e3e8ef;
    --border-soft: #eef2f7;
    --text:        #1a2233;
    --text-mut:    #5b6b82;
    --text-dim:    #8a99ad;
    --brand:       #635bff;
    --brand-2:     #4b45c6;
    --brand-3:     #7a73ff;
    --brand-glow:  rgba(99,91,255,.25);
    --sky:         #0ea5e9;
    --red:         #df1b41;
    --red-soft:    rgba(223,27,65,.09);
    --green:       #17a34a;
    --amber:       #e08c0c;
    --violet:      #7a5af8;
    --shadow:      0 1px 3px rgba(26,34,51,.06), 0 1px 2px rgba(26,34,51,.04);
    --shadow-md:   0 4px 12px rgba(26,34,51,.08);
    --shadow-lg:   0 12px 32px rgba(26,34,51,.12);
}

*, *::before, *::after { box-sizing: border-box; }
html, body, [class*="css"] {
    font-family: 'Inter', system-ui, sans-serif !important;
    background: var(--bg) !important;
    color: var(--text) !important;
}
.stApp { background: var(--bg) !important; }
.stApp::before {
    content: ''; position: fixed; top: 0; left: 0; right: 0; height: 280px; pointer-events: none; z-index: 0;
    background: linear-gradient(180deg, rgba(99,91,255,.04) 0%, transparent 100%);
}
#MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }
/* Φέρε το περιεχόμενο ψηλά (αφαίρεσε το προεπιλεγμένο κενό του Streamlit) */
[data-testid="stAppViewContainer"] > .main { padding-top: 0 !important; }
[data-testid="stMain"] { padding-top: 0 !important; }
[data-testid="stMainBlockContainer"] { padding-top: 1rem !important; }
.stApp [data-testid="stVerticalBlock"] { gap: .75rem !important; }
.block-container { padding: 0.5rem 2.5rem 6rem !important; max-width: 1280px !important; position: relative; z-index: 1; }
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
    display: flex; align-items: center; gap: 1.15rem;
    margin: 0 0 1.5rem 0; padding-bottom: 1.1rem;
    border-bottom: 1px solid var(--border-soft);
}
.page-header .icon {
    width: 56px; height: 56px; border-radius: 17px; display: flex; align-items: center; justify-content: center;
    font-size: 1.65rem; color: #fff; position: relative;
    background: linear-gradient(135deg, var(--brand), var(--brand-2));
    box-shadow: 0 10px 26px var(--brand-glow), inset 0 1px 0 rgba(255,255,255,.3); flex-shrink: 0;
}
.page-header .icon::after {
    content: ''; position: absolute; inset: 0; border-radius: 17px;
    background: radial-gradient(circle at 30% 25%, rgba(255,255,255,.35), transparent 60%);
}
.page-header h1 {
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.85rem; font-weight: 800;
    letter-spacing: -.025em; color: var(--text); margin: 0; line-height: 1.05;
}
.page-header .sub { font-size: .85rem; color: var(--text-mut); margin-top: .35rem; font-weight: 500; }

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
    background: var(--bg-card);
    border: 1px solid var(--border); border-radius: 14px; padding: 1.5rem 1.6rem;
    transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
    box-shadow: var(--shadow);
}
.kpi-card:hover {
    transform: translateY(-2px);
    border-color: color-mix(in srgb, var(--accent, var(--brand)) 35%, var(--border));
    box-shadow: var(--shadow-md);
}
.kpi-card::after {
    content: ''; position: absolute; inset: 0 0 auto 0; height: 3px;
    background: var(--accent, var(--brand));
}
.kpi-card .glow { display: none; }
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
    position: relative; overflow: hidden; border-radius: 16px; padding: 1.6rem 1.75rem;
    color: #fff; min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;
    box-shadow: var(--shadow-md); transition: transform .15s ease, box-shadow .15s ease;
}
.hero-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
.hero-card.grad-blue   { background: linear-gradient(135deg, #7a73ff 0%, #635bff 55%, #4b45c6 100%); }
.hero-card.grad-violet { background: linear-gradient(135deg, #9d6ef7 0%, #7a5af8 50%, #5b45b8 100%); }
.hero-card.grad-navy   { background: linear-gradient(135deg, #2d3748 0%, #1a2233 100%); }
.hero-card.grad-teal   { background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%); }
.hero-card::after {
    content: ''; position: absolute; top: -40%; right: -10%; width: 190px; height: 190px;
    border-radius: 50%; background: radial-gradient(circle, rgba(255,255,255,.16), transparent 68%); pointer-events: none;
}
.hero-card::before {
    content: ''; position: absolute; bottom: -45%; left: 5%; width: 150px; height: 150px;
    border-radius: 50%; background: radial-gradient(circle, rgba(255,255,255,.08), transparent 70%); pointer-events: none;
}
.hero-label {
    font-size: .72rem; font-weight: 600; letter-spacing: .04em; opacity: .92;
    display: flex; align-items: center; gap: .5rem; position: relative; z-index: 1;
}
.hero-icon {
    position: absolute; top: 1.45rem; right: 1.55rem; width: 40px; height: 40px; border-radius: 11px;
    background: rgba(255,255,255,.18); display: flex; align-items: center; justify-content: center;
    font-size: 1.18rem; z-index: 1; box-shadow: inset 0 1px 0 rgba(255,255,255,.25);
}
.hero-value {
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 2.1rem; font-weight: 800;
    letter-spacing: -.03em; line-height: 1; position: relative; z-index: 1; font-variant-numeric: tabular-nums;
}
.hero-sub { font-size: .76rem; opacity: .9; position: relative; z-index: 1; font-weight: 500; }
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
    background: color-mix(in srgb, var(--brand) 8%, #ffffff);
    border: 1px solid color-mix(in srgb, var(--brand) 20%, var(--border));
    border-radius: 8px; padding: .5rem .9rem; font-size: .8rem; font-weight: 600; color: var(--brand); margin-bottom: 1.35rem;
}

/* ═══════════════ ALERTS ═══════════════ */
.alert { border-radius: 12px; padding: .9rem 1.15rem; font-size: .78rem; font-weight: 500; margin: .75rem 0; display: flex; gap: .55rem; align-items: flex-start; }
.alert-success { background: rgba(26,162,96,.1); border: 1px solid rgba(26,162,96,.4); color: var(--green); }
.alert-warn    { background: rgba(232,146,12,.1); border: 1px solid rgba(232,146,12,.4); color: var(--amber); }
.alert-error   { background: var(--red-soft); border: 1px solid rgba(226,35,26,.4); color: var(--red); }
.alert-info    { background: rgba(0,114,206,.08); border: 1px solid rgba(0,114,206,.3); color: var(--brand); }

/* ═══════════════ TABLE ═══════════════ */
[data-testid="stDataFrame"] { border: 1px solid var(--border) !important; border-radius: 12px !important; overflow: hidden !important; box-shadow: var(--shadow) !important; }
[data-testid="stDataFrame"] th { background: var(--bg) !important; color: var(--text-dim) !important; font-size: .64rem !important; letter-spacing: .06em !important; text-transform: uppercase !important; font-weight: 700 !important; padding-top: .7rem !important; padding-bottom: .7rem !important; }
[data-testid="stDataFrame"] td { background: #ffffff !important; color: var(--text) !important; font-size: .84rem !important; border-color: var(--border-soft) !important; }

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
[data-testid="stExpander"] { border: 1px solid var(--border) !important; border-radius: 10px !important; background: #ffffff !important; box-shadow: var(--shadow) !important; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] details > summary { padding: .5rem .85rem !important; font-size: .82rem !important; font-weight: 600 !important; min-height: unset !important; }
[data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span { font-size: .82rem !important; }
[data-testid="stExpander"] summary svg { width: 1rem !important; height: 1rem !important; }
[data-testid="stExpander"] summary { color: var(--text-mut) !important; font-size: .82rem !important; font-weight: 600 !important; }

/* ═══════════════ PROGRESS CARD ═══════════════ */
.prog-card { background: #ffffff; border: 1px solid var(--border); border-radius: 14px; padding: 1.2rem 1.4rem; margin: .75rem 0; }
.prog-title { font-size: .88rem; font-weight: 700; color: var(--text); margin-bottom: .4rem; }
.prog-sub { font-size: .72rem; color: var(--text-mut); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

hr { border-color: var(--border-soft) !important; margin: 1.5rem 0 !important; }

/* ═══════════════ YEAR ROW (timologiseis) ═══════════════ */
.year-row {
    display: flex; align-items: center; justify-content: space-between;
    background: var(--bg-card);
    border: 1px solid var(--border); border-radius: 12px; padding: 1.1rem 1.4rem; margin-bottom: .6rem;
    transition: all .15s ease; box-shadow: var(--shadow);
}
.year-row:hover { border-color: color-mix(in srgb, var(--brand) 40%, var(--border)); transform: translateX(2px); box-shadow: var(--shadow-md); }
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
    # Lazy load OCR — δεν υπάρχει στο Streamlit Cloud, μόνο σε GitHub Actions/τοπικά.
    convert_from_bytes, pytesseract = _load_ocr()
    if convert_from_bytes is None or pytesseract is None:
        return r
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
# ══════════════════════════════════════════════════════════════════════════════
# 🔧 ΔΙΑΚΟΠΤΗΣ ΣΕΛΙΔΩΝ — ΒΗΜΑ ΒΗΜΑ
# ══════════════════════════════════════════════════════════════════════════════
# Πρόσθεσε ΜΙΑ σελίδα τη φορά για να βρούμε ποια σκάει.
#
#   ΒΗΜΑ 1: ENABLED_PAGES = ["Επισκόπηση"]
#   ΒΗΜΑ 2: ENABLED_PAGES = ["Επισκόπηση", "Πωλήσεις"]
#   ΒΗΜΑ 3: ENABLED_PAGES = ["Επισκόπηση", "Πωλήσεις", "Παραστατικά"]
#   ΒΗΜΑ 4: + "Τιμολογήσεις"
#   ΒΗΜΑ 5: + "Μήνας"
#
# Μόλις σκάσει σε κάποιο βήμα → βρήκαμε τον ένοχο!
# Όταν τελειώσουμε, βάλε ENABLED_PAGES = ALL_PAGES για να ενεργοποιηθούν όλες.
# ══════════════════════════════════════════════════════════════════════════════
ALL_PAGES = ["Επισκόπηση", "Πωλήσεις", "Παραστατικά", "Τιμολογήσεις", "Μήνας"]

ENABLED_PAGES = ["Επισκόπηση"]          # ← ΑΛΛΑΞΕ ΜΟΝΟ ΑΥΤΗ ΤΗ ΓΡΑΜΜΗ

# Δείχνει τη μνήμη στην οθόνη (βοηθάει να δούμε πού εκτοξεύεται)
SHOW_MEMORY = True

PAGES = ENABLED_PAGES
PAGE_ICONS = {"Επισκόπηση": "🏠", "Πωλήσεις": "📈", "Παραστατικά": "🧾", "Τιμολογήσεις": "💳", "Μήνας": "📅"}


def _mem_mb():
    """Τρέχουσα μνήμη της διεργασίας σε MB."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return 0.0


def _mem_badge(label=""):
    """Εμφανίζει τη μνήμη στην οθόνη."""
    if not SHOW_MEMORY:
        return
    m = _mem_mb()
    _color = "#17a34a" if m < 400 else ("#e08c0c" if m < 800 else "#df1b41")
    st.markdown(
        f'<div style="position:fixed;bottom:10px;right:10px;z-index:999999;'
        f'background:#fff;border:2px solid {_color};border-radius:10px;'
        f'padding:.5rem .9rem;font-family:monospace;font-size:.8rem;font-weight:700;'
        f'color:{_color};box-shadow:0 4px 14px rgba(0,0,0,.15)">'
        f'🧠 {m:.0f} MB {label}</div>',
        unsafe_allow_html=True
    )

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
.block-container { padding-left: 264px !important; }
@media (max-width: 820px) { .block-container { padding-left: 1rem !important; } }
</style>
""", unsafe_allow_html=True)

# ── CUSTOM SIDEBAR (σκούρα μπάρα με εικονίδιο + κείμενο — στυλ Flowlu) ──
import urllib.parse as _u_rail
# ── Wide sidebar with grouped navigation (like enterprise dashboards) ──
# Ομάδες: ΛΕΙΤΟΥΡΓΙΕΣ (οι κύριες σελίδες μας)
_NAV_GROUPS = [
    ("", [("Επισκόπηση", "Dashboard")]),
    ("ΛΕΙΤΟΥΡΓΙΕΣ", [("Πωλήσεις", "Πωλήσεις"), ("Παραστατικά", "Παραστατικά"),
                     ("Τιμολογήσεις", "Τιμολογήσεις"), ("Μήνας", "Μήνας")]),
]

_rail_items = ""
for _grp_name, _grp_pages in _NAV_GROUPS:
    if _grp_name:
        _rail_items += f'<div class="rail-group">{_grp_name}</div>'
    for p, _lbl in _grp_pages:
        _active = p == page
        _href = "?page=" + _u_rail.quote(p)
        _cls = "rail-item active" if _active else "rail-item"
        _chevron = '<span class="rail-chev">›</span>' if _active else ''
        _rail_items += (
            f'<a href="{_href}" target="_self" class="{_cls}">'
            f'<span class="rail-ico">{PAGE_ICONS[p]}</span>'
            f'<span class="rail-lbl">{_lbl}</span>'
            f'{_chevron}'
            f'</a>'
        )

_rail_html = (
    '<div class="side-rail">'
    '<div class="side-brand">'
    '<div class="side-logo">ΑΒ</div>'
    '<div class="side-brand-txt"><span class="side-name">AB Σκύρος</span>'
    '<span class="side-sub">Business Intelligence</span></div>'
    '</div>'
    '<div class="rail-nav">' + _rail_items + '</div>'
    '<div class="side-promo">'
    '<div class="side-promo-title">AB Σκύρος</div>'
    '<div class="side-promo-sub">Έξυπνη πληροφόρηση, καλύτερες αποφάσεις.</div>'
    '</div>'
    '<div class="side-user">'
    '<div class="side-user-av">FT</div>'
    '<div class="side-user-txt"><span class="side-user-name">Διαχειριστής</span>'
    '<span class="side-user-status"><span class="su-dot"></span>Online</span></div>'
    '</div>'
    '</div>'
)
st.markdown(_rail_html, unsafe_allow_html=True)

# ── Blue gradient header banner ──
from datetime import datetime as _dtnow
_today_hdr = date.today()
_hr = _dtnow.now().hour
_gr = "Καλημέρα" if _hr < 12 else ("Καλησπέρα" if _hr < 18 else "Καλό βράδυ")
_topbar = (
    '<div class="hero-banner">'
    '<div class="hero-banner-inner">'
    '<div class="hb-left">'
    f'<div class="hb-greet">{_gr}! ☀️</div>'
    '<div class="hb-title">AB Σκύρος Store</div>'
    '<div class="hb-sub">Retail Operations Dashboard</div>'
    '</div>'
    '<div class="hb-right">'
    '<div class="hb-datebox">'
    f'<div class="hb-date-d">📅 {DAYS_GR_FULL[_today_hdr.weekday()]}, {_today_hdr.day} {MONTHS_GR[_today_hdr.month-1]} {_today_hdr.year}</div>'
    '</div>'
    '<div class="hb-live"><span class="hb-live-dot"></span>Live</div>'
    '</div>'
    '</div></div>'
)
st.markdown(_topbar, unsafe_allow_html=True)

st.markdown("""
<style>
/* ═══════════════ WIDE SIDEBAR (enterprise) ═══════════════ */
.side-rail {
    position: fixed; top: 0; left: 0; bottom: 0; width: 240px; z-index: 999990;
    background: linear-gradient(180deg, #0f2847 0%, #0a1f38 55%, #071528 100%);
    border-right: 1px solid rgba(120,170,230,.08);
    display: flex; flex-direction: column;
    padding: 1.4rem 0 1rem; overflow-y: auto;
    box-shadow: 3px 0 24px rgba(6,20,40,.25);
}
.side-rail::-webkit-scrollbar { width: 5px; }
.side-rail::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 3px; }
.side-brand { display: flex; align-items: center; gap: .7rem; padding: 0 1.3rem 1.5rem; }
.side-logo {
    width: 44px; height: 44px; border-radius: 12px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Plus Jakarta Sans'; font-weight: 800; font-size: 1.1rem; color: #fff;
    background: linear-gradient(135deg, #3b82f6, #2563eb 60%, #1d4ed8);
    box-shadow: 0 4px 14px rgba(59,130,246,.45), inset 0 1px 0 rgba(255,255,255,.35);
}
.side-brand-txt { display: flex; flex-direction: column; gap: .1rem; }
.side-name { font-family: 'Plus Jakarta Sans'; font-weight: 800; font-size: 1.05rem; color: #fff; letter-spacing: -.01em; line-height: 1.1; }
.side-sub { font-size: .66rem; color: #7e98bd; font-weight: 500; }
.rail-nav { display: flex; flex-direction: column; gap: .12rem; padding: 0 .75rem; flex: 1; }
.rail-group {
    font-size: .62rem; font-weight: 700; letter-spacing: .1em; color: #5e779c;
    text-transform: uppercase;
    padding: 1.1rem .7rem .4rem;
}
.rail-item {
    position: relative; display: flex; align-items: center; gap: .8rem;
    padding: .7rem .85rem; border-radius: 10px; text-decoration: none !important;
    transition: all .15s ease; margin-bottom: .05rem;
}
.rail-item .rail-ico { font-size: 1.15rem; line-height: 1; width: 1.4rem; text-align: center; filter: grayscale(1) opacity(.6); transition: all .15s; }
.rail-item .rail-lbl { font-size: .86rem; font-weight: 600; color: #a9bdd8; transition: color .15s; flex: 1; }
.rail-item .rail-chev { color: #fff; font-size: 1.1rem; font-weight: 700; }
.rail-item:hover { background: rgba(255,255,255,.06); }
.rail-item:hover .rail-ico { filter: grayscale(.2) opacity(.9); }
.rail-item:hover .rail-lbl { color: #e2ecf8; }
.rail-item.active {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    box-shadow: 0 4px 14px rgba(37,99,235,.4);
}
.rail-item.active .rail-ico { filter: none; }
.rail-item.active .rail-lbl { color: #fff; font-weight: 700; }
.side-promo {
    margin: 1rem .9rem .8rem; padding: 1.1rem 1rem; border-radius: 14px;
    background: linear-gradient(145deg, rgba(37,99,235,.22), rgba(29,78,216,.12));
    border: 1px solid rgba(90,140,220,.2);
}
.side-promo-title { font-family: 'Plus Jakarta Sans'; font-weight: 800; font-size: .92rem; color: #fff; margin-bottom: .2rem; }
.side-promo-sub { font-size: .72rem; color: #a9bdd8; line-height: 1.4; }
.side-user {
    display: flex; align-items: center; gap: .65rem; margin: 0 .9rem;
    padding: .75rem .5rem; border-top: 1px solid rgba(255,255,255,.08);
}
.side-user-av {
    width: 38px; height: 38px; border-radius: 10px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: .82rem; color: #fff;
    background: linear-gradient(135deg, #3b82f6, #2563eb);
}
.side-user-txt { display: flex; flex-direction: column; gap: .1rem; }
.side-user-name { font-size: .82rem; font-weight: 700; color: #fff; }
.side-user-status { font-size: .68rem; color: #5eba7d; display: flex; align-items: center; gap: .3rem; }
.su-dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }
@media (max-width: 820px) { .side-rail { display: none !important; } }

/* ═══════════════ BLUE GRADIENT HERO BANNER ═══════════════ */
.hero-banner {
    position: relative; overflow: hidden; border-radius: 18px; margin: 0 0 1.5rem 0;
    background: linear-gradient(120deg, #0f2847 0%, #1a4a8a 45%, #2563eb 100%);
    box-shadow: 0 10px 30px rgba(15,40,71,.28);
}
.hero-banner::after {
    content: ''; position: absolute; top: -50%; right: -5%; width: 340px; height: 340px;
    border-radius: 50%; background: radial-gradient(circle, rgba(96,165,250,.28), transparent 65%); pointer-events: none;
}
.hero-banner::before {
    content: ''; position: absolute; bottom: -60%; left: 20%; width: 280px; height: 280px;
    border-radius: 50%; background: radial-gradient(circle, rgba(59,130,246,.2), transparent 68%); pointer-events: none;
}
.hero-banner-inner {
    position: relative; z-index: 1; display: flex; align-items: center; justify-content: space-between;
    padding: 1.6rem 1.9rem; gap: 1rem; flex-wrap: wrap;
}
.hb-greet { font-size: .88rem; color: #bcd4f5; font-weight: 600; margin-bottom: .3rem; }
.hb-title { font-family: 'Plus Jakarta Sans'; font-weight: 800; font-size: 1.9rem; color: #fff; letter-spacing: -.02em; line-height: 1.05; }
.hb-sub { font-size: .82rem; color: #a9c5ec; margin-top: .25rem; font-weight: 500; }
.hb-right { display: flex; align-items: center; gap: .7rem; }
.hb-datebox {
    background: rgba(255,255,255,.14); backdrop-filter: blur(8px);
    border: 1px solid rgba(255,255,255,.18); border-radius: 11px; padding: .6rem .95rem;
}
.hb-date-d { font-size: .8rem; font-weight: 600; color: #fff; }
.hb-live {
    display: inline-flex; align-items: center; gap: .4rem;
    font-size: .76rem; font-weight: 700; color: #fff;
    background: rgba(34,197,94,.25); border: 1px solid rgba(34,197,94,.4);
    border-radius: 10px; padding: .55rem .8rem;
}
.hb-live-dot { width: 7px; height: 7px; border-radius: 50%; background: #4ade80; box-shadow: 0 0 8px #4ade80; animation: livepulse 2s infinite; }
@keyframes livepulse {
    0% { box-shadow: 0 0 0 0 rgba(74,222,128,.6); }
    70% { box-shadow: 0 0 0 6px rgba(74,222,128,0); }
    100% { box-shadow: 0 0 0 0 rgba(74,222,128,0); }
}
@media (max-width: 820px) { .hb-title { font-size: 1.5rem; } .hb-sub { display: none; } }
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
    if st.button("💾 Αποθήκευση διόρθωσης", key="save_fix", width='stretch'):
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
    if st.button("➕ Προσθήκη ημέρας", key="save_add", width='stretch', disabled=_exists):
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
    if st.button("Εκτέλεση ελέγχου", key="run_sales_check", width='stretch'):
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
                        if st.button("🗑 Διαγραφή", key=f"del_sales_{_e['row']}", width='stretch'):
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
# ── Δείχνει ποιες σελίδες είναι ενεργές (για τη διάγνωση) ──
if SHOW_MEMORY:
    _off = [p for p in ALL_PAGES if p not in ENABLED_PAGES]
    if _off:
        st.info(f"🔧 **Λειτουργία διάγνωσης** — Ενεργές: {', '.join(ENABLED_PAGES)}  ·  "
                f"Ανενεργές: {', '.join(_off)}  ·  Μνήμη τώρα: **{_mem_mb():.0f} MB**")
    else:
        st.success(f"✅ Όλες οι σελίδες ενεργές · Μνήμη: **{_mem_mb():.0f} MB**")



st.title("🅱️ ΤΕΣΤ Β — CSS/rail ΧΩΡΙΣ δεδομένα")
st.success("✅ Αν βλέπεις αυτό ΚΑΙ ΔΕΝ πέφτει μετά 30\" → το CSS/rail είναι ΕΝΤΑΞΕΙ.")
st.warning("❌ Αν ΠΕΣΕΙ → φταίει το CSS/HTML/rail.")
st.caption(f"Μνήμη: {_mem_mb():.0f} MB")
