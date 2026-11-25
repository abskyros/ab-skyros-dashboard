"""
core/sheets.py — ΟΛΗ η επικοινωνία με το Google Sheets περνάει από εδώ.

Λειτουργεί σε ΔΥΟ περιβάλλοντα:
  • Streamlit Cloud  → credentials από st.secrets["gcp_service_account"]
  • GitHub Actions   → credentials από env GOOGLE_KEY_JSON

ΓΙΑΤΙ ΔΕΝ ΣΚΑΕΙ ΠΙΑ (segmentation fault):
  1. Ο gspread client είναι singleton (@st.cache_resource) — ένα connection, όχι
     καινούριο σε κάθε rerun.
  2. Στο cache μπαίνουν ΜΟΝΟ DataFrames — ΠΟΤΕ ζωντανά worksheet objects
     (δεν γίνονται pickle και τρώνε μνήμη).
  3. Διαβάζουμε με get_all_values() (λίστες) αντί get_all_records() (dicts) —
     πολύ λιγότερη μνήμη σε 10.000+ γραμμές.
  4. float32 αντί float64.
"""

from __future__ import annotations

import os
import json
import re
import time
from datetime import date, datetime, timedelta

import pandas as pd

from core.config import (
    SPREADSHEET_ID, SCOPES, CENTS,
    SHEET_SALES, SHEET_INV, SHEET_TIMOL,
    SALES_COLS, INV_COLS, TIMOL_COLS,
)

# Το streamlit είναι optional — τα jobs τρέχουν χωρίς αυτό.
try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    _HAS_ST = False

    class _NoStreamlit:
        """Dummy decorators ώστε ο ίδιος κώδικας να τρέχει και σε GitHub Actions."""
        @staticmethod
        def cache_resource(fn=None, **kw):
            def wrap(f):
                f.clear = lambda: None
                return f
            return wrap(fn) if fn else wrap

        @staticmethod
        def cache_data(fn=None, **kw):
            def wrap(f):
                f.clear = lambda: None
                return f
            return wrap(fn) if fn else wrap

    st = _NoStreamlit()  # type: ignore

import gspread
from google.oauth2.service_account import Credentials


# ══════════════════════════════════════════════════════════════════════════════
# AUTH — singleton client
# ══════════════════════════════════════════════════════════════════════════════
def _credentials_info() -> dict:
    """Βρίσκει τα credentials από όπου κι αν τρέχουμε."""
    # 1) GitHub Actions
    raw = os.environ.get("GOOGLE_KEY_JSON")
    if raw:
        return json.loads(raw)

    # 2) Streamlit Cloud
    if _HAS_ST:
        try:
            info = dict(st.secrets["gcp_service_account"])
            if "private_key" in info:
                info["private_key"] = info["private_key"].replace("\\n", "\n")
            return info
        except Exception:
            pass

    # 3) Τοπικό αρχείο
    key_path = os.environ.get("GOOGLE_KEY_PATH", "ab-skyros-key.json")
    with open(key_path) as f:
        return json.load(f)


@st.cache_resource(show_spinner=False)
def _client():
    """Ένας client για όλη τη ζωή της εφαρμογής. ΔΕΝ επιστρέφει worksheet."""
    creds = Credentials.from_service_account_info(_credentials_info(), scopes=SCOPES)
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def _spreadsheet():
    """
    Το ΑΝΟΙΧΤΟ spreadsheet — singleton, όπως ο client.

    ΓΙΑΤΙ: το .open_by_key() είναι ΜΙΑ κλήση στο API. Αν το καλούσαμε σε κάθε
    _ws(), κάθε ανάγνωση πλήρωνε μία κλήση παραπάνω. Με 3 φύλλα × κάθε rerun,
    αυτό μόνο του έφτανε να χτυπήσει το όριο 60/λεπτό. Ανοίγουμε μία φορά.

    ΔΕΝ μπαίνει σε cache_data (δεν γίνεται pickle) — μόνο cache_resource.
    """
    return _client().open_by_key(SPREADSHEET_ID)


def _ws(name: str):
    """Ζωντανό worksheet — ΠΟΤΕ δεν μπαίνει σε cache_data. Το spreadsheet όμως
    είναι singleton, άρα εδώ πληρώνουμε μόνο την .worksheet() κλήση."""
    return _spreadsheet().worksheet(name)


# ══════════════════════════════════════════════════════════════════════════════
# RETRY — ανθεκτικότητα στο όριο 60 αναγνώσεων/λεπτό (σφάλμα 429)
# ══════════════════════════════════════════════════════════════════════════════
def _is_quota_error(e: Exception) -> bool:
    """Αναγνωρίζει το 429 (quota exceeded) από το gspread APIError ή το μήνυμα."""
    code = getattr(getattr(e, "response", None), "status_code", None)
    if code == 429:
        return True
    s = str(e)
    return "429" in s or "Quota exceeded" in s or "RATE_LIMIT" in s.upper()


def _with_retry(fn, *, tries: int = 2, base_wait: float = 2.5):
    """
    Τρέχει το fn()· αν φάει 429, περιμένει και ξαναδοκιμάζει.

    Το όριο του Sheets είναι «ανά λεπτό». Μια σύντομη αναμονή συχνά αρκεί: όταν
    το Action κι η εφαρμογή διαβάζουν ταυτόχρονα, το σφάλμα είναι στιγμιαίο.
    Καλύτερα να περιμένεις 2-4 δευτ. παρά να δείξεις κίτρινο σφάλμα στον χρήστη.
    """
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if not _is_quota_error(e) or attempt == tries - 1:
                raise
            time.sleep(base_wait * (attempt + 1))   # 2.5s, μετά 5s
    if last:
        raise last


# ── Τυλίγματα πράξεων Sheets με retry ──────────────────────────────────────────
#
# Οι εγγραφές (merge_*) και οι καθαρισμοί (purge_*) ΔΕΝ πιάνουν σφάλματα: ένα
# στιγμιαίο 429 εκεί ρίχνει όλο το job. Αντί να τυλίξουμε δεκάδες κλήσεις μία-
# μία, περνάμε τις τρεις πράξεις που χτυπάνε το API από αυτούς τους helpers.
#
# ΓΙΑΤΙ ΠΕΡΙΣΣΟΤΕΡΕΣ ΠΡΟΣΠΑΘΕΙΕΣ ΕΔΩ: το όριο του Sheets είναι «ανά λεπτό». Ένα
# job (GitHub Actions) δεν έχει χρήστη που περιμένει — μπορεί άνετα να περιμένει
# ως ~30 δευτ. ώσπου να «ανοίξει» το παράθυρο, αντί να αποτύχει το run.
def _get_all(ws) -> list:
    """ws.get_all_values() με retry στο 429."""
    return _with_retry(ws.get_all_values, tries=4, base_wait=5.0)


def _append(ws, rows: list) -> None:
    """
    ws.append_rows(...) με retry στο 429.

    table_range="A1": ΠΑΝΤΑ από τη στήλη A. Χωρίς αυτό, το Google ψάχνει μόνο
    του «τον πίνακα» — και στο timologiseis, όπου οι στήλες F–G (voucher,
    sent_date) είναι γεμάτες μόνο στις τελευταίες γραμμές, έγραφε τις νέες
    γραμμές από τη στήλη F. Η εφαρμογή διάβαζε κενή στήλη A και τις αγνοούσε
    (έτσι «χανόταν» η επιταγή 25/12/2026 και ξαναγραφόταν σε κάθε ενημέρωση).
    """
    _with_retry(lambda: ws.append_rows(rows, value_input_option="RAW",
                                       table_range="A1"),
                tries=4, base_wait=5.0)


def _delete(ws, start: int, end: int) -> None:
    """ws.delete_rows(start, end) με retry στο 429."""
    _with_retry(lambda: ws.delete_rows(int(start), int(end)),
                tries=4, base_wait=5.0)


# ══════════════════════════════════════════════════════════════════════════════
# ΡΥΘΜΙΣΕΙΣ — μικρές τιμές που θυμάται η εφαρμογή (π.χ. το ταμείο)
# ══════════════════════════════════════════════════════════════════════════════
SHEET_SETTINGS = "settings"


def _settings_ws():
    """
    Το φύλλο «settings» (key | value). Αν λείπει, το φτιάχνει.

    Έτσι το ταμείο θυμάται την τελευταία τιμή ακόμα κι αν κλείσεις τον browser
    ή ανοίξεις την εφαρμογή από άλλο κινητό.

    Χρησιμοποιεί το singleton _spreadsheet() — δεν ξανανοίγει το αρχείο.
    """
    ss = _spreadsheet()
    try:
        return ss.worksheet(SHEET_SETTINGS)
    except Exception:
        ws = ss.add_worksheet(title=SHEET_SETTINGS, rows=50, cols=2)
        ws.update([["key", "value"]], "A1")
        return ws


@st.cache_data(ttl=120, max_entries=1, show_spinner=False)
def _load_settings() -> dict:
    """
    ΟΛΕΣ οι ρυθμίσεις μαζί, σε dict {key: value} — cached.

    ΓΙΑΤΙ: πριν, κάθε load_setting() άνοιγε το φύλλο και το διάβαζε ξεχωριστά
    (2 κλήσεις). Το ταμείο και τα πάγια έξοδα είναι δύο κλειδιά — 4 κλήσεις
    μόνο για ρυθμίσεις, σε κάθε πρώτο φόρτωμα των σελίδων «Μήνας/Πρόβλεψη».

    Τώρα: μία ανάγνωση, όλα τα κλειδιά, cached για 2 λεπτά. Το save_setting()
    καθαρίζει αυτό το cache, ώστε η επόμενη ανάγνωση να δει τη νέα τιμή.

    Το 429 εδώ δεν σπάει τίποτα — επιστρέφουμε κενό dict και ο καλών βάζει το
    default. Αλλά ΔΕΝ το καταπίνουμε σιωπηλά: ειδοποιούμε διακριτικά.
    """
    def _fetch():
        return _settings_ws().get_all_values()

    try:
        vals = _with_retry(_fetch)
    except Exception as e:  # noqa: BLE001
        if _is_quota_error(e):
            _warn("Προσωρινό όριο Google Sheets — οι ρυθμίσεις (π.χ. ταμείο) "
                  "ίσως δείχνουν προηγούμενη τιμή για λίγο.")
        return {}

    out = {}
    for row in (vals or [])[1:]:          # παράλειψε την επικεφαλίδα
        if row and row[0]:
            out[row[0]] = row[1] if len(row) > 1 else ""
    return out


def load_setting(key: str, default: str = "") -> str:
    """Διαβάζει μια ρύθμιση από το cached dict. Default αν λείπει."""
    return _load_settings().get(key, default)


