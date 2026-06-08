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
    if gspread is None:
        raise ImportError("gspread δεν είναι εγκατεστημένο.")
    try:
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
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

def _parse_number(x):
    """
    Μετατρέπει οποιαδήποτε τιμή σε float αξιόπιστα.
    Χειρίζεται: 1547.73 / "1547,73" / "1.547,73" / "1,547.73" / "1547.73 €"
    """
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("€", "").replace(" ", "").strip()
    if not s:
        return 0.0
    # Format "1.547,73" — τελεία=χιλιάδες, κόμμα=δεκαδικά
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # κόμμα είναι το δεκαδικό διαχωριστικό
            s = s.replace(".", "").replace(",", ".")
        else:
            # τελεία είναι το δεκαδικό διαχωριστικό
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return 0.0

# ══════════════════════════════════════════════════════════════════════════════
# SALES
# ══════════════════════════════════════════════════════════════════════════════
SALES_COLS = ["date", "net_sales", "customers", "avg_basket"]

@st.cache_data(ttl=300)
def load_sales() -> pd.DataFrame:
    try:
        ws = _get_sheet("sales")
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=SALES_COLS)
        df = pd.DataFrame(records)
        df["date"]       = pd.to_datetime(df["date"], errors="coerce").dt.date
        df["net_sales"]  = df["net_sales"].apply(_parse_number) / 100.0
        df["customers"]  = pd.to_numeric(df["customers"], errors="coerce")
        df["avg_basket"] = df["avg_basket"].apply(_parse_number) / 100.0
        df = df.dropna(subset=["date", "net_sales"])
        df = df[df["net_sales"] > 0]
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
        return df
    except Exception as e:
        st.warning(f"⚠️ Σφάλμα φόρτωσης πωλήσεων: {e}")
        return pd.DataFrame(columns=SALES_COLS)

def merge_sales(records: list) -> int:
    if not records:
        return 0
    try:
        ws = _get_sheet("sales")
        existing = ws.get_all_records()
        existing_dates = {str(r.get("date", "")) for r in existing}
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
            # Αποθήκευση x100 (integers) ώστε load_sales(/100) να επιστρέφει σωστή τιμή
            new_rows.append([
                d_str,
                round(float(rec["net_sales"]) * 100) if rec.get("net_sales") is not None else "",
                int(rec["customers"]) if rec.get("customers") is not None else "",
                round(float(rec["avg_basket"]) * 100) if rec.get("avg_basket") is not None else "",
            ])
        if new_rows:
            ws.append_rows(new_rows, value_input_option="RAW")
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
    try:
        ws = _get_sheet("invoices")
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=INVOICES_COLS)
        df = pd.DataFrame(records)
        df.columns = [c.lower() for c in df.columns]
        df["date"]  = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = df["value"].apply(_parse_number) / 100.0
        df = df.dropna(subset=["date"])
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
        return df
    except Exception as e:
        st.warning(f"⚠️ Σφάλμα φόρτωσης παραστατικών: {e}")
        return pd.DataFrame(columns=INVOICES_COLS)

def merge_invoices(records: list) -> int:
    if not records:
        return 0
    try:
        ws = _get_sheet("invoices")
        existing = ws.get_all_records()
        existing_keys = set()
        for r in existing:
            # Οι τιμές στο sheet είναι x100 integers
            raw_v = float(r.get('value', 0))
            key = f"{r.get('date','')}|{r.get('type','')}|{round(raw_v / 100.0, 2)}"
            existing_keys.add(key)
        if not existing:
            ws.append_row(["date", "type", "value"])
        new_rows = []
        for rec in records:
            d = rec.get("date") or rec.get("DATE")
            t = str(rec.get("type") or rec.get("TYPE", "")).strip()
            v = _parse_number(rec.get("value") or rec.get("VALUE", 0))
            if d is None or not t or t.lower() == "nan":
                continue
            d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            v_rounded = round(v, 2)
            key = f"{d_str}|{t}|{v_rounded}"
            if key in existing_keys:
                continue
            existing_keys.add(key)
            # Αποθήκευση x100 ώστε load_invoices(/100) να επιστρέφει σωστή τιμή
            new_rows.append([d_str, t, round(v_rounded * 100)])
        if new_rows:
            ws.append_rows(new_rows, value_input_option="RAW")
            load_invoices.clear()
        return len(new_rows)
    except Exception as e:
        st.error(f"❌ Σφάλμα αποθήκευσης παραστατικών: {e}")
        return 0

# ══════════════════════════════════════════════════════════════════════════════
# ΤΙΜΟΛΟΓΗΣΕΙΣ (επιταγές)
# ══════════════════════════════════════════════════════════════════════════════
TIMOL_COLS = ["check_date", "period", "amount"]

@st.cache_data(ttl=300)
def load_timologiseis() -> pd.DataFrame:
    try:
        ws = _get_sheet("timologiseis")
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=TIMOL_COLS)
        df = pd.DataFrame(records)
        df.columns = [c.lower() for c in df.columns]
        if "check_date" in df.columns:
            df["check_date"] = pd.to_datetime(df["check_date"], errors="coerce")
        if "amount" in df.columns:
            df["amount"] = df["amount"].apply(_parse_number)
        df = df.dropna(subset=["check_date"])
        df = df.sort_values("check_date", ascending=False).reset_index(drop=True)
        return df
    except Exception:
        # Αν δεν υπάρχει το φύλλο, επιστρέφει κενό
        return pd.DataFrame(columns=TIMOL_COLS)

def merge_timologiseis(records: list) -> int:
    if not records:
        return 0
    try:
        client = _get_client()
        wb = client.open_by_key(SPREADSHEET_ID)
        try:
            ws = wb.worksheet("timologiseis")
        except Exception:
            ws = wb.add_worksheet(title="timologiseis", rows=200, cols=5)
            ws.append_row(["check_date", "period", "amount"])
        existing = ws.get_all_records()
        existing_keys = set()
        for r in existing:
            existing_keys.add(f"{r.get('check_date','')}|{round(float(r.get('amount',0) or 0),2)}")
        new_rows = []
        for rec in records:
            cd = rec.get("check_date")
            if cd is None:
                continue
            cd_str = cd.strftime("%Y-%m-%d") if hasattr(cd, "strftime") else str(cd)
            amt = round(float(rec.get("amount", 0)), 2)
            key = f"{cd_str}|{amt}"
            if key in existing_keys:
                continue
            existing_keys.add(key)
            new_rows.append([cd_str, str(rec.get("period", "")), amt])
        if new_rows:
            ws.append_rows(new_rows, value_input_option="RAW")
            load_timologiseis.clear()
        return len(new_rows)
    except Exception as e:
        st.error(f"❌ Σφάλμα αποθήκευσης τιμολογήσεων: {e}")
        return 0
