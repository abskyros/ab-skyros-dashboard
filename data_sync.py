#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_sync.py — Αυτόματη ενημέρωση ΠΑΡΑΣΤΑΤΙΚΩΝ & ΤΙΜΟΛΟΓΗΣΕΩΝ
Τρέχει μέσω GitHub Actions ΚΑΘΕ 2 ΩΡΕΣ (data_sync.yml).
Διαβάζει τα emails, κάνει parse τα Excel/CSV, και αποθηκεύει στο Google Sheets.
Είναι idempotent — προσθέτει μόνο ό,τι λείπει.

GitHub Secrets: GOOGLE_KEY_JSON, EMAIL_PASS (invoices), SALES_EMAIL_PASS (timologiseis)
"""

import io
import os
import sys
import json
import re
from datetime import date, datetime

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from imap_tools import MailBox, AND

# ── CONFIG (ίδιο με app.py) ──
SPREADSHEET_ID        = "1KWX5PH0Dg-dhfMfT8-jCd-Jft9f80I1E2Wss1w8QTlA"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

INVOICES_EMAIL_USER   = "abf.skyros@gmail.com"
INVOICES_EMAIL_SENDER = "Notifications@WeDoConnect.com"
TIMOL_EMAIL_USER      = "ftoulisgm@gmail.com"
TIMOL_EMAIL_SENDER    = "noreply@ab.gr"
TIMOL_SUBJECT_KW      = "ΤΙΜΟΛΟΓΗΣΕΙΣ"

INV_LIMIT   = 60
TIMOL_LIMIT = 200


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════════════════
def _get_wb():
    info = json.loads(os.environ["GOOGLE_KEY_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def _parse_number(x):
    if x is None:
        return 0.0
    s = str(x).replace("€", "").replace(" ", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def merge_invoices(wb, records):
    """Αποθηκεύει παραστατικά (×100), αποφεύγει διπλά (date+type+value)."""
    if not records:
        return 0
    ws = wb.worksheet("invoices")
    existing = set()
    for r in ws.get_all_values()[1:]:
        if len(r) >= 3 and r[0]:
            existing.add(f"{str(r[0]).strip()}|{str(r[1]).strip()}|{r[2]}")
    new_rows = []
    for rec in records:
        d = rec.get("date")
        if d is None or (hasattr(d, "__class__") and pd.isna(d)):
            continue
        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        t = str(rec.get("type", "")).strip()
        v100 = round(float(rec.get("value", 0)) * 100)
        key = f"{d_str}|{t}|{v100}"
        if key in existing:
            continue
        existing.add(key)
        new_rows.append([d_str, t, v100])
    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
    return len(new_rows)


def merge_timologiseis(wb, records):
    """Αποθηκεύει τιμολογήσεις/επιταγές (×100), αποφεύγει διπλά (date+amount)."""
    if not records:
        return 0
    ws = wb.worksheet("timologiseis")
    existing = set()
    for r in ws.get_all_values()[1:]:
        if len(r) >= 3 and r[0]:
            existing.add(f"{str(r[0]).strip()}|{r[2]}")
    new_rows = []
    for rec in records:
        cd = rec.get("check_date")
        if cd is None:
            continue
        cd_str = cd.strftime("%Y-%m-%d") if hasattr(cd, "strftime") else str(cd)[:10]
        amt = round(float(rec.get("amount", 0)), 2)
        v100 = round(amt * 100)
        key = f"{cd_str}|{v100}"
        if key in existing:
            continue
        existing.add(key)
        new_rows.append([cd_str, str(rec.get("period", "")), v100])
    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
    return len(new_rows)


# ══════════════════════════════════════════════════════════════════════════════
# PARSERS (ίδια λογική με app.py)
# ══════════════════════════════════════════════════════════════════════════════
def parse_invoice_xlsx(file_content, filename):
    records = []
    try:
        if filename.lower().endswith(('.xlsx', '.xls')):
            df_raw = pd.read_excel(io.BytesIO(file_content), header=None)
        else:
            try:
                df_raw = pd.read_csv(io.BytesIO(file_content), header=None, sep=None, engine='python')
            except Exception:
                df_raw = pd.read_csv(io.BytesIO(file_content), header=None, encoding='cp1253', sep=None, engine='python')

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

        col_date  = next((c for c in df.columns if 'ΗΜΕΡΟΜΗΝΙΑ' in c), None)
        col_value = next((c for c in df.columns if 'ΑΞΙΑ' in c or 'ΣΥΝΟΛΟ' in c), None)
        col_type  = next((c for c in df.columns if 'ΤΥΠΟΣ' in c), None)
        if not (col_date and col_value and col_type):
            return records

        temp = df[[col_date, col_type, col_value]].copy()
        temp.columns = ['date', 'type', 'value']
        temp['date'] = pd.to_datetime(temp['date'], errors='coerce')
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
    except Exception:
        pass
    return records


def parse_timologiseis_xlsx(file_content):
    try:
        df_raw = pd.read_excel(io.BytesIO(file_content), header=None)
    except Exception:
        return None
    for i in range(len(df_raw) - 1, -1, -1):
        row = df_raw.iloc[i]
        row_text = " ".join([str(x) for x in row.values if pd.notna(x)])
        m = re.search(r"ΠΛΗΡΩΜΗ\s+ΜΕ\s+ΕΠΙΤΑΓΗ\s+(\d{1,2})[./](\d{1,2})[./](\d{4})", row_text, re.IGNORECASE)
        if m:
            try:
                check_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except Exception:
                continue
            amount = None
            if len(row.values) > 8:
                v8 = row.values[8]
                if isinstance(v8, (int, float)) and pd.notna(v8):
                    amount = float(v8)
                else:
                    amount = _parse_number(v8)
            if amount is None or amount == 0:
                for x in row.values:
                    if isinstance(x, float) and pd.notna(x) and x != int(x):
                        amount = float(x)
                        break
            if amount is not None:
                period_m = re.search(r"ΠΕΡΙΟΔΟΥ?\s*([\d.]+\s*-\s*[\d.]+)", row_text)
                period = period_m.group(1).strip() if period_m else ""
                return {"check_date": check_date, "period": period, "amount": round(abs(amount), 2)}
    return None


def _is_timol_email(msg):
    subj = (getattr(msg, "subject", "") or "").upper()
    sender = (getattr(msg, "from_", "") or "").lower()
    if TIMOL_SUBJECT_KW in subj:
        return True
    if "ab.gr" in sender and ("ΤΙΜΟΛΟΓ" in subj or "ΒΑΣΙΛΟΠΟΥΛ" in subj):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# FETCH
# ══════════════════════════════════════════════════════════════════════════════
def sync_invoices(wb, pw):
    new_recs = []
    try:
        with MailBox("imap.gmail.com").login(INVOICES_EMAIL_USER, pw) as mb:
            msgs = list(mb.fetch(AND(from_=INVOICES_EMAIL_SENDER), limit=INV_LIMIT, reverse=True))
            for msg in msgs:
                for att in msg.attachments:
                    fname = att.filename or ""
                    if fname.lower().endswith((".xlsx", ".xls", ".csv")):
                        new_recs.extend(parse_invoice_xlsx(att.payload, fname))
    except Exception as e:
        print(f"  ⚠️ Σφάλμα παραστατικών: {e}")
        return 0
    return merge_invoices(wb, new_recs)


def sync_timologiseis(wb, pw):
    new_recs = []
    try:
        with MailBox("imap.gmail.com").login(TIMOL_EMAIL_USER, pw) as mb:
            msgs = list(mb.fetch(limit=TIMOL_LIMIT, reverse=True, mark_seen=False))
            for msg in msgs:
                if not _is_timol_email(msg):
                    continue
                for att in msg.attachments:
                    fname = att.filename or ""
                    if fname.lower().endswith((".xlsx", ".xls")):
                        rec = parse_timologiseis_xlsx(att.payload)
                        if rec:
                            new_recs.append(rec)
    except Exception as e:
        print(f"  ⚠️ Σφάλμα τιμολογήσεων: {e}")
        return 0
    return merge_timologiseis(wb, new_recs)


def main():
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("❌ Λείπει το GOOGLE_KEY_JSON")
        sys.exit(1)

    print(f"▶ Συγχρονισμός Παραστατικών & Τιμολογήσεων — {datetime.now():%Y-%m-%d %H:%M}")
    wb = _get_wb()

    inv_pw = os.environ.get("EMAIL_PASS", "")
    tim_pw = os.environ.get("SALES_EMAIL_PASS", "")

    print("\n🧾 ΠΑΡΑΣΤΑΤΙΚΑ")
    if inv_pw:
        n = sync_invoices(wb, inv_pw)
        print(f"  ✅ {n} νέα παραστατικά." if n else "  ℹ️ Κανένα νέο παραστατικό.")
    else:
        print("  ⚠️ Λείπει το EMAIL_PASS — παράλειψη.")

    print("\n💳 ΤΙΜΟΛΟΓΗΣΕΙΣ")
    if tim_pw:
        n = sync_timologiseis(wb, tim_pw)
        print(f"  ✅ {n} νέες τιμολογήσεις." if n else "  ℹ️ Καμία νέα τιμολόγηση.")
    else:
        print("  ⚠️ Λείπει το SALES_EMAIL_PASS — παράλειψη.")

    print("\n🎉 Ολοκληρώθηκε.")


if __name__ == "__main__":
    main()
