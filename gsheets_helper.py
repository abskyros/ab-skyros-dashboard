"""
gsheets_helper.py
ΕΚΔΟΣΗ: v5.0 — με check_invoices_quality + check_timologiseis_quality + delete_sheet_row
Κοινό module για ανάγνωση/εγγραφή στο Google Sheets.
Φύλλα: "sales", "invoices", "timologiseis"
"""

import json
import pandas as pd
from datetime import date, datetime, timedelta
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

@st.cache_data(ttl=300, max_entries=1)
def load_sales() -> pd.DataFrame:
    try:
        ws = _get_sheet("sales")
        # get_all_values() είναι ΠΟΛΥ πιο ελαφρύ από get_all_records()
        # (λίστες αντί για ένα dict ανά γραμμή) — κρίσιμο για τη μνήμη.
        vals = ws.get_all_values()
        if len(vals) < 2:
            return pd.DataFrame(columns=SALES_COLS)
        rows = []
        for r in vals[1:]:
            if len(r) < 2 or not r[0]:
                continue
            rows.append((r[0], r[1],
                         r[2] if len(r) > 2 else "",
                         r[3] if len(r) > 3 else ""))
        del vals
        if not rows:
            return pd.DataFrame(columns=SALES_COLS)
        df = pd.DataFrame(rows, columns=["date", "net_sales", "customers", "avg_basket"])
        del rows
        df["date"]       = pd.to_datetime(df["date"], errors="coerce")
        df["net_sales"]  = df["net_sales"].apply(_parse_number) / 100.0
        df["customers"]  = pd.to_numeric(df["customers"], errors="coerce")
        df["avg_basket"] = df["avg_basket"].apply(_parse_number) / 100.0
        df = df.dropna(subset=["date", "net_sales"])
        df = df[df["net_sales"] > 0]
        df = df.drop_duplicates(subset=["date"])
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
        # Μείωση μνήμης: float32 αντί float64
        for _c in ("net_sales", "avg_basket", "customers"):
            if _c in df.columns:
                df[_c] = df[_c].astype("float32")
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


def update_sales_value(target_date, net_sales=None, customers=None, avg_basket=None):
    """Διορθώνει χειροκίνητα μια υπάρχουσα εγγραφή πώλησης βάσει ημερομηνίας.
    Επιστρέφει (success: bool, message: str). Οι τιμές αποθηκεύονται x100."""
    try:
        ws = _get_sheet("sales")
        d_str = target_date.isoformat() if isinstance(target_date, (date, datetime)) else str(target_date)
        all_vals = ws.get_all_values()
        if not all_vals:
            return False, "Το φύλλο πωλήσεων είναι κενό."
        header = all_vals[0]
        # Βρες τη γραμμή με αυτή την ημερομηνία (στήλη 0)
        row_idx = None
        for i, row in enumerate(all_vals[1:], start=2):  # 1-indexed, +1 για header
            if row and str(row[0]).strip() == d_str:
                row_idx = i
                break
        if row_idx is None:
            return False, f"Δεν βρέθηκε εγγραφή για {d_str}."
        # Ενημέρωσε μόνο τα πεδία που δόθηκαν (x100 για χρηματικά)
        updates = []
        if net_sales is not None:
            updates.append((2, round(float(net_sales) * 100)))   # στήλη B
        if customers is not None:
            updates.append((3, int(customers)))                   # στήλη C
        if avg_basket is not None:
            updates.append((4, round(float(avg_basket) * 100)))   # στήλη D
        for col, val in updates:
            ws.update_cell(row_idx, col, val)
        load_sales.clear()
        return True, f"Ενημερώθηκε η εγγραφή {d_str}."
    except Exception as e:
        return False, f"Σφάλμα: {e}"

# ══════════════════════════════════════════════════════════════════════════════
# INVOICES
# ══════════════════════════════════════════════════════════════════════════════
INVOICES_COLS = ["date", "type", "value"]

