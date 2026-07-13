"""
core/config.py — Μία πηγή αλήθειας για όλες τις σταθερές.
Χρησιμοποιείται ΚΑΙ από την εφαρμογή ΚΑΙ από τα jobs (GitHub Actions).
"""

# ── GOOGLE SHEETS ─────────────────────────────────────────────────────────────
SPREADSHEET_ID = "1KWX5PH0Dg-dhfMfT8-jCd-Jft9f80I1E2Wss1w8QTlA"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_SALES  = "sales"
SHEET_INV    = "invoices"
SHEET_TIMOL  = "timologiseis"

SALES_COLS = ["date", "net_sales", "customers", "avg_basket"]
INV_COLS   = ["date", "type", "value"]
TIMOL_COLS = ["check_date", "period", "amount", "check_number", "expenses"]

# ΣΗΜΑΝΤΙΚΟ: όλα τα ποσά αποθηκεύονται στο Sheet ως ΛΕΠΤΑ (ακέραιοι, ×100).
# Αυτό αποφεύγει προβλήματα με το ελληνικό locale (κόμμα vs τελεία).
CENTS = 100

# ── EMAIL ─────────────────────────────────────────────────────────────────────
INVOICES_EMAIL_USER   = "abf.skyros@gmail.com"
INVOICES_EMAIL_SENDER = "Notifications@WeDoConnect.com"

SALES_EMAIL_USER      = "ftoulisgm@gmail.com"
SALES_EMAIL_SENDER    = "abf.skyros@gmail.com"
SALES_SUBJECT_KW      = "ΑΒ ΣΚΥΡΟΣ"

TIMOL_EMAIL_USER      = "abf.skyros@gmail.com"
TIMOL_EMAIL_SENDER    = "fr.georgios.manos.ftoylis@ab.gr"
TIMOL_SUBJECT_KW      = "ΤΙΜΟΛΟΓΗΣΕΙΣ"

IMAP_HOST = "imap.gmail.com"

# ── ΕΠΙΧΕΙΡΗΣΙΑΚΕΣ ΣΤΑΘΕΡΕΣ ───────────────────────────────────────────────────
# 364 ημέρες = 52 εβδομάδες. Πέφτει ΠΑΝΤΑ στην ίδια ημέρα της εβδομάδας πέρσι.
# Για λιανική, η σύγκριση «Παρασκευή vs Παρασκευή» έχει νόημα — όχι «17/3 vs 17/3».
YOY_OFFSET_DAYS = 364

# Η επιταγή καλύπτει τις πωλήσεις των 7 ημερών ΠΡΙΝ την ημερομηνία της.
CHECK_PERIOD_DAYS = 7

# Πόσο κοντά (± ημέρες) ψάχνουμε την περσινή αντίστοιχη επιταγή.
CHECK_MATCH_TOLERANCE = 3

DEEP_SCAN_YEARS = 2
BATCH_SIZE = 20

# ── ΕΛΛΗΝΙΚΑ ──────────────────────────────────────────────────────────────────
DAYS_GR = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
DAYS_GR_SHORT = ["Δευ", "Τρι", "Τετ", "Πεμ", "Παρ", "Σαβ", "Κυρ"]

MONTHS_GR = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος",
             "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]
MONTHS_GR_SHORT = ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μάι", "Ιουν",
                   "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"]

# ── ΣΕΛΙΔΕΣ ───────────────────────────────────────────────────────────────────
PAGES = {
    "Επισκόπηση":   "home",
    "Πωλήσεις":     "trending-up",
    "Παραστατικά":  "file-text",
    "Τιμολογήσεις": "credit-card",
    "Μήνας":        "calendar",
}
DEFAULT_PAGE = "Επισκόπηση"

# ── ΧΡΩΜΑΤΑ (πρέπει να ταιριάζουν με ui/style.css) ────────────────────────────
COLOR = {
    "ink":       "#0B2A4A",   # βαθύ navy — ΑΒ
    "brand":     "#0072CE",   # ΑΒ μπλε
    "brand_soft":"#E6F1FB",
    "pos":       "#00875A",   # θετικό (πράσινο)
    "neg":       "#C9372C",   # αρνητικό (κόκκινο)
    "warn":      "#B54708",
    "prev":      "#94A3B8",   # περσινά — γκρι, όχι διαγωνιστικό χρώμα
    "grid":      "#E8ECF1",
    "text":      "#0F172A",
    "muted":     "#64748B",
    "dim":       "#94A3B8",
}