# Για το clear_all_caches() — ώστε να μπορεί να γράψει load_setting.clear().
load_setting.clear = _load_settings.clear  # type: ignore[attr-defined]


def save_setting(key: str, value: str) -> bool:
    """
    Γράφει μια ρύθμιση (ενημερώνει αν υπάρχει, προσθέτει αν λείπει).

    ΚΡΙΣΙΜΟ: μετά την εγγραφή καθαρίζει το cache ρυθμίσεων. Αλλιώς θα έγραφες
    νέο ταμείο, θα γινόταν rerun, και θα διάβαζες την ΠΑΛΙΑ cached τιμή.
    """
    try:
        ws = _settings_ws()
        rows = ws.get_all_values()
        for i, row in enumerate(rows[1:], start=2):   # 1-indexed, μετά την επικεφαλίδα
            if row and row[0] == key:
                ws.update_cell(i, 2, str(value))
                _load_settings.clear()
                return True
        # Δεν υπάρχει — πρόσθεσέ το
        ws.append_row([key, str(value)], table_range="A1")
        _load_settings.clear()
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ΑΡΙΘΜΟΙ — ελληνικό locale
# ══════════════════════════════════════════════════════════════════════════════
def parse_number(x) -> float:
    """
    Δέχεται οτιδήποτε, επιστρέφει float.
    Χειρίζεται: 1547.73 · "1547,73" · "1.547,73" · "1,547.73" · "1547,73 €"
    """
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return 0.0 if pd.isna(x) else float(x)

    s = str(x).replace("€", "").replace(" ", "").replace("\xa0", "").strip()
    if not s:
        return 0.0

    if "," in s and "." in s:
        # Ό,τι είναι πιο δεξιά, είναι το δεκαδικό.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")

    try:
        return float(s)
    except ValueError:
        return 0.0


def to_cents(v) -> int:
    """Ευρώ → λεπτά. Έτσι γράφουμε ΠΑΝΤΑ στο Sheet."""
    return int(round(parse_number(v) * CENTS))


def from_cents(v) -> float:
    """Λεπτά → ευρώ. Έτσι διαβάζουμε ΠΑΝΤΑ από το Sheet."""
    return parse_number(v) / CENTS


# ══════════════════════════════════════════════════════════════════════════════
# ΚΟΙΝΟ ΔΙΑΒΑΣΜΑ — ΟΛΑ ΤΑ ΦΥΛΛΑ ΜΕ ΜΙΑ ΚΛΗΣΗ (batch)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def _load_all_sheets() -> dict:
    """
    Διαβάζει sales + invoices + timologiseis με ΜΙΑ κλήση στο API.

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΓΙΑΤΙ ΑΥΤΟ ΛΥΝΕΙ ΤΟ 429                                                 │
    │                                                                        │
    │ Πριν: load_sales() + load_invoices() + load_timologiseis() = 3 ξεχωρι- │
    │ στές κλήσεις get_all_values(), η καθεμία σε κάθε φόρτωμα σελίδας.       │
    │                                                                        │
    │ Τώρα: ΜΙΑ κλήση values_batch_get για όλα τα εύρη μαζί. Το Sheets API    │
    │ τη μετράει ως μία ανάγνωση. 3 → 1.                                      │
    │                                                                        │
    │ Το cache (ttl=600) είναι ΚΟΙΝΟ: οι τρεις loaders τραβάνε από εδώ, άρα  │
    │ ένα μόνο «κλειδί» στη μνήμη, ένα refresh κάθε 10 λεπτά.                 │
    └────────────────────────────────────────────────────────────────────────┘

    → {"sales": [[...]], "invoices": [[...]], "timologiseis": [[...]]}
      (ωμές λίστες γραμμών, ΜΕ την κεφαλίδα — ώστε το _row = index+2 να ισχύει)
    """
    ranges = [f"{SHEET_SALES}!A:D", f"{SHEET_INV}!A:D", f"{SHEET_TIMOL}!A:G"]

    def _fetch():
        # values_batch_get: μία κλήση, πολλά εύρη. Επιστρέφει τις τιμές με τη
        # σειρά που ζητήθηκαν.
        resp = _spreadsheet().values_batch_get(ranges)
        return [vr.get("values", []) for vr in resp.get("valueRanges", [])]

    try:
        sales_v, inv_v, timol_v = _with_retry(_fetch)
    except Exception as e:  # noqa: BLE001
        _warn(f"Δεν φόρτωσαν τα δεδομένα: {e}")
        return {"sales": [], "invoices": [], "timologiseis": []}

    return {"sales": sales_v, "invoices": inv_v, "timologiseis": timol_v}


def _clear_all() -> None:
    """Καθαρίζει το κοινό cache ανάγνωσης. Το καλούν όλα τα merge/delete."""
    _load_all_sheets.clear()


# ══════════════════════════════════════════════════════════════════════════════
# ΠΩΛΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_sales() -> pd.DataFrame:
    """→ DataFrame[date, net_sales, customers, avg_basket] — ποσά σε ΕΥΡΩ."""
    vals = _load_all_sheets().get("sales", [])

    if len(vals) < 2:
        return pd.DataFrame(columns=SALES_COLS)

    rows = [
        (r[0], r[1],
         r[2] if len(r) > 2 else "",
         r[3] if len(r) > 3 else "")
        for r in vals[1:] if len(r) >= 2 and r[0]
    ]
    del vals
    if not rows:
        return pd.DataFrame(columns=SALES_COLS)

    df = pd.DataFrame(rows, columns=SALES_COLS)
    del rows

    df["date"]       = pd.to_datetime(df["date"], errors="coerce")
    df["net_sales"]  = df["net_sales"].map(from_cents)
    df["customers"]  = pd.to_numeric(df["customers"], errors="coerce")
    df["avg_basket"] = df["avg_basket"].map(from_cents)

    df = df.dropna(subset=["date", "net_sales"])
    df = df[df["net_sales"] > 0]
    df = df.sort_values("date", ascending=False).reset_index(drop=True)

    for c in ("net_sales", "customers", "avg_basket"):
        df[c] = df[c].astype("float32")

    return df


def merge_sales(records: list) -> int:
    """Προσθέτει μόνο ΝΕΕΣ ημερομηνίες. Idempotent."""
    if not records:
        return 0

    ws = _ws(SHEET_SALES)
    existing = {str(r[0]).strip() for r in _get_all(ws)[1:] if r and r[0]}

    new_rows = []
    for rec in records:
        d = rec.get("date")
        if not d:
            continue
        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        if d_str in existing:
            continue
        existing.add(d_str)

        cust = rec.get("customers")
        avg  = rec.get("avg_basket")
        new_rows.append([
            d_str,
            to_cents(rec.get("net_sales", 0)),
            int(cust) if cust else "",
            to_cents(avg) if avg else "",
        ])

    if new_rows:
        _append(ws, new_rows)
        _sort_by_date(ws, cols="A:D")
        load_sales.clear(); _clear_all()

    return len(new_rows)


def update_sales(target_date, net_sales=None, customers=None, avg_basket=None) -> tuple[bool, str]:
    """Διορθώνει μια υπάρχουσα ημέρα."""
    d_str = target_date.strftime("%Y-%m-%d") if hasattr(target_date, "strftime") else str(target_date)[:10]
    ws = _ws(SHEET_SALES)

    row_idx = None
    for i, r in enumerate(ws.get_all_values()[1:], start=2):
        if r and str(r[0]).strip() == d_str:
            row_idx = i
            break

    if row_idx is None:
        return False, f"Η {d_str} δεν βρέθηκε."

    if net_sales is not None:
        ws.update_cell(row_idx, 2, to_cents(net_sales))
    if customers is not None:
        ws.update_cell(row_idx, 3, int(customers))
    if avg_basket is not None:
        ws.update_cell(row_idx, 4, to_cents(avg_basket))

    load_sales.clear(); _clear_all()
    return True, f"Η {d_str} ενημερώθηκε."


# ══════════════════════════════════════════════════════════════════════════════
# ΠΑΡΑΣΤΑΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, max_entries=1, show_spinner=False)
def load_invoices() -> pd.DataFrame:
    """
    → DataFrame[date, type, value, number, _row] — ποσά σε ΕΥΡΩ.

    Η στήλη `number` είναι ο ΑΡΙΘΜΟΣ ΠΑΡΑΣΤΑΤΙΚΟΥ — η μοναδική ταυτότητα.
    Η `_row` είναι η γραμμή στο Sheet, για διαγραφές.

    ΣΥΜΒΑΤΟΤΗΤΑ: τα παλιά δεδομένα έχουν μόνο 3 στήλες (χωρίς αριθμό).
    Δεν σπάμε — τα διαβάζουμε με κενό number. Ο έλεγχος ξέρει να τα ξεχωρίζει.
    """
    cols = INV_COLS + ["_row"]
    vals = _load_all_sheets().get("invoices", [])

    if len(vals) < 2:
        return pd.DataFrame(columns=cols)

    rows = [
        (r[0], r[1], r[2],
         r[3] if len(r) > 3 else "",   # number — κενό στα παλιά
         i)
        for i, r in enumerate(vals[1:], start=2)
        if len(r) >= 3 and r[0]
    ]
    del vals
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows, columns=cols)
    del rows

    df["date"]   = pd.to_datetime(df["date"], errors="coerce")
    df["type"]   = df["type"].astype(str).str.strip()
    df["value"]  = df["value"].map(from_cents).astype("float32")
    df["number"] = df["number"].astype(str).str.strip()

    df = df.dropna(subset=["date"])
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df


def _invoice_id(number: str) -> str:
    """
    Η ΤΑΥΤΟΤΗΤΑ ενός παραστατικού = ο αριθμός του. Τίποτε άλλο.

    Δεν χρειάζεται ημερομηνία ούτε ποσό. Ο αριθμός 9315755320 είναι μοναδικός
    στο σύστημα της ΑΒ — αν εμφανιστεί δεύτερη φορά, είναι διπλοκαταχώρηση.
    """
    return str(number or "").strip()


def _legacy_key(d, t, cents: int) -> str:
    """
    Εφεδρικό κλειδί, ΜΟΝΟ για τα παλιά δεδομένα που δεν έχουν αριθμό.

    Είναι ασθενές — δεν ξεχωρίζει δύο πραγματικά τιμολόγια ίδιου ποσού. Γι' αυτό
    χρησιμοποιείται μόνο για να μη ξαναγραφτούν παλιές εγγραφές, ΠΟΤΕ για διαγραφή.
    """
    d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10].strip()
    t_str = str(t or "").strip().upper()
    return f"~{d_str}|{t_str}|{int(cents)}"