@st.cache_data(ttl=300, max_entries=1)
def load_invoices() -> pd.DataFrame:
    try:
        ws = _get_sheet("invoices")
        # ΚΡΙΣΙΜΟ: 10.000+ γραμμές. get_all_values() αντί get_all_records()
        # γλιτώνει τεράστια μνήμη (λίστες αντί για dict ανά γραμμή).
        vals = ws.get_all_values()
        if len(vals) < 2:
            return pd.DataFrame(columns=INVOICES_COLS)
        rows = []
        for r in vals[1:]:
            if len(r) < 3 or not r[0]:
                continue
            rows.append((r[0], r[1], r[2]))
        del vals
        if not rows:
            return pd.DataFrame(columns=INVOICES_COLS)
        df = pd.DataFrame(rows, columns=["date", "type", "value"])
        del rows
        df["date"]  = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = df["value"].apply(_parse_number) / 100.0
        df = df.dropna(subset=["date"])
        df = df.drop_duplicates(subset=["date", "type", "value"])
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
        # Μείωση μνήμης
        df["value"] = df["value"].astype("float32")
        df["type"]  = df["type"].astype("category")
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

@st.cache_data(ttl=300, max_entries=1)
def load_timologiseis() -> pd.DataFrame:
    try:
        ws = _get_sheet("timologiseis")
        all_vals = ws.get_all_values()
        if not all_vals:
            return pd.DataFrame(columns=TIMOL_COLS)
        # Έλεγχος αν η 1η γραμμή είναι header
        first = [str(c).strip().lower() for c in all_vals[0][:3]]
        if first == ["check_date", "period", "amount"]:
            data_rows = all_vals[1:]
        else:
            # Δεν υπάρχει header — όλες οι γραμμές είναι δεδομένα
            data_rows = all_vals
        rows = []
        for ri, r in enumerate(data_rows, start=2):
            if len(r) < 3:
                continue
            _chknum = r[3] if len(r) > 3 else ""
            _exp = r[4] if len(r) > 4 else ""
            rows.append({"check_date": r[0], "period": r[1], "amount": r[2],
                         "check_number": str(_chknum).strip(),
                         "expenses": str(_exp).strip(), "_row": ri})
        if not rows:
            return pd.DataFrame(columns=TIMOL_COLS + ["check_number", "expenses", "_row"])
        df = pd.DataFrame(rows)
        df["check_date"] = pd.to_datetime(df["check_date"], errors="coerce")
        df["amount"] = df["amount"].apply(_parse_number) / 100.0
        df = df.dropna(subset=["check_date"])
        df = df.drop_duplicates(subset=["check_date", "amount"])
        df = df.sort_values("check_date", ascending=False).reset_index(drop=True)
        return df
    except Exception:
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
        # Διασφάλιση ότι υπάρχει header στη γραμμή 1
        all_vals = ws.get_all_values()
        if not all_vals or [str(c).strip().lower() for c in all_vals[0][:3]] != ["check_date", "period", "amount"]:
            # Αν η 1η γραμμή δεν είναι header → καθάρισε & ξαναγράψε σωστά
            ws.clear()
            ws.append_row(["check_date", "period", "amount"])
            all_vals = [["check_date", "period", "amount"]]
        # Συλλογή υπαρχόντων κλειδιών (από όλες τις γραμμές δεδομένων)
        existing_keys = set()
        for row in all_vals[1:]:
            if len(row) >= 3:
                cd_e = str(row[0]).strip()
                try:
                    amt_e = round(float(str(row[2]).replace(",", ".")) / 100.0, 2)
                except Exception:
                    amt_e = 0
                existing_keys.add(f"{cd_e}|{amt_e}")
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
            existing_keys.add(key)  # αποτρέπει διπλά μέσα στο ίδιο batch
            new_rows.append([cd_str, str(rec.get("period", "")), round(amt * 100)])
        if new_rows:
            ws.append_rows(new_rows, value_input_option="RAW")
            load_timologiseis.clear()
        return len(new_rows)
    except Exception as e:
        st.error(f"❌ Σφάλμα αποθήκευσης τιμολογήσεων: {e}")
        return 0


def update_timologiseis_check_number(target_row, check_number):
    """Αποθηκεύει τον αριθμό επιταγής στη στήλη D της δοσμένης γραμμής (1-indexed)."""
    try:
        ws = _get_sheet("timologiseis")
        ws.update_cell(int(target_row), 4, str(check_number))
        load_timologiseis.clear()
        return True, "Αποθηκεύτηκε ο αριθμός επιταγής."
    except Exception as e:
        return False, f"Σφάλμα: {e}"


