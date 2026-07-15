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


def _ws(name: str):
    """Ζωντανό worksheet — ΠΟΤΕ δεν μπαίνει σε cache."""
    return _client().open_by_key(SPREADSHEET_ID).worksheet(name)


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
# ΠΩΛΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, max_entries=1, show_spinner=False)
def load_sales() -> pd.DataFrame:
    """→ DataFrame[date, net_sales, customers, avg_basket] — ποσά σε ΕΥΡΩ."""
    try:
        vals = _ws(SHEET_SALES).get_all_values()
    except Exception as e:
        _warn(f"Δεν φόρτωσαν οι πωλήσεις: {e}")
        return pd.DataFrame(columns=SALES_COLS)

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
    existing = {str(r[0]).strip() for r in ws.get_all_values()[1:] if r and r[0]}

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
        ws.append_rows(new_rows, value_input_option="RAW")
        _sort_by_date(ws, cols="A:D")
        load_sales.clear()

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

    load_sales.clear()
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
    try:
        vals = _ws(SHEET_INV).get_all_values()
    except Exception as e:
        _warn(f"Δεν φόρτωσαν τα παραστατικά: {e}")
        return pd.DataFrame(columns=cols)

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
        for r in ws.get_all_values()[1:] if len(r) >= 3 and r[0]
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
        ws.append_rows(new_rows, value_input_option="RAW")
        load_invoices.clear()

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
    vals = ws.get_all_values()

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
        ws.delete_rows(start, end)

    load_invoices.clear()
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


# ══════════════════════════════════════════════════════════════════════════════
# ΤΙΜΟΛΟΓΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, max_entries=1, show_spinner=False)
def load_timologiseis() -> pd.DataFrame:
    """
    → DataFrame[check_date, period, amount, check_number, expenses, _row]
    Η στήλη _row είναι ο αριθμός γραμμής στο Sheet — χρειάζεται για edit/delete.
    """
    cols = TIMOL_COLS + ["_row"]
    try:
        vals = _ws(SHEET_TIMOL).get_all_values()
    except Exception as e:
        _warn(f"Δεν φόρτωσαν οι τιμολογήσεις: {e}")
        return pd.DataFrame(columns=cols)

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

    df = df.dropna(subset=["check_date"])
    df = df.sort_values("check_date", ascending=False).reset_index(drop=True)
    return df


def merge_timologiseis(records: list) -> int:
    """Κλειδί διπλότυπου: check_date + amount."""
    if not records:
        return 0

    ws = _ws(SHEET_TIMOL)

    # Το Sheet δίνει λεπτά ως string. Κανονικοποιούμε σε ακέραιο, ώστε το
    # "21351" και το 21351 να δίνουν το ίδιο κλειδί.
    existing = {
        f"{str(r[0]).strip()}|{int(parse_number(r[2]))}"
        for r in ws.get_all_values()[1:] if len(r) >= 3 and r[0]
    }

    new_rows = []
    for rec in records:
        cd = rec.get("check_date")
        if not cd:
            continue
        cd_str = cd.strftime("%Y-%m-%d") if hasattr(cd, "strftime") else str(cd)[:10]
        v = to_cents(rec.get("amount", 0))

        key = f"{cd_str}|{v}"
        if key in existing:
            continue
        existing.add(key)
        new_rows.append([cd_str, str(rec.get("period", "")), v, "", ""])

    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
        load_timologiseis.clear()

    return len(new_rows)


def update_timologiseis_field(row: int, field: str, value: str) -> bool:
    """Γράφει check_number (στήλη D) ή expenses (στήλη E)."""
    col = {"check_number": 4, "expenses": 5}.get(field)
    if not col or not row:
        return False
    try:
        _ws(SHEET_TIMOL).update_cell(int(row), col, str(value or ""))
        load_timologiseis.clear()
        return True
    except Exception:
        return False


def purge_duplicate_timologiseis() -> tuple[int, int]:
    """
    Σβήνει διπλές επιταγές. Κρατάει αυτή που έχει συμπληρωμένα πεδία.

    Εδώ η επιλογή είναι πιο λεπτή απ' ό,τι στα παραστατικά: αν έχεις γράψει
    αριθμό επιταγής ή έξοδα σε μία από τις διπλές, ΑΥΤΗ πρέπει να μείνει —
    αλλιώς χάνεται η δουλειά σου.
    """
    ws = _ws(SHEET_TIMOL)
    vals = ws.get_all_values()

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
            return sum(1 for c in (3, 4) if len(r) > c and str(r[c]).strip())

        keeper = max(entries, key=filled)
        doomed += [i for i, _ in entries if i != keeper[0]]

    if not doomed:
        return 0, len(groups)

    for start, end in reversed(_group_runs(doomed)):
        ws.delete_rows(start, end)

    load_timologiseis.clear()
    return len(doomed), len(groups)


def purge_duplicate_sales() -> tuple[int, int]:
    """Σβήνει διπλές ημέρες πωλήσεων. Κρατάει την πρώτη."""
    ws = _ws(SHEET_SALES)
    vals = ws.get_all_values()

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
        ws.delete_rows(start, end)

    load_sales.clear()
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
            # Τιμολογήσεις: εβδομαδιαίες → κενό = >10 μέρες απόσταση
            ordered = sorted(dates)
            for a, b in zip(ordered, ordered[1:]):
                delta = (b - a).days
                if delta > 10:
                    gaps.append({
                        "after": a.isoformat(),
                        "before": b.isoformat(),
                        "gap_days": delta,
                        "approx_missing": round(delta / 7) - 1,
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