def _key_from_sheet(row: list) -> str:
    """Γραμμή Sheet → κλειδί. Αν έχει αριθμό, τον χρησιμοποιεί."""
    number = row[3] if len(row) > 3 else ""
    if _invoice_id(number):
        return _invoice_id(number)

    # Παλιά εγγραφή χωρίς αριθμό → εφεδρικό κλειδί
    cents = int(parse_number(row[2] if len(row) > 2 else 0))
    return _legacy_key(row[0], row[1] if len(row) > 1 else "", cents)


def _key_from_record(rec: dict) -> str:
    """Εγγραφή parser → κλειδί."""
    number = rec.get("number", "")
    if _invoice_id(number):
        return _invoice_id(number)

    return _legacy_key(rec.get("date"), rec.get("type", ""), to_cents(rec.get("value", 0)))


def merge_invoices(records: list) -> int:
    """Προσθέτει μόνο ό,τι δεν υπάρχει. Κλειδί: ο ΑΡΙΘΜΟΣ ΠΑΡΑΣΤΑΤΙΚΟΥ."""
    if not records:
        return 0

    ws = _ws(SHEET_INV)
    _ensure_number_column(ws)

    existing = {
        _key_from_sheet(r)
        for r in _get_all(ws)[1:] if len(r) >= 3 and r[0]
    }

    new_rows = []
    for rec in records:
        d = rec.get("date")
        if d is None or (isinstance(d, float) and pd.isna(d)):
            continue

        key = _key_from_record(rec)
        if key in existing:
            continue
        existing.add(key)

        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        new_rows.append([
            d_str,
            str(rec.get("type", "")).strip(),
            to_cents(rec.get("value", 0)),
            str(rec.get("number", "")).strip(),
        ])

    if new_rows:
        _append(ws, new_rows)
        load_invoices.clear(); _clear_all()

    return len(new_rows)


def _ensure_number_column(ws) -> None:
    """
    Προσθέτει τη στήλη D («number») αν λείπει.

    Το παλιό φύλλο έχει 3 στήλες. Δεν πειράζουμε τα δεδομένα — απλώς
    προσθέτουμε την κεφαλίδα, ώστε οι νέες εγγραφές να έχουν πού να γράψουν.
    """
    try:
        header = ws.row_values(1)
        if len(header) < 4 or str(header[3]).strip().lower() != "number":
            ws.update_cell(1, 4, "number")
    except Exception:
        pass


def purge_duplicate_invoices() -> tuple[int, int, int]:
    """
    Σβήνει ΜΟΝΟ όσα έχουν τον ΙΔΙΟ ΑΡΙΘΜΟ ΠΑΡΑΣΤΑΤΙΚΟΥ. Κρατάει την πρώτη εμφάνιση.

    → (σβήστηκαν, έμειναν, παραλείφθηκαν_χωρίς_αριθμό)

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΤΙ ΣΒΗΝΕΤΑΙ ΚΑΙ ΤΙ ΟΧΙ                                                 │
    │                                                                        │
    │  ✓ Ίδιος αριθμός 2+ φορές  → διπλοκαταχώρηση. Σβήνεται με ασφάλεια.    │
    │                                                                        │
    │  ✗ Ίδιο ποσό, άλλος αριθμός → ΔΥΟ ΠΡΑΓΜΑΤΙΚΑ ΤΙΜΟΛΟΓΙΑ. Μένουν.        │
    │                                                                        │
    │  ✗ Χωρίς αριθμό (παλιά δεδομένα) → ΔΕΝ ΤΑ ΑΓΓΙΖΟΥΜΕ. Δεν ξέρουμε αν    │
    │    είναι διπλά ή όχι, και μια λάθος διαγραφή αφαιρεί πραγματικά λεφτά. │
    └────────────────────────────────────────────────────────────────────────┘

    ΣΕΙΡΑ ΔΙΑΓΡΑΦΗΣ: από κάτω προς τα πάνω. Αν σβήσεις πρώτα τη γραμμή 100, όλες
    οι από κάτω μετακινούνται μία θέση πάνω και οι αριθμοί που κρατάς γίνονται
    λάθος. Ανάποδα, οι πάνω δεν κουνιούνται.
    """
    ws = _ws(SHEET_INV)
    vals = _get_all(ws)

    if len(vals) < 3:
        return 0, max(0, len(vals) - 1), 0

    seen = set()
    doomed = []
    no_number = 0

    for i, r in enumerate(vals[1:], start=2):
        if len(r) < 3 or not r[0]:
            continue

        number = _invoice_id(r[3] if len(r) > 3 else "")

        if not number:
            no_number += 1     # παλιά εγγραφή — δεν την αγγίζουμε
            continue

        if number in seen:
            doomed.append(i)
        else:
            seen.add(number)

    if not doomed:
        return 0, len(seen), no_number

    for start, end in reversed(_group_runs(doomed)):
        _delete(ws, start, end)

    load_invoices.clear(); _clear_all()
    return len(doomed), len(seen), no_number


def find_duplicate_numbers(df: pd.DataFrame) -> list[dict]:
    """
    🔁 ΔΙΠΛΟΚΑΤΑΧΩΡΗΣΗ — ο ΙΔΙΟΣ αριθμός παραστατικού, πάνω από μία φορά.

    Ο ΑΡΙΘΜΟΣ ΠΑΡΑΣΤΑΤΙΚΟΥ είναι ΜΟΝΑΔΙΚΟΣ. Αν εμφανίζεται 2+ φορές, τότε το ίδιο
    ακριβώς παραστατικό καταχωρήθηκε πολλές φορές — σίγουρη διπλοκαταχώρηση.

    Αυτό είναι διαφορετικό από το find_double_charges():
      • Ίδιος αριθμός    → ΣΙΓΟΥΡΗ διπλοκαταχώρηση (εδώ)   → σβήσε τις παραπανίσιες
      • Άλλος αριθμός    → ίδιο ποσό, πιθανό λάθος προμηθευτή → ΜΗΝ σβήνεις

    → [{"number", "type", "value", "count", "rows": [...], "dates": [...]}, ...]
    """
    if df.empty or "number" not in df.columns:
        return []

    d = df[df["number"].astype(str).str.strip() != ""].copy()
    if d.empty:
        return []

    out = []
    for number, g in d.groupby("number"):
        if len(g) < 2:
            continue

        rows = sorted(int(x) for x in g["_row"].tolist()) if "_row" in g else []
        dates = sorted(g["date"].dt.strftime("%d/%m/%Y").tolist())

        out.append({
            "number": str(number),
            "type": str(g["type"].iloc[0]),
            "value": float(g["value"].iloc[0]),
            "count": len(g),
            "rows": rows,
            "dates": dates,
        })

    # Οι πιο ακριβές διπλοκαταχωρήσεις πρώτα — εκεί «πονάει» περισσότερο.
    out.sort(key=lambda x: (x["count"] - 1) * abs(x["value"]), reverse=True)
    return out


# ══════════════════════════════════════════════════════════════════════════════
def find_double_charges(df: pd.DataFrame) -> list[dict]:
    """
    ⚠️ ΔΙΠΛΗ ΧΡΕΩΣΗ — άλλο πράγμα από τη διπλοκαταχώρηση.

    Ψάχνει παραστατικά με ΔΙΑΦΟΡΕΤΙΚΟ αριθμό αλλά ίδια μέρα, τύπο και ποσό.

    Αυτό ΔΕΝ είναι σφάλμα του συστήματος — είναι πιθανό σφάλμα του ΠΡΟΜΗΘΕΥΤΗ:
    σου έκοψε δύο φορές το ίδιο τιμολόγιο, με δύο διαφορετικούς αριθμούς.

    Δεν σβήνεται ποτέ αυτόματα. Θέλει τηλέφωνο στην ΑΒ.

    → [{"date", "type", "value", "numbers": [...], "rows": [...]}, ...]
    """
    if df.empty or "number" not in df.columns:
        return []

    d = df[df["number"].astype(str).str.strip() != ""].copy()
    if d.empty:
        return []

    d["_d"] = d["date"].dt.strftime("%Y-%m-%d")
    d["_v"] = d["value"].round(2)

    out = []
    for (dt, tp, v), g in d.groupby(["_d", "type", "_v"]):
        if len(g) < 2:
            continue
        if float(v) == 0:      # τα μηδενικά είναι συνηθισμένα, δεν είναι χρέωση
            continue

        out.append({
            "date": dt,
            "type": tp,
            "value": float(v),
            "count": len(g),
            "numbers": sorted(g["number"].tolist()),
            "rows": sorted(int(x) for x in g["_row"].tolist()),
        })

    out.sort(key=lambda x: (x["date"], -x["value"]), reverse=True)
    return out


def find_repeated_amounts(df: pd.DataFrame, within_days: int = 60) -> list[dict]:
    """
    🔁 ΙΔΙΟ ΠΟΣΟ ΣΕ ΔΙΑΦΟΡΕΤΙΚΕΣ ΜΕΡΕΣ — πιθανή διπλή παραγγελία.

    Ψάχνει παραστατικά με ΑΚΡΙΒΩΣ το ίδιο ποσό αλλά ΔΙΑΦΟΡΕΤΙΚΗ ημερομηνία,
    που απέχουν το πολύ `within_days` μέρες.

    Το σκεπτικό: αν η ίδια παραγγελία τιμολογηθεί δύο φορές (π.χ. λάθος του
    προμηθευτή, ή διπλή καταχώρηση παραγγελίας), το ΠΟΣΟ θα είναι ίδιο, αλλά
    σε άλλη μέρα. Δεν είναι το ίδιο με τις «διπλές χρεώσεις» (ίδια μέρα) —
    εδώ κοιτάμε ΑΝΑ ΔΙΑΣΤΗΜΑ.

    ΔΕΝ ΣΒΗΝΕΤΑΙ ΠΟΤΕ. Δύο τιμολόγια των 1.725,08 € σε διαφορετικές βδομάδες
    μπορεί κάλλιστα να είναι δύο κανονικές, ξεχωριστές παραγγελίες. Μόνο εσύ
    ξέρεις — το εργαλείο απλώς τα φέρνει μπροστά σου για έλεγχο.

    → [{
         "value": float,
         "count": int,                    # πόσες φορές εμφανίζεται το ποσό
         "dates": [date, ...],            # οι ημερομηνίες, ταξινομημένες
         "numbers": [str, ...],           # οι αριθμοί παραστατικών
         "rows": [int, ...],              # γραμμές στο Sheet
         "max_gap": int,                  # μέγιστη απόσταση σε μέρες
         "min_gap": int,                  # ελάχιστη απόσταση (τα πιο κοντινά)
       }, ...]
    Ταξινομημένο: πρώτα τα πιο ύποπτα (κοντινές μέρες, μεγάλα ποσά).
    """
    if df.empty or "number" not in df.columns:
        return []

    # Μόνο γραμμές με αριθμό (οι αριθμημένες είναι αξιόπιστες).
    d = df[df["number"].astype(str).str.strip() != ""].copy()
    if d.empty:
        return []

    d["_v"] = d["value"].round(2)

    out = []
    for v, g in d.groupby("_v"):
        if float(v) == 0:            # τα μηδενικά (πιστωτικά κ.λπ.) δεν μας νοιάζουν
            continue
        if len(g) < 2:               # χρειάζονται τουλάχιστον δύο για σύγκριση
            continue

        # Ημερομηνίες, ταξινομημένες
        dates = sorted(
            (x.date() if hasattr(x, "date") else x)
            for x in g["date"].tolist()
        )

        # Υπάρχει έστω ΕΝΑ ζευγάρι μέσα στο παράθυρο; Και ποιο το πιο κοντινό;
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        if not gaps:
            continue

        min_gap = min(gaps)
        # Αν ακόμη και το πιο κοντινό ζευγάρι απέχει πάνω από within_days,
        # δεν είναι ύποπτο — μάλλον σύμπτωση σε διαφορετικές εποχές.
        if min_gap == 0 or min_gap > within_days:
            continue

        # Συνολικό εύρος (πρώτη → τελευταία)
        max_gap = (dates[-1] - dates[0]).days

        out.append({
            "value": float(v),
            "count": len(g),
            "dates": dates,
            "numbers": sorted(g["number"].astype(str).tolist()),
            "rows": sorted(int(x) for x in g["_row"].tolist()) if "_row" in g else [],
            "max_gap": max_gap,
            "min_gap": min_gap,
        })

    # Πιο ύποπτα πρώτα: κοντινές μέρες, μετά μεγάλα ποσά.
    out.sort(key=lambda x: (x["min_gap"], -x["value"]))
    return out