def update_timologiseis_expenses(target_row, expenses):
    """Αποθηκεύει τα έξοδα μήνα στη στήλη E της δοσμένης γραμμής (1-indexed)."""
    try:
        ws = _get_sheet("timologiseis")
        ws.update_cell(int(target_row), 5, str(expenses))
        load_timologiseis.clear()
        return True, "Αποθηκεύτηκαν τα έξοδα."
    except Exception as e:
        return False, f"Σφάλμα: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# ΕΛΕΓΧΟΣ ΠΟΙΟΤΗΤΑΣ ΔΕΔΟΜΕΝΩΝ (διπλά + κενά)
# ══════════════════════════════════════════════════════════════════════════════
def check_sales_quality(lookback_days=None):
    """Ελέγχει το φύλλο sales για διπλές ημερομηνίες & κενά (χαμένες μέρες).
    Αν lookback_days δοθεί, ελέγχει μόνο τις τελευταίες Ν ημέρες.
    Επιστρέφει dict: {duplicates: [...], gaps: [...]}."""
    result = {"duplicates": [], "gaps": []}
    try:
        ws = _get_sheet("sales")
        vals = ws.get_all_values()
        if len(vals) < 2:
            return result
        rows = vals[1:]  # χωρίς header
        # Συγκέντρωσε ημερομηνίες με τις γραμμές & τιμές τους
        from collections import defaultdict
        date_rows = defaultdict(list)  # date_str -> list of (row_index, net_sales_raw)
        for i, r in enumerate(rows, start=2):  # 1-indexed + header
            if r and r[0]:
                d_str = str(r[0]).strip()
                net_raw = r[1] if len(r) > 1 else ""
                date_rows[d_str].append((i, net_raw))

        all_dates = sorted(date_rows.keys())
        if lookback_days:
            cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
            check_dates = [d for d in all_dates if d >= cutoff]
        else:
            check_dates = all_dates

        # 1) Διπλές ημερομηνίες
        for d_str in check_dates:
            entries = date_rows[d_str]
            if len(entries) > 1:
                vals_list = []
                for (ridx, net_raw) in entries:
                    try:
                        v = _parse_number(net_raw) / 100.0
                    except Exception:
                        v = 0
                    vals_list.append({"row": ridx, "net_sales": round(v, 2)})
                result["duplicates"].append({"date": d_str, "entries": vals_list})

        # 2) Κενά (χαμένες μέρες) — μόνο σε συνεχόμενο εύρος
        try:
            parsed = sorted({datetime.strptime(d, "%Y-%m-%d").date() for d in check_dates})
            if len(parsed) >= 2:
                start, end = parsed[0], parsed[-1]
                existing = set(parsed)
                cur = start
                while cur <= end:
                    if cur not in existing:
                        result["gaps"].append(cur.isoformat())
                    cur += timedelta(days=1)
        except Exception:
            pass
    except Exception as e:
        result["error"] = str(e)
    return result


def check_timologiseis_quality(lookback_days=None):
    """Ελέγχει το φύλλο timologiseis για διπλές ημερομηνίες επιταγής & κενές εβδομάδες.
    Επιστρέφει dict: {duplicates: [...], gaps: [...]}."""
    result = {"duplicates": [], "gaps": []}
    try:
        ws = _get_sheet("timologiseis")
        vals = ws.get_all_values()
        if len(vals) < 2:
            return result
        rows = vals[1:]
        from collections import defaultdict
        date_rows = defaultdict(list)
        for i, r in enumerate(rows, start=2):
            if r and r[0]:
                d_str = str(r[0]).strip()
                amt_raw = r[2] if len(r) > 2 else ""
                date_rows[d_str].append((i, amt_raw))

        all_dates = sorted(date_rows.keys())
        if lookback_days:
            cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
            check_dates = [d for d in all_dates if d >= cutoff]
        else:
            check_dates = all_dates

        # 1) Διπλές ημερομηνίες επιταγής
        for d_str in check_dates:
            entries = date_rows[d_str]
            if len(entries) > 1:
                vals_list = []
                for (ridx, amt_raw) in entries:
                    try:
                        v = _parse_number(amt_raw) / 100.0
                    except Exception:
                        v = 0
                    vals_list.append({"row": ridx, "amount": round(v, 2)})
                result["duplicates"].append({"date": d_str, "entries": vals_list})

        # 2) Κενές εβδομάδες (οι επιταγές είναι ~εβδομαδιαίες, διαφορά ~7 μέρες)
        try:
            parsed = sorted({datetime.strptime(d, "%Y-%m-%d").date() for d in check_dates})
            for a, b in zip(parsed, parsed[1:]):
                gap_days = (b - a).days
                if gap_days > 10:  # >10 μέρες = πιθανή χαμένη εβδομάδα
                    missing_weeks = gap_days // 7 - 1
                    result["gaps"].append({
                        "after": a.isoformat(),
                        "before": b.isoformat(),
                        "gap_days": gap_days,
                        "approx_missing": max(1, missing_weeks)
                    })
        except Exception:
            pass
    except Exception as e:
        result["error"] = str(e)
    return result


