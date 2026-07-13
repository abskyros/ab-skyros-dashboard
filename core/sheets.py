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
    """→ DataFrame[date, type, value] — ποσά σε ΕΥΡΩ."""
    try:
        vals = _ws(SHEET_INV).get_all_values()
    except Exception as e:
        _warn(f"Δεν φόρτωσαν τα παραστατικά: {e}")
        return pd.DataFrame(columns=INV_COLS)

    if len(vals) < 2:
        return pd.DataFrame(columns=INV_COLS)

    rows = [(r[0], r[1], r[2]) for r in vals[1:] if len(r) >= 3 and r[0]]
    del vals
    if not rows:
        return pd.DataFrame(columns=INV_COLS)

    df = pd.DataFrame(rows, columns=INV_COLS)
    del rows

    df["date"]  = pd.to_datetime(df["date"], errors="coerce")
    df["type"]  = df["type"].astype(str).str.strip()
    df["value"] = df["value"].map(from_cents).astype("float32")

    df = df.dropna(subset=["date"])
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df


def merge_invoices(records: list) -> int:
    """Κλειδί διπλότυπου: date + type + value."""
    if not records:
        return 0

    ws = _ws(SHEET_INV)
    existing = {
        f"{str(r[0]).strip()}|{str(r[1]).strip()}|{str(r[2]).strip()}"
        for r in ws.get_all_values()[1:] if len(r) >= 3 and r[0]
    }

    new_rows = []
    for rec in records:
        d = rec.get("date")
        if d is None or (isinstance(d, float) and pd.isna(d)):
            continue
        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        t = str(rec.get("type", "")).strip()
        v = to_cents(rec.get("value", 0))

        key = f"{d_str}|{t}|{v}"
        if key in existing:
            continue
        existing.add(key)
        new_rows.append([d_str, t, v])

    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
        load_invoices.clear()

    return len(new_rows)


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
    existing = {
        f"{str(r[0]).strip()}|{str(r[2]).strip()}"
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
        return {"duplicates": [], "gaps": [], "error": str(e)}

    if len(vals) < 2:
        return {"duplicates": [], "gaps": []}

    dups, seen, dates = [], {}, set()

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
            key = f"{d_str}|{r[1] if len(r) > 1 else ''}|{r[2] if len(r) > 2 else ''}"
        else:
            key = d_str

        seen.setdefault(key, []).append({
            "row": i,
            "date": d_str,
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
    return {"duplicates": dups, "gaps": gaps}


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


# ══════════════════════════════════════════════════════════════════════════════
# ΒΟΗΘΗΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
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