@st.cache_data(ttl=300, max_entries=1, show_spinner=False)
def load_timologiseis() -> pd.DataFrame:
    """
    → DataFrame[check_date, period, amount, check_number, expenses, voucher, sent_date, _row]
    Η στήλη _row είναι ο αριθμός γραμμής στο Sheet — χρειάζεται για edit/delete.
    """
    cols = TIMOL_COLS + ["_row"]
    vals = _load_all_sheets().get("timologiseis", [])

    if len(vals) < 2:
        return pd.DataFrame(columns=cols)

    rows = []
    for i, r in enumerate(vals[1:], start=2):
        if len(r) < 3 or not r[0]:
            continue
        rows.append((
            r[0],                              # check_date
            r[1] if len(r) > 1 else "",        # period
            r[2],                              # amount (cents)
            r[3] if len(r) > 3 else "",        # check_number
            r[4] if len(r) > 4 else "",        # expenses
            r[5] if len(r) > 5 else "",        # voucher — κενό στις παλιές γραμμές
            r[6] if len(r) > 6 else "",        # sent_date — πότε στάλθηκε το πακέτο
            i,                                 # _row
        ))
    del vals
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows, columns=cols)
    del rows

    df["check_date"]   = pd.to_datetime(df["check_date"], errors="coerce")
    df["amount"]       = df["amount"].map(from_cents).astype("float32")
    df["period"]       = df["period"].astype(str)
    df["check_number"] = df["check_number"].astype(str)
    df["expenses"]     = df["expenses"].astype(str)
    df["voucher"]      = df["voucher"].astype(str)
    df["sent_date"]    = df["sent_date"].astype(str)

    df = df.dropna(subset=["check_date"])
    df = df.sort_values("check_date", ascending=False).reset_index(drop=True)
    return df


def merge_timologiseis(records: list) -> int:
    """
    Κλειδί διπλότυπου: check_date + περίοδος (όχι ποσό).

    Η ίδια επιταγή μπορεί να έρθει σε δεύτερο email με άλλο ποσό (π.χ. η 22/06/2026:
    63.441,08 στο Sheet, 63.262,19 σε άλλο email). Με κλειδί το ποσό έμπαινε δεύτερη
    γραμμή για την ίδια επιταγή. Τώρα: ίδια μέρα + ίδια περίοδος = ίδια επιταγή,
    και κρατάμε ό,τι υπάρχει ήδη (μπορεί να το έχεις διορθώσει με το χέρι).
    """
    if not records:
        return 0

    ws = _ws(SHEET_TIMOL)

    def key(cd: str, period: str) -> str:
        # Η περίοδος γράφεται άλλοτε «12.10.2026 -20.10.2026», άλλοτε με κενά.
        return cd.strip() + "|" + "".join((period or "").split())

    existing = {
        key(str(r[0]), str(r[1]) if len(r) > 1 else "")
        for r in _get_all(ws)[1:] if r and r[0]
    }

    new_rows = []
    for rec in records:
        cd = rec.get("check_date")
        if not cd:
            continue
        cd_str = cd.strftime("%Y-%m-%d") if hasattr(cd, "strftime") else str(cd)[:10]
        v = to_cents(rec.get("amount", 0))

        k = key(cd_str, str(rec.get("period", "")))
        if k in existing:
            continue
        existing.add(k)
        new_rows.append([cd_str, str(rec.get("period", "")), v, "", ""])

    if new_rows:
        _append(ws, new_rows)
        load_timologiseis.clear(); _clear_all()

    # Οι αγορές ανά ημέρα (γραμμές του Excel) πάνε στο φύλλο «agores» — ΚΑΙ για
    # τις επιταγές που υπήρχαν ήδη (έτσι γεμίζει και το παρελθόν). Δευτερεύον:
    # αν αποτύχει, οι τιμολογήσεις έχουν ήδη γραφτεί.
    try:
        merge_agores(records)
    except Exception as e:  # noqa: BLE001
        print(f"  ! Αγορές ανά ημέρα: {e}")

    return len(new_rows)


def update_timologiseis_field(row: int, field: str, value: str) -> bool:
    """Γράφει check_number (στήλη D), expenses (E), voucher (F) ή sent_date (G)."""
    col = {"check_number": 4, "expenses": 5, "voucher": 6, "sent_date": 7}.get(field)
    if not col or not row:
        return False
    try:
        ws = _ws(SHEET_TIMOL)
        # Το φύλλο μπορεί να έχει μόνο 5 στήλες (η F είναι νέα) — αλλιώς το
        # update_cell αποτυγχάνει με «exceeds grid limits».
        if col > ws.col_count:
            ws.add_cols(col - ws.col_count)
        # Οι νέες στήλες δεν έχουν ακόμα επικεφαλίδα: τη γράφουμε μία φορά.
        header = (_load_all_sheets().get("timologiseis") or [[]])[0]
        for c in range(max(len(header) + 1, 6), col + 1):
            ws.update_cell(1, c, TIMOL_COLS[c - 1])
        if field in ("voucher", "sent_date"):
            # RAW: το Sheet να κρατήσει ΑΚΡΙΒΩΣ ό,τι γράφτηκε. Αλλιώς ένα voucher
            # «00123» γίνεται αριθμός 123 και η ημερομηνία αλλάζει μορφή.
            a1 = gspread.utils.rowcol_to_a1(int(row), col)
            ws.update([[str(value or "")]], a1, raw=True)
        else:
            ws.update_cell(int(row), col, str(value or ""))
        load_timologiseis.clear(); _clear_all()
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ΑΓΟΡΕΣ ΑΝΑ ΗΜΕΡΑ (από τις γραμμές των Excel τιμολόγησης)
# ══════════════════════════════════════════════════════════════════════════════
SHEET_AGORES = "agores"
AGORES_COLS = ["date", "amount", "check_date"]


def _agores_ws():
    """Το φύλλο «agores» (date | amount σε λεπτά | check_date). Αν λείπει, το φτιάχνει."""
    ss = _spreadsheet()
    try:
        return ss.worksheet(SHEET_AGORES)
    except Exception:
        ws = ss.add_worksheet(title=SHEET_AGORES, rows=1000, cols=3)
        ws.update([AGORES_COLS], "A1")
        return ws


@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_agores() -> pd.DataFrame:
    """
    → DataFrame[date, amount, check_date] — οι αγορές κάθε ημέρας, όπως τις
    γράφουν τα Excel τιμολόγησης (άθροισμα όλων των παραστατικών της ημέρας).
    Κενό DataFrame αν δεν υπάρχει ακόμη το φύλλο ή δεν διαβάζεται.
    """
    try:
        vals = _with_retry(lambda: _agores_ws().get_all_values())
    except Exception:
        return pd.DataFrame(columns=AGORES_COLS)
    rows = [r[:3] for r in (vals or [])[1:] if len(r) >= 3 and r[0]]
    if not rows:
        return pd.DataFrame(columns=AGORES_COLS)
    df = pd.DataFrame(rows, columns=AGORES_COLS)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["check_date"] = pd.to_datetime(df["check_date"], errors="coerce")
    df["amount"] = df["amount"].map(from_cents).astype(float)
    return df.dropna(subset=["date"])


def merge_agores(records: list) -> int:
    """
    Γράφει τις αγορές ανά ημέρα από Excel τιμολόγησης (parse_timologisi_daily).

    Κλειδί: η ΕΠΙΤΑΓΗ (check_date). Αν μια επιταγή έχει ήδη γραμμές, δεν
    ξαναγράφεται — έτσι το ίδιο Excel σε δεύτερο email δεν διπλασιάζει τις αγορές.
    → πόσες ΕΠΙΤΑΓΕΣ προστέθηκαν.
    """
    recs = [r for r in records if r and r.get("daily") and r.get("check_date")]
    if not recs:
        return 0
    ws = _agores_ws()
    have = {str(r[2]).strip() for r in _get_all(ws)[1:] if len(r) >= 3 and r[2]}

    rows, added = [], 0
    for rec in sorted(recs, key=lambda r: r["check_date"]):
        cd = rec["check_date"].strftime("%Y-%m-%d")
        if cd in have:
            continue
        have.add(cd)
        added += 1
        for d, v in sorted(rec["daily"].items()):
            rows.append([d.strftime("%Y-%m-%d"), to_cents(v), cd])

    if rows:
        _append(ws, rows)
        load_agores.clear()
    return added


# ══════════════════════════════════════════════════════════════════════════════
# ΠΑΓΙΑ ΕΞΟΔΑ (από τα email του λογιστή — core/pagia.py)
# ══════════════════════════════════════════════════════════════════════════════
SHEET_PAGIA = "pagia"
# «sub»: φορέας (ΕΦΚΑ/ΤΕΚΑ), εταίρος, ή είδος δώρου — βλ. core/pagia.py.
# «emps»: «κωδικός:λεπτά» ανά εργαζόμενο — για να μη μετρηθεί κανείς δύο φορές.
# «source»: θέμα email · αρχεία · «check»: αποτέλεσμα ελέγχων — για τις «Λεπτομέρειες μήνα».
PAGIA_COLS = ["kind", "ref", "sub", "amount", "pay_date", "detail", "email_date", "emps",
              "source", "check"]