def check_invoices_quality(lookback_days=None):
    """Ελέγχει το φύλλο invoices για διπλές εγγραφές (ίδια ημερομηνία+τύπος+αξία)
    και κενά (χαμένες μέρες στο εύρος). Επιστρέφει dict: {duplicates, gaps}."""
    result = {"duplicates": [], "gaps": []}
    try:
        ws = _get_sheet("invoices")
        vals = ws.get_all_values()
        if len(vals) < 2:
            return result
        rows = vals[1:]
        from collections import defaultdict
        # Διπλά = ίδιος συνδυασμός (date|type|value)
        combo_rows = defaultdict(list)
        all_dates_set = set()
        for i, r in enumerate(rows, start=2):
            if r and r[0]:
                d_str = str(r[0]).strip()
                t_str = str(r[1]).strip() if len(r) > 1 else ""
                v_str = str(r[2]).strip() if len(r) > 2 else ""
                combo_rows[f"{d_str}|{t_str}|{v_str}"].append((i, d_str, t_str, v_str))
                try:
                    all_dates_set.add(datetime.strptime(d_str, "%Y-%m-%d").date())
                except Exception:
                    pass

        cutoff = None
        if lookback_days:
            cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

        # Διπλές εγγραφές (πανομοιότυπες: ίδια date+type+value)
        for combo, entries in combo_rows.items():
            if len(entries) > 1:
                d_str = entries[0][1]
                if cutoff and d_str < cutoff:
                    continue
                try:
                    _v = _parse_number(entries[0][3]) / 100.0
                except Exception:
                    _v = 0
                result["duplicates"].append({
                    "date": d_str,
                    "type": entries[0][2],
                    "value": round(_v, 2),
                    "rows": [e[0] for e in entries],
                })

        # Κενά (χαμένες μέρες) — παραβλέπουμε Κυριακές (συνήθως κλειστά)
        try:
            parsed = sorted(all_dates_set)
            if cutoff:
                _c = datetime.strptime(cutoff, "%Y-%m-%d").date()
                parsed = [d for d in parsed if d >= _c]
            if len(parsed) >= 2:
                start, end = parsed[0], parsed[-1]
                existing = set(parsed)
                cur = start
                while cur <= end:
                    if cur not in existing and cur.weekday() != 6:
                        result["gaps"].append(cur.isoformat())
                    cur += timedelta(days=1)
        except Exception:
            pass
    except Exception as e:
        result["error"] = str(e)
    return result


def delete_sheet_row(sheet_name, row_index):
    """Σβήνει μια συγκεκριμένη γραμμή (1-indexed) από το φύλλο.
    Επιστρέφει (success, message)."""
    try:
        ws = _get_sheet(sheet_name)
        ws.delete_rows(int(row_index))
        # Καθάρισε caches
        if sheet_name == "sales":
            load_sales.clear()
        elif sheet_name == "invoices":
            load_invoices.clear()
        elif sheet_name == "timologiseis":
            load_timologiseis.clear()
        return True, f"Διαγράφηκε η γραμμή {row_index}."
    except Exception as e:
        return False, f"Σφάλμα διαγραφής: {e}"
