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

# ── ΧΡΩΜΑΤΑ (ταιριάζουν με ui/style.css) ─────────────────────────────────────
#
# Το κόκκινο της ΑΒ είναι η ταυτότητα. ΔΕΝ χρησιμοποιείται για «κακό νούμερο» —
# γι' αυτό υπάρχει ξεχωριστό "neg". Δύο κόκκινα, δύο δουλειές.
COLOR = {
    "ab_red":    "#E2231A",   # Ταυτότητα ΑΒ
    "ab_dark":   "#B81A12",
    "ink":       "#1A1A1A",   # Το κύριο νούμερο
    "brand":     "#E2231A",
    "pos":       "#0E8A4F",   # Ανέβηκε
    "neg":       "#D0342C",   # Έπεσε
    "warn":      "#B25E09",
    "prev":      "#9AA1AD",   # Πέρσι — γκρι
    "grid":      "#E4E7EC",
    "text":      "#16181D",
    "muted":     "#5F6672",
    "dim":       "#9AA1AD",
}