# Μισθοδοσίες ΑΝΑ ΕΡΓΑΖΟΜΕΝΟ (για τον φάκελο του κάθε υπαλλήλου στο HR).
# «code» = κωδικός λογιστηρίου (κενό αν το αρχείο είχε μόνο IBAN/λογαριασμό —
# συμπληρώνεται μόνο του μόλις γίνει γνωστό από άλλο αρχείο).
SHEET_MISTH = "misthodosies"
MISTH_COLS = ["code", "iban", "name", "kind", "ref", "sub", "amount", "pay_date", "email_date"]


def _reset_ws(title: str, cols: list):
    """
    Φύλλο που ΦΤΙΑΧΝΕΙ η εφαρμογή από τα email. Αν λείπει, το δημιουργεί· αν η
    κεφαλίδα δεν είναι η τρέχουσα (άλλαξε η μορφή), το ΚΑΘΑΡΙΖΕΙ ώστε να
    ξαναγεμίσει από τα email — δεν χάνεται τίποτα που έγραψε ο χρήστης.
    """
    ss = _spreadsheet()
    try:
        ws = ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=1000, cols=len(cols))
        ws.update([cols], "A1")
        return ws
    head = (ws.row_values(1) or [])[:len(cols)]
    if head != cols:
        ws.clear()
        if ws.col_count < len(cols):
            ws.add_cols(len(cols) - ws.col_count)
        ws.update([cols], "A1")
    return ws


def _pagia_ws():
    return _reset_ws(SHEET_PAGIA, PAGIA_COLS)


# Μισθοδοσίες που γράφονται ΑΝΑ ΕΡΓΑΖΟΜΕΝΟ (τα υπόλοιπα είναι ένα ποσό).
_PER_EMP_KINDS = ("Μισθοδοσία", "Δώρα/Επιδόματα", "Συμπληρωματική")

# Αναφορά ανάκτησης: μία γραμμή ανά email του λογιστή (τι αρχεία είχε, τι βρέθηκε).
SHEET_PAGIA_LOG = "pagia_log"
PAGIA_LOG_COLS = ["email_date", "subject", "files", "found", "notes", "run_at"]


def _pagia_log_ws():
    return _reset_ws(SHEET_PAGIA_LOG, PAGIA_LOG_COLS)


def append_pagia_log(entries: list) -> int:
    """Γράφει γραμμές αναφοράς (dict με τα PAGIA_LOG_COLS)."""
    if not entries:
        return 0
    rows = [[str(e.get(c, "") or "")[:5000] for c in PAGIA_LOG_COLS] for e in entries]
    _append(_pagia_log_ws(), rows)
    load_pagia_log.clear()
    return len(rows)


@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_pagia_log() -> pd.DataFrame:
    try:
        vals = _with_retry(lambda: _pagia_log_ws().get_all_values())
    except Exception:
        return pd.DataFrame(columns=PAGIA_LOG_COLS)
    n = len(PAGIA_LOG_COLS)
    rows = [(r + [""] * n)[:n] for r in (vals or [])[1:] if r and any(r)]
    return pd.DataFrame(rows, columns=PAGIA_LOG_COLS)


def reset_pagia_sheets() -> list:
    """
    ΑΔΕΙΑΖΕΙ τα φύλλα «pagia», «misthodosies», «pagia_log» (κρατά την κεφαλίδα)
    για ανάκτηση από την αρχή. Είναι φύλλα που φτιάχνει ΜΟΝΟ η εφαρμογή από τα
    email — τίποτα δεν έχει γράψει ο χρήστης. Δεν αγγίζει κανένα άλλο φύλλο.
    """
    done = []
    for title, cols in ((SHEET_PAGIA, PAGIA_COLS), (SHEET_MISTH, MISTH_COLS),
                        (SHEET_PAGIA_LOG, PAGIA_LOG_COLS)):
        ws = _reset_ws(title, cols)
        _with_retry(lambda w=ws: w.clear())
        _with_retry(lambda w=ws, c=cols: w.update([c], "A1"))
        done.append(title)
    load_pagia.clear()
    load_misthodosies.clear()
    load_pagia_log.clear()
    return done


def _misth_ws():
    return _reset_ws(SHEET_MISTH, MISTH_COLS)


@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_pagia() -> pd.DataFrame:
    """→ DataFrame[PAGIA_COLS] (κενό αν δεν υπάρχει)."""
    try:
        vals = _with_retry(lambda: _pagia_ws().get_all_values())
    except Exception:
        return pd.DataFrame(columns=PAGIA_COLS)
    n = len(PAGIA_COLS)
    rows = [(r + [""] * n)[:n] for r in (vals or [])[1:] if r and r[0]]
    if not rows:
        return pd.DataFrame(columns=PAGIA_COLS)
    df = pd.DataFrame(rows, columns=PAGIA_COLS)
    df["amount"] = df["amount"].map(from_cents).astype(float)
    df["pay_date"] = pd.to_datetime(df["pay_date"], errors="coerce")
    df["email_date"] = pd.to_datetime(df["email_date"], errors="coerce")
    return df


def _emp_maps(rows: list) -> tuple[dict, dict]:
    """
    Από τις γραμμές του «misthodosies»: IBAN/λογαριασμός → κωδικός, και
    όνομα → κωδικός (μόνο όπου το όνομα δείχνει ΕΝΑΝ κωδικό).
    """
    from core.parsers import norm_greek
    by_acct, by_name = {}, {}
    for r in rows:
        code, acct, nm = r[0].strip(), r[1].strip().upper(), r[2]
        if not code:
            continue
        if acct:
            by_acct[acct] = code
        key = " ".join(norm_greek(nm).replace("-", " ").split()[:2])
        if key:
            by_name.setdefault(key, set()).add(code)
    return by_acct, {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1}


def _resolve(acct: str, name: str, by_acct: dict, by_name: dict) -> str:
    """Κωδικός για γραμμή χωρίς κωδικό: ίδιο IBAN → ίδιος λογαριασμός (τα τελευταία
    ψηφία του IBAN) → ίδιο ονοματεπώνυμο. Αλλιώς κενό (μένει για αργότερα)."""
    from core.parsers import norm_greek
    acct = (acct or "").strip().upper()
    if acct in by_acct:
        return by_acct[acct]
    digits = re.sub(r"\D", "", acct).lstrip("0")
    if len(digits) >= 8 and not acct.startswith("GR"):
        hits = {c for a, c in by_acct.items() if re.sub(r"\D", "", a).endswith(digits)}
        if len(hits) == 1:
            return hits.pop()
    key = " ".join(norm_greek(name or "").replace("-", " ").split()[:2])
    return by_name.get(key, "")


def load_emp_map() -> dict:
    """IBAN → κωδικός, από όσες μισθοδοσίες έχουν ήδη γραφτεί (για τα CSV χωρίς κωδικό)."""
    try:
        rows = [(r + [""] * 3)[:3] for r in _get_all(_misth_ws())[1:] if r]
    except Exception:
        return {}
    return {a: c for a, c in _emp_maps(rows)[0].items() if a.startswith("GR")}


def merge_pagia(records: list) -> int:
    """
    Γράφει μόνο ό,τι δεν υπάρχει — ίδιο κλειδί με το core.pagia.key().

    Μισθοδοσίες με εργαζόμενους: για κάθε πληρωμή (είδος + μήνας + δώρο) γράφονται
    ΜΟΝΟ οι εργαζόμενοι με ποσό που δεν υπάρχει ήδη (ίδιος κωδικός + ίδιο ποσό =
    ήδη μετρημένο). Οι ίδιοι γράφονται ΚΑΙ ανά εργαζόμενο στο «misthodosies».
    """
    from datetime import date as _date
    from core.pagia import key as pagia_key, _cents

    # ΑΑΔΕ με ημερομηνία κατάστασης: χωριστά (και τα σημάδια «καμία δόση», ποσό 0)
    aade = [r for r in records if r and r.get("kind") == "ΑΑΔΕ" and r.get("snap")]
    recs = [r for r in records if r and r.get("kind") and r.get("amount")
            and not (r.get("kind") == "ΑΑΔΕ" and r.get("snap"))]
    if not recs and not aade:
        return 0
    ws = _pagia_ws()
    wm = _misth_ws()
    mrows = [(r + [""] * len(MISTH_COLS))[:len(MISTH_COLS)] for r in _get_all(wm)[1:] if r]
    by_acct, by_name = _emp_maps(mrows)

    def canon(ident: str, who=("", "")) -> str:
        """Ίδιος άνθρωπος = ίδια ταυτότητα, είτε ήρθε με κωδικό είτε με IBAN."""
        if ident.startswith(("ΙΒΑΝ:", "ΛΟΓ:")):
            return _resolve(ident.split(":", 1)[1], who[1] if who else "", by_acct, by_name) or ident
        return ident

    n = len(PAGIA_COLS)
    have, emp_seen = set(), {}
    # Σκέτα σύνολα (μισθοδοτική χωρίς λίστα τράπεζας) ανά πληρωμή → γραμμές στο φύλλο.
    # Μόλις έρθουν οι εργαζόμενοι της ίδιας πληρωμής, το σκέτο σύνολο ΦΕΥΓΕΙ
    # (αλλιώς μετριέται δύο φορές).
    totals_at: dict[tuple, list] = {}
    aade_rows: list[dict] = []
    for idx, r in enumerate(_get_all(ws)[1:], start=2):
        if not r or not r[0]:
            continue
        r = (r + [""] * n)[:n]
        if r[0] == "ΑΑΔΕ":
            aade_rows.append({"idx": idx, "due": r[4], "snap": r[6], "row": None})
        if r[0] in _PER_EMP_KINDS and not r[7]:
            totals_at.setdefault((r[0], r[1], r[2]), []).append(idx)
        toks = [t for t in r[7].split(",") if ":" in t]
        if toks:
            seen = emp_seen.setdefault((r[0], r[1], r[2]), set())
            for t in toks:
                ident, cents = t.rsplit(":", 1)
                seen.add(f"{canon(ident)}:{cents}")
            continue
        try:
            pay = _date.fromisoformat(r[4]) if r[4] else None
        except ValueError:
            pay = None
        have.add(pagia_key({"kind": r[0], "ref": r[1], "sub": r[2],
                            "amount": from_cents(r[3]), "pay_date": pay}))
    rows, mnew, drop = [], [], []
    if aade:
        _merge_aade(aade, aade_rows, rows, drop)
    # Πρώτα όσα έχουν εργαζόμενους: έτσι ένα σκέτο σύνολο της ίδιας πληρωμής βρίσκει
    # ότι υπάρχουν ήδη και δεν γράφεται.
    for r in sorted(recs, key=lambda x: (x["ref"], x["kind"], x.get("sub", ""), not x.get("emps"))):
        emps = r.get("emps") or {}
        k3 = (r["kind"], r["ref"], str(r.get("sub", "")))
        pay = r["pay_date"].strftime("%Y-%m-%d") if r.get("pay_date") else ""
        sent = r.get("email_date")
        sent_s = sent.strftime("%Y-%m-%d") if sent else ""
        if emps:
            who = r.get("who") or {}
            done = emp_seen.setdefault((r["kind"], r["ref"], r.get("sub", "")), set())
            new = {}
            for ident, amt in emps.items():
                tok = f"{canon(ident, who.get(ident))}:{_cents(amt)}"
                if tok not in done:
                    done.add(tok)
                    new[ident] = amt
            if not new:
                continue
            for ident, amt in new.items():
                acct, nm = (who.get(ident) or ("", ""))
                code = ident if re.fullmatch(r"\d{4,6}", ident) else canon(ident, (acct, nm))
                code = code if re.fullmatch(r"\d{4,6}", code) else ""
                acct = acct or (ident.split(":", 1)[1] if ":" in ident else "")
                mnew.append([code, acct, nm, r["kind"], r["ref"], str(r.get("sub", "")),
                             to_cents(amt), pay, sent_s])
            r = {**r, "emps": new, "amount": round(sum(new.values()), 2)}
            drop += totals_at.pop(k3, [])          # το σκέτο σύνολο αντικαθίσταται
        elif r["kind"] in _PER_EMP_KINDS and emp_seen.get(k3):
            continue                               # υπάρχουν ήδη εργαζόμενοι → όχι και σύνολο
        else:
            k = pagia_key(r)
            if k in have:
                continue
            have.add(k)
        toks = ",".join(sorted(f"{i}:{_cents(a)}" for i, a in (r.get("emps") or {}).items()))
        rows.append([r["kind"], r["ref"], str(r.get("sub", "")), to_cents(r["amount"]), pay,
                     str(r.get("detail", ""))[:200], sent_s, toks,
                     str(r.get("source", ""))[:200], str(r.get("check", ""))[:400]])
    if rows:
        _append(ws, rows)
        load_pagia.clear()
    for idx in sorted(set(drop), reverse=True):    # από κάτω προς τα πάνω: σωστοί αριθμοί γραμμών
        _with_retry(lambda i=idx: ws.delete_rows(i))
        load_pagia.clear()
    if mnew:
        _append(wm, mnew)
        resolve_misthodosies(wm)
        load_misthodosies.clear()
    return len(rows)


