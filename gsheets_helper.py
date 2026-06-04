"""
gsheets_helper.py
Κοινό module για ανάγνωση/εγγραφή στο Google Sheets.
Φύλλα: "sales" και "invoices"
"""
import json
import pandas as pd
from datetime import date, datetime
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None

SPREADSHEET_ID = "1KWX5PH0Dg-dhfMfT8-jCd-Jft9f80I1E2Wss1w8QTlA"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── AUTH ──────────────────────────────────────────────────────────────────────

def _get_client():
    """Επιστρέφει authenticated gspread client από Streamlit secrets."""
    if gspread is None:
        raise ImportError("gspread δεν είναι εγκατεστημένο.")
    try:
        info = dict(st.secrets["gcp_service_account"])
        # Διόρθωση private_key αν έχει escaped newlines
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
        # Fallback: διαβάζουμε από αρχείο (για GitHub Action)
        import os
        key_path = os.environ.get("GOOGLE_KEY_PATH", "ab-skyros-key.json")
        with open(key_path) as f:
            info = json.load(f)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _get_sheet(sheet_name: str):
    client = _get_client()
    wb = client.open_by_key(SPREADSHEET_ID)
    return wb.worksheet(sheet_name)

# ══════════════════════════════════════════════════════════════════════════════
# SALES
# ══════════════════════════════════════════════════════════════════════════════
SALES_COLS = ["date", "net_sales", "customers", "avg_basket"]

@st.cache_data(ttl=300)
def load_sales() -> pd.DataFrame:
    """Φορτώνει όλες τις εγγραφές πωλήσεων από το φύλλο 'sales'."""
    try:
        ws = _get_sheet("sales")
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=SALES_COLS)
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        df["net_sales"] = pd.to_numeric(df["net_sales"], errors="coerce")
        df["customers"] = pd.to_numeric(df["customers"], errors="coerce")
        df["avg_basket"] = pd.to_numeric(df["avg_basket"], errors="coerce")
        df = df.dropna(subset=["date", "net_sales"])
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
        return df
    except Exception as e:
        st.warning(f"⚠️ Σφάλμα φόρτωσης πωλήσεων: {e}")
        return pd.DataFrame(columns=SALES_COLS)

def merge_sales(records: list) -> int:
    """
    Αποθηκεύει νέες εγγραφές πωλήσεων (αποφεύγει duplicates ανά ημερομηνία).
    Επιστρέφει αριθμό νέων εγγραφών που αποθηκεύτηκαν.
    """
    if not records:
        return 0
    try:
        ws = _get_sheet("sales")
        existing = ws.get_all_records()
        existing_dates = {str(r.get("date", "")) for r in existing}

        # Αν το φύλλο είναι άδειο, βάλε headers
        if not existing:
            ws.append_row(SALES_COLS)

        new_rows = []
        for rec in records:
            d = rec.get("date")
            if d is None:
                continue
            d_str = d.isoformat() if isinstance(d, (date, datetime)) else str(d)
            if d_str in existing_dates:
                continue
            existing_dates.add(d_str)
            new_rows.append([
                d_str,
                round(float(rec["net_sales"]), 2) if rec.get("net_sales") is not None else "",
                int(rec["customers"]) if rec.get("customers") is not None else "",
                round(float(rec["avg_basket"]), 2) if rec.get("avg_basket") is not None else "",
            ])

        if new_rows:
            ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        load_sales.clear()
        return len(new_rows)
    except Exception as e:
        st.error(f"❌ Σφάλμα αποθήκευσης πωλήσεων: {e}")
        return 0

# ══════════════════════════════════════════════════════════════════════════════
# INVOICES
# ══════════════════════════════════════════════════════════════════════════════
INVOICES_COLS = ["date", "type", "value"]

@st.cache_data(ttl=300)
def load_invoices() -> pd.DataFrame:
    """Φορτώνει όλα τα παραστατικά από το φύλλο 'invoices'."""
    try:
        ws = _get_sheet("invoices")
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=INVOICES_COLS)
        df = pd.DataFrame(records)
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0)
        df = df.dropna(subset=["date"])
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
        return df
    except Exception as e:
        st.warning(f"⚠️ Σφάλμα φόρτωσης παραστατικών: {e}")
        return pd.DataFrame(columns=INVOICES_COLS)

def merge_invoices(records: list) -> int:
    """
    Αποθηκεύει νέα παραστατικά (αποφεύγει duplicates βάσει date+type+value).
    Επιστρέφει αριθμό νέων εγγραφών.
    """
    if not records:
        return 0
    try:
        ws = _get_sheet("invoices")
        existing = ws.get_all_records()

        # Δημιούργησε set από existing keys
        existing_keys = set()
        for r in existing:
            key = f"{r.get('date','')}|{r.get('type','')}|{r.get('value','')}"
            existing_keys.add(key)

        if not existing:
            ws.append_row(["date", "type", "value"])

        new_rows = []
        for rec in records:
            d = rec.get("date") or rec.get("DATE")
            t = rec.get("type") or rec.get("TYPE", "")
            v = rec.get("value") or rec.get("VALUE", 0)
            if d is None:
                continue
            d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            v_str = str(round(float(v), 2))
            key = f"{d_str}|{t}|{v_str}"
            if key in existing_keys:
                continue
            existing_keys.add(key)
            new_rows.append([d_str, t, float(v_str)])

        if new_rows:
            ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        load_invoices.clear()
        return len(new_rows)
    except Exception as e:
        st.error(f"❌ Σφάλμα αποθήκευσης παραστατικών: {e}")
        return 0