def _merge_aade(aade: list, existing: list, rows: list, drop: list) -> None:
    """
    ΑΑΔΕ: κάθε κατάσταση «Οφειλές προς το Δημόσιο» είναι φωτογραφία της στιγμής S
    (ημερομηνία πληροφόρησης· γράφεται στη στήλη email_date).
      • Νεότερη κατάσταση → σβήνει τις δόσεις παλιότερων με λήξη ≥ S (αλλάζουν/κλείνουν).
      • Παλιότερη κατάσταση (π.χ. η ανάκτηση διαβάζει ανάποδα) → δεν γράφει δόσεις
        με λήξη ≥ της νεότερης που υπάρχει ήδη.
      • Ίδια κατάσταση ξανά → τίποτα. Ληξιπρόθεσμη δόση (λήξη < S) που υπάρχει ήδη → τίποτα.
    Η συνολική οφειλή της ΝΕΟΤΕΡΗΣ κατάστασης → ρύθμιση «aade_debt».
    """
    import json

    def iso(d):
        return d.strftime("%Y-%m-%d") if d else ""

    alive = [dict(e) for e in existing]
    groups: dict[str, list] = {}
    for r in aade:
        groups.setdefault(iso(r["snap"]), []).append(r)
    newest = None
    for snap in sorted(groups):
        newer = [e["snap"] for e in alive if e["snap"] > snap]
        cutoff = min(newer) if newer else None
        for e in [e for e in alive if e["snap"] < snap and e["due"] >= snap]:
            alive.remove(e)
            if e["row"] is not None:
                rows.remove(e["row"])
            else:
                drop.append(e["idx"])
        for r in groups[snap]:
            due = iso(r.get("pay_date"))
            if not due or not r.get("amount"):
                continue
            if cutoff and due >= cutoff:
                continue
            if any(e["due"] == due and e["snap"] == snap for e in alive):
                continue
            if due < snap and any(e["due"] == due for e in alive):
                continue
            row = ["ΑΑΔΕ", r["ref"], "", to_cents(r["amount"]), due, str(r.get("detail", ""))[:200],
                   snap, "", str(r.get("source", ""))[:200], ""]
            rows.append(row)
            alive.append({"idx": None, "due": due, "snap": snap, "row": row})
        debt = next((r.get("debt") for r in groups[snap] if r.get("debt")), None)
        if debt and not newer:
            newest = {"date": snap, **debt}
    if newest:
        try:
            old = json.loads(load_setting("aade_debt", "") or "{}")
        except ValueError:
            old = {}
        if newest["date"] >= str(old.get("date", "")):
            save_setting("aade_debt", json.dumps(newest))


def resolve_misthodosies(wm=None) -> int:
    """
    Γραμμές χωρίς κωδικό (παλιά Excel με μόνο λογαριασμό, CSV) → κωδικός από
    ό,τι έγινε γνωστό ΜΕΤΑ (IBAN / λογαριασμός / ονοματεπώνυμο). → πόσες βρέθηκαν.
    """
    wm = wm or _misth_ws()
    vals = _get_all(wm)
    rows = [(r + [""] * len(MISTH_COLS))[:len(MISTH_COLS)] for r in vals[1:]]
    by_acct, by_name = _emp_maps(rows)
    upd = []
    for i, r in enumerate(rows, start=2):
        if r[0] or not (r[1] or r[2]):
            continue
        code = _resolve(r[1], r[2], by_acct, by_name)
        if code:
            upd.append({"range": f"A{i}", "values": [[code]]})
    if upd:
        _with_retry(lambda: wm.batch_update(upd, value_input_option="RAW"))
    return len(upd)


@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_misthodosies() -> pd.DataFrame:
    """→ DataFrame[MISTH_COLS]: μία γραμμή ανά εργαζόμενο ανά πληρωμή."""
    try:
        vals = _with_retry(lambda: _misth_ws().get_all_values())
    except Exception:
        return pd.DataFrame(columns=MISTH_COLS)
    n = len(MISTH_COLS)
    rows = [(r + [""] * n)[:n] for r in (vals or [])[1:] if r and any(r)]
    df = pd.DataFrame(rows, columns=MISTH_COLS)
    if not df.empty:
        df["amount"] = df["amount"].map(from_cents).astype(float)
        df["pay_date"] = pd.to_datetime(df["pay_date"], errors="coerce")
    return df


def update_timologisi(row: int, old_check_date: str, check_date, period: str,
                      amount: float) -> tuple[bool, str]:
    """
    Χειροκίνητη διόρθωση μιας επιταγής: ημερομηνία (A), περίοδος (B), ποσό (C).

    ΑΣΦΑΛΕΙΑ: πριν γράψουμε, ξαναδιαβάζουμε τη γραμμή και ελέγχουμε ότι είναι
    ΑΚΟΜΑ η ίδια επιταγή (old_check_date). Αν στο μεταξύ μπήκε/σβήστηκε γραμμή
    και άλλαξε η αρίθμηση, ΔΕΝ γράφουμε — αλλιώς θα πειράζαμε λάθος επιταγή.
    """
    try:
        ws = _ws(SHEET_TIMOL)
        current = ws.row_values(int(row))
        if not current or str(current[0]).strip() != str(old_check_date).strip():
            return False, "Το Sheet άλλαξε στο μεταξύ — ανανέωσε τη σελίδα και ξαναδοκίμασε."
        cd = check_date.strftime("%Y-%m-%d") if hasattr(check_date, "strftime") else str(check_date)[:10]
        ws.update([[cd, str(period or ""), to_cents(amount)]], f"A{int(row)}:C{int(row)}", raw=True)
        load_timologiseis.clear(); _clear_all()
        return True, f"Η επιταγή {cd} ενημερώθηκε."
    except Exception as e:
        return False, f"Δεν ενημερώθηκε: {e}"


def delete_invoice_by_number(number: str) -> tuple[bool, str]:
    """
    Σβήνει ΕΝΑ παραστατικό με βάση τον αριθμό του (στήλη D).

    Ψάχνουμε τη γραμμή ΤΗ ΣΤΙΓΜΗ της διαγραφής (όχι από παλιά λίστα), ώστε να
    μη σβηστεί λάθος γραμμή αν άλλαξε η αρίθμηση. Αν ο αριθμός υπάρχει σε
    πάνω από μία γραμμή, δεν σβήνουμε τίποτα — αυτό είναι δουλειά του
    «Έλεγχος δεδομένων» (διπλά).
    """
    num = str(number or "").strip()
    if not num:
        return False, "Δώσε αριθμό παραστατικού."
    try:
        ws = _ws(SHEET_INV)
        rows = [i for i, r in enumerate(_get_all(ws)[1:], start=2)
                if len(r) > 3 and str(r[3]).strip() == num]
        if not rows:
            return False, f"Δεν βρέθηκε παραστατικό με αριθμό {num}."
        if len(rows) > 1:
            return False, (f"Ο αριθμός {num} υπάρχει {len(rows)} φορές — "
                           f"χρησιμοποίησε τον «Έλεγχο δεδομένων» στα Παραστατικά.")
        _delete(ws, rows[0], rows[0])
        load_invoices.clear(); _clear_all()
        return True, f"Το παραστατικό {num} διαγράφηκε."
    except Exception as e:
        return False, f"Δεν διαγράφηκε: {e}"


def purge_duplicate_timologiseis() -> tuple[int, int]:
    """
    Σβήνει διπλές επιταγές. Κρατάει αυτή που έχει συμπληρωμένα πεδία.

    Εδώ η επιλογή είναι πιο λεπτή απ' ό,τι στα παραστατικά: αν έχεις γράψει
    αριθμό επιταγής, έξοδα ή voucher σε μία από τις διπλές, ΑΥΤΗ πρέπει να μείνει —
    αλλιώς χάνεται η δουλειά σου.
    """
    ws = _ws(SHEET_TIMOL)
    vals = _get_all(ws)

    if len(vals) < 3:
        return 0, max(0, len(vals) - 1)

    # Ομαδοποιούμε ανά κλειδί, κρατώντας ΟΛΕΣ τις γραμμές κάθε ομάδας.
    groups: dict[str, list[tuple[int, list]]] = {}

    for i, r in enumerate(vals[1:], start=2):
        if len(r) < 3 or not r[0]:
            continue
        # Η αξία στο Sheet είναι ΗΔΗ σε λεπτά — δεν την ξαναμετατρέπουμε.
        key = f"{str(r[0]).strip()}|{int(parse_number(r[2]))}"
        groups.setdefault(key, []).append((i, r))

    doomed = []

    for entries in groups.values():
        if len(entries) < 2:
            continue

        # Ποια αξίζει να μείνει; Αυτή με τα περισσότερα συμπληρωμένα πεδία.
        def filled(item):
            _, r = item
            return sum(1 for c in (3, 4, 5, 6) if len(r) > c and str(r[c]).strip())

        keeper = max(entries, key=filled)
        doomed += [i for i, _ in entries if i != keeper[0]]

    if not doomed:
        return 0, len(groups)

    for start, end in reversed(_group_runs(doomed)):
        _delete(ws, start, end)

    load_timologiseis.clear(); _clear_all()
    return len(doomed), len(groups)


def purge_duplicate_sales() -> tuple[int, int]:
    """Σβήνει διπλές ημέρες πωλήσεων. Κρατάει την πρώτη."""
    ws = _ws(SHEET_SALES)
    vals = _get_all(ws)

    if len(vals) < 3:
        return 0, max(0, len(vals) - 1)

    seen = set()
    doomed = []

    for i, r in enumerate(vals[1:], start=2):
        if len(r) < 2 or not r[0]:
            continue
        key = str(r[0]).strip()
        if key in seen:
            doomed.append(i)
        else:
            seen.add(key)

    if not doomed:
        return 0, len(seen)

    for start, end in reversed(_group_runs(doomed)):
        _delete(ws, start, end)

    load_sales.clear(); _clear_all()
    return len(doomed), len(seen)


def purge_all_duplicates() -> dict:
    """Καθαρίζει και τα τρία φύλλα. → {φύλλο: (σβήστηκαν, έμειναν)}"""
    return {
        "sales": purge_duplicate_sales(),
        "invoices": purge_duplicate_invoices(),
        "timologiseis": purge_duplicate_timologiseis(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# ΕΛΕΓΧΟΣ ΠΟΙΟΤΗΤΑΣ
# ══════════════════════════════════════════════════════════════════════════════
def check_quality(sheet: str) -> dict:
    """
    Βρίσκει διπλά & κενά. ΔΕΝ σβήνει τίποτα — μόνο αναφέρει.
    → {"duplicates": [...], "gaps": [...]}
    """
    try:
        vals = _ws(sheet).get_all_values()
    except Exception as e:
        return {"duplicates": [], "gaps": [], "no_number": 0, "error": str(e)}

    if len(vals) < 2:
        return {"duplicates": [], "gaps": [], "no_number": 0}

    dups, seen, dates = [], {}, set()
    no_number = 0     # παλιές εγγραφές χωρίς αριθμό — δεν ελέγχονται

    for i, r in enumerate(vals[1:], start=2):
        if not r or not r[0]:
            continue
        d_str = str(r[0]).strip()

        try:
            dates.add(datetime.strptime(d_str, "%Y-%m-%d").date())
        except ValueError:
            continue

        # Το κλειδί διπλότυπου διαφέρει ανά φύλλο.
        if sheet == SHEET_INV:
            # Ο ΑΡΙΘΜΟΣ ΠΑΡΑΣΤΑΤΙΚΟΥ είναι η ταυτότητα. Αν λείπει (παλιά εγγραφή),
            # ΔΕΝ την ελέγχουμε καθόλου — δεν μπορούμε να ξέρουμε αν είναι διπλή.
            number = str(r[3]).strip() if len(r) > 3 else ""
            if not number:
                no_number += 1
                continue
            key = number
        else:
            key = d_str

        seen.setdefault(key, []).append({
            "row": i,
            "date": d_str,
            "number": str(r[3]).strip() if sheet == SHEET_INV and len(r) > 3 else "",
            "value": from_cents(r[2] if sheet == SHEET_INV and len(r) > 2
                                else (r[1] if len(r) > 1 else 0)),
            "type": r[1] if sheet == SHEET_INV and len(r) > 1 else "",
        })

    for key, entries in seen.items():
        if len(entries) > 1:
            dups.append({
                "date": entries[0]["date"],
                "type": entries[0]["type"],
                "value": entries[0]["value"],
                "number": entries[0].get("number", ""),
                "entries": entries,
            })

    # Κενά
    gaps = []
    if dates:
        lo, hi = min(dates), max(dates)
        if sheet == SHEET_TIMOL:
            # Τιμολογήσεις: εβδομαδιαίες (κενό = >10 μέρες) ως 07/12/2026,
            # δεκαήμερες 5/15/25 μετά (κενό = >12 μέρες· 25→5 είναι ως 11).
            from core.config import CHECK_DECADE_FROM
            decade_from = date.fromisoformat(CHECK_DECADE_FROM)
            ordered = sorted(dates)
            for a, b in zip(ordered, ordered[1:]):
                delta = (b - a).days
                step = 10 if b >= decade_from else 7
                if delta > step + 3:
                    gaps.append({
                        "after": a.isoformat(),
                        "before": b.isoformat(),
                        "gap_days": delta,
                        "approx_missing": max(1, round(delta / step) - 1),
                    })
        else:
            # Πωλήσεις & παραστατικά: καθημερινά
            cur = lo
            while cur <= hi:
                if cur not in dates and cur.weekday() < 6:
                    gaps.append(cur.isoformat())
                cur += timedelta(days=1)

    dups.sort(key=lambda d: d["date"], reverse=True)
    return {"duplicates": dups, "gaps": gaps, "no_number": no_number}


def delete_row(sheet: str, row: int) -> tuple[bool, str]:
    """Σβήνει ΜΙΑ γραμμή. Καθαρίζει το cache μετά."""
    try:
        _ws(sheet).delete_rows(int(row))
        {SHEET_SALES: load_sales,
         SHEET_INV: load_invoices,
         SHEET_TIMOL: load_timologiseis}[sheet].clear()
        _clear_all()
        return True, f"Η γραμμή {row} διαγράφηκε."
    except Exception as e:
        return False, f"Δεν διαγράφηκε: {e}"


def delete_rows_safe(sheet: str, rows: list[int]) -> tuple[int, list[str]]:
    """
    Σβήνει ΠΟΛΛΕΣ γραμμές με ασφάλεια.

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΓΙΑΤΙ ΑΠΟ ΚΑΤΩ ΠΡΟΣ ΤΑ ΠΑΝΩ                                            │
    │                                                                        │
    │ Όταν σβήνεις τη γραμμή 5, η γραμμή 6 γίνεται 5, η 7 γίνεται 6, κ.ο.κ.  │
    │ Αν σβήσεις πρώτα τη 5 και μετά «τη 7», θα σβήσεις ΛΑΘΟΣ γραμμή.        │
    │                                                                        │
    │ Σβήνοντας από κάτω προς τα πάνω, οι αριθμοί των γραμμών που ΔΕΝ έχουν  │
    │ σβηστεί ακόμα δεν αλλάζουν. Ασφαλές.                                   │
    │                                                                        │
    │ Ομαδοποιούμε και συνεχόμενες γραμμές → μία κλήση αντί για πολλές.      │
    └────────────────────────────────────────────────────────────────────────┘

    → (πόσες σβήστηκαν, [σφάλματα])
    """
    if not rows:
        return 0, []

    ws = _ws(sheet)
    deleted = 0
    errors = []

    # reversed → από κάτω προς τα πάνω, ώστε να μην αλλάζουν οι αριθμοί γραμμών
    for start, end in reversed(_group_runs(rows)):
        try:
            ws.delete_rows(int(start), int(end))
            deleted += end - start + 1
            time.sleep(1.2)   # όριο Sheets API: ~60 κλήσεις/λεπτό
        except Exception as e:
            errors.append(f"Γραμμές {start}-{end}: {e}")

    {SHEET_SALES: load_sales,
     SHEET_INV: load_invoices,
     SHEET_TIMOL: load_timologiseis}[sheet].clear()
    _clear_all()

    return deleted, errors


# ══════════════════════════════════════════════════════════════════════════════
# ΒΟΗΘΗΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
def _group_runs(rows: list[int]) -> list[tuple[int, int]]:
    """
    [3,4,5,9,10] → [(3,5), (9,10)]

    Ομαδοποιεί συνεχόμενες γραμμές, ώστε να σβήνονται με μία κλήση αντί για
    πεντακόσιες. Το Sheets API έχει όριο ~60 κλήσεις/λεπτό — χωρίς αυτό, ο
    καθαρισμός 500 γραμμών θα κρατούσε 8 λεπτά και θα χτυπούσε rate limit.
    """
    if not rows:
        return []

    rows = sorted(set(rows))
    runs = []
    start = prev = rows[0]

    for r in rows[1:]:
        if r == prev + 1:
            prev = r
        else:
            runs.append((start, prev))
            start = prev = r

    runs.append((start, prev))
    return runs


def _sort_by_date(ws, cols: str = "A:D") -> None:
    """Ταξινομεί το φύλλο κατά ημερομηνία, νεότερη πρώτη."""
    try:
        vals = ws.get_all_values()
        if len(vals) < 3:
            return
        data = sorted(vals[1:], key=lambda r: r[0] if r and r[0] else "", reverse=True)
        if data == vals[1:]:
            return

        last_col = cols.split(":")[1]
        rng = f"A2:{last_col}{len(data) + 1}"
        try:
            ws.update(values=data, range_name=rng, value_input_option="RAW")
        except TypeError:  # gspread < 6
            ws.update(rng, data, value_input_option="RAW")
    except Exception:
        pass


def _warn(msg: str) -> None:
    if _HAS_ST:
        st.warning(msg, icon="⚠️")
    else:
        print(f"⚠️  {msg}")


def clear_all_caches() -> None:
    load_sales.clear()
    load_invoices.clear()
    load_timologiseis.clear()
    _load_all_sheets.clear()
    load_setting.clear()
    load_agores.clear()
    load_pagia.clear()


# ══════════════════════════════════════════════════════════════════════════════
# ΧΕΙΡΟΚΙΝΗΤΑ ΠΑΓΙΑ — φύλλο «pagia_manual». Το γράφει ΜΟΝΟ ο χρήστης: ΠΟΤΕ δεν
# καθαρίζεται (ούτε από το «Άδειασμα» της ανάκτησης, ούτε αν αλλάξει η κεφαλίδα).
# ══════════════════════════════════════════════════════════════════════════════
SHEET_PAGIA_MANUAL = "pagia_manual"
MANUAL_COLS = ["id", "name", "amount", "freq", "start", "end", "day", "note"]


def _manual_ws():
    ss = _spreadsheet()
    try:
        return ss.worksheet(SHEET_PAGIA_MANUAL)
    except Exception:
        ws = ss.add_worksheet(title=SHEET_PAGIA_MANUAL, rows=200, cols=len(MANUAL_COLS))
        ws.update([MANUAL_COLS], "A1")
        return ws


@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_pagia_manual() -> list:
    """→ [{id, name, amount(€), freq, start, end, day, note}]"""
    try:
        vals = _with_retry(lambda: _manual_ws().get_all_values())
    except Exception:
        return []
    n = len(MANUAL_COLS)
    out = []
    for r in (vals or [])[1:]:
        r = (r + [""] * n)[:n]
        if not r[0] or not r[1]:
            continue
        d = dict(zip(MANUAL_COLS, r))
        d["amount"] = from_cents(d["amount"])
        out.append(d)
    return out


def add_pagia_manual(item: dict) -> str:
    """Νέο χειροκίνητο πάγιο → το id του."""
    import uuid
    iid = uuid.uuid4().hex[:8]
    row = [iid, str(item.get("name", "")).strip(), to_cents(item.get("amount") or 0),
           str(item.get("freq", "")), str(item.get("start", "")), str(item.get("end", "") or ""),
           str(item.get("day", "") or ""), str(item.get("note", "") or "")[:200]]
    _append(_manual_ws(), [row])
    load_pagia_manual.clear()
    return iid


def delete_pagia_manual(iid: str) -> bool:
    ws = _manual_ws()
    for idx, r in enumerate(_get_all(ws)[1:], start=2):
        if r and r[0] == iid:
            _with_retry(lambda: ws.delete_rows(idx))
            load_pagia_manual.clear()
            return True
    return False


def update_pagia_manual(iid: str, fields: dict) -> bool:
    """Αλλάζει πεδία ενός χειροκίνητου παγίου (π.χ. {"end": "2026-11"} ή {"amount": 52.0})."""
    ws = _manual_ws()
    for idx, r in enumerate(_get_all(ws)[1:], start=2):
        if r and r[0] == iid:
            row = (r + [""] * len(MANUAL_COLS))[:len(MANUAL_COLS)]
            for k, v in fields.items():
                if k in MANUAL_COLS and k != "id":
                    row[MANUAL_COLS.index(k)] = to_cents(v or 0) if k == "amount" else str(v or "")
            _with_retry(lambda: ws.update([row], f"A{idx}", value_input_option="RAW"))
            load_pagia_manual.clear()
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# ΔΙΟΡΘΩΣΕΙΣ ΜΕ ΤΟ ΧΕΡΙ — φύλλο «pagia_fix». Μία γραμμή = (μήνας, είδος) → σωστό
# ποσό. ΥΠΕΡΙΣΧΥΕΙ του αυτόματου (και του χειροκίνητου παγίου) για αυτόν τον μήνα.
# Δεν το αγγίζει ΠΟΤΕ καμία ανάκτηση. Σβήνεις τη διόρθωση → γυρνάει το αυτόματο.
# ══════════════════════════════════════════════════════════════════════════════
SHEET_PAGIA_FIX = "pagia_fix"
FIX_COLS = ["id", "ref", "kind", "amount", "pay_date", "note", "created"]
FIX_SOURCE = "✎ Διόρθωση με το χέρι"


def _fix_ws():
    ss = _spreadsheet()
    try:
        return ss.worksheet(SHEET_PAGIA_FIX)
    except Exception:
        ws = ss.add_worksheet(title=SHEET_PAGIA_FIX, rows=200, cols=len(FIX_COLS))
        ws.update([FIX_COLS], "A1")
        return ws


@st.cache_data(ttl=600, max_entries=1, show_spinner=False)
def load_pagia_fix() -> list:
    """→ [{id, ref, kind, amount(€), pay_date («YYYY-MM-DD» ή ""), note, created}]"""
    try:
        vals = _with_retry(lambda: _fix_ws().get_all_values())
    except Exception:
        return []
    n = len(FIX_COLS)
    out = []
    for r in (vals or [])[1:]:
        r = (r + [""] * n)[:n]
        if not r[0] or not r[1] or not r[2]:
            continue
        d = dict(zip(FIX_COLS, r))
        d["amount"] = from_cents(d["amount"])
        out.append(d)
    return out


def save_pagia_fix(ref: str, kind: str, amount: float, pay_date: str = "", note: str = "") -> None:
    """Νέα διόρθωση (μήνας + είδος). Αν υπάρχει ήδη για τα ίδια → αντικαθίσταται."""
    import uuid
    from datetime import datetime as _dt
    delete_pagia_fix(ref=ref, kind=kind)
    row = [uuid.uuid4().hex[:8], ref, kind, to_cents(amount or 0), pay_date or "",
           str(note or "")[:200], _dt.now().strftime("%Y-%m-%d %H:%M")]
    _append(_fix_ws(), [row])
    load_pagia_fix.clear()


def delete_pagia_fix(iid: str = "", ref: str = "", kind: str = "") -> bool:
    """Σβήνει διόρθωση με id, ή με (μήνας, είδος)."""
    ws = _fix_ws()
    for idx, r in enumerate(_get_all(ws)[1:], start=2):
        r = (r + [""] * 3)[:3]
        if (iid and r[0] == iid) or (not iid and r[1] == ref and r[2] == kind):
            _with_retry(lambda: ws.delete_rows(idx))
            load_pagia_fix.clear()
            return True
    return False


def apply_pagia_fix(df: pd.DataFrame, fixes: list) -> pd.DataFrame:
    """Για κάθε διόρθωση: βγάζει ό,τι υπάρχει για (μήνας, είδος) και βάζει το σωστό ποσό."""
    if not fixes:
        return df
    drop = {(f["ref"], f["kind"]) for f in fixes}
    if not df.empty:
        df = df[[(str(r), str(k)) not in drop for r, k in zip(df["ref"], df["kind"])]]
    rows = []
    for f in fixes:
        rows.append({"kind": f["kind"], "ref": f["ref"], "sub": "", "amount": float(f["amount"]),
                     "pay_date": f.get("pay_date") or None,
                     "detail": "✎ " + (f.get("note") or "διόρθωση"),
                     "source": FIX_SOURCE, "check": "", "emps": ""})
    fx = pd.DataFrame(rows)
    fx["pay_date"] = pd.to_datetime(fx["pay_date"], errors="coerce")
    fx["email_date"] = pd.NaT
    for col in PAGIA_COLS:
        if col not in fx.columns:
            fx[col] = ""
    return fx if df.empty else pd.concat([df, fx], ignore_index=True)


def load_pagia_all(today) -> pd.DataFrame:
    """
    Αυτόματα πάγια (από τα email) + χειροκίνητα (ανά μήνα, ως το τέλος του
    επόμενου έτους) + διορθώσεις με το χέρι (υπερισχύουν). Για «Πάγια» και «Μήνας».
    """
    from datetime import date as _date
    from core.pagia import expand_manual
    df = load_pagia()
    rows = expand_manual(load_pagia_manual(), _date(today.year + 1, 12, 31))
    if rows:
        man = pd.DataFrame(rows)
        man["pay_date"] = pd.to_datetime(man["pay_date"])
        man["email_date"] = pd.NaT
        for col in PAGIA_COLS:
            if col not in man.columns:
                man[col] = ""
        df = man if df.empty else pd.concat([df, man], ignore_index=True)
    return apply_pagia_fix(df, load_pagia_fix())


# ══════════════════════════════════════════════════════════════════════════════
# ΑΝΤΙΚΑΤΑΣΤΑΣΗ ΣΥΓΚΕΚΡΙΜΕΝΩΝ — σβήνει ΜΟΝΟ κάποιες κατηγορίες σε κάποιους μήνες
# (αντί για «Άδειασμα» όλων). Τα υπόλοιπα μένουν ακριβώς όπως είναι.
# ══════════════════════════════════════════════════════════════════════════════
def _rewrite_keep(ws, keep_fn, n: int) -> int:
    """
    Ξαναγράφει το φύλλο κρατώντας ΜΟΝΟ τις γραμμές όπου keep_fn(γραμμή) = True.
    ΜΙΑ εγγραφή, ΧΩΡΙΣ clear: οι κρατημένες γραμμές από πάνω και κενές από κάτω
    όσες έφυγαν — αν κάτι αποτύχει στη μέση, δεν μένει άδειο φύλλο.
    → πόσες γραμμές έφυγαν.
    """
    vals = _get_all(ws)
    if len(vals) <= 1:
        return 0
    body = [(r + [""] * n)[:n] for r in vals[1:]]
    body = [r for r in body if any(str(x).strip() for x in r)]
    kept = [r for r in body if keep_fn(r)]
    gone = len(body) - len(kept)
    if not gone:
        return 0
    blank = [[""] * n for _ in range(len(vals) - 1 - len(kept))]
    _with_retry(lambda: ws.update(kept + blank, "A2", value_input_option="RAW"),
                tries=4, base_wait=5.0)
    return gone


def purge_pagia_kinds(kinds: list, ref_from: str, ref_to: str) -> dict:
    """
    Σβήνει από «pagia» και «misthodosies» ΜΟΝΟ τις γραμμές των κατηγοριών `kinds`
    με μήνα (ref, «YYYY-MM») από `ref_from` ως `ref_to`. → {φύλλο: πόσες έφυγαν}.
    """
    kinds = set(kinds)

    def keep(kind_col, ref_col):
        return lambda r: not (r[kind_col] in kinds and ref_from <= r[ref_col][:7] <= ref_to)

    out = {SHEET_PAGIA: _rewrite_keep(_pagia_ws(), keep(0, 1), len(PAGIA_COLS)),
           SHEET_MISTH: _rewrite_keep(_misth_ws(), keep(3, 4), len(MISTH_COLS))}
    load_pagia.clear()
    load_misthodosies.clear()
    return out


def purge_pagia_log(date_from: str, date_to: str) -> int:
    """Σβήνει από την «Αναφορά ανάκτησης» τα email με ημ/νία από–έως («YYYY-MM-DD»)."""
    n = _rewrite_keep(_pagia_log_ws(), lambda r: not (date_from <= r[0] <= date_to),
                      len(PAGIA_LOG_COLS))
    load_pagia_log.clear()
    return n
