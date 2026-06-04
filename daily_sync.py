"""
daily_sync.py
Τρέχει από GitHub Actions κάθε πρωί.
Κατεβάζει νέα παραστατικά & αναφορές πωλήσεων → αποθηκεύει στο Google Sheets.
"""
import os
import io
import re
import json
import pandas as pd
from datetime import date, datetime, timedelta
from imap_tools import MailBox, AND
from pdf2image import convert_from_bytes
import pytesseract
import gspread
from google.oauth2.service_account import Credentials

# ── CONFIG ────────────────────────────────────────────────────────────────────
SPREADSHEET_ID        = "1KWX5PH0Dg-dhfMfT8-jCd-Jft9f80I1E2Wss1w8QTlA"
INVOICES_EMAIL_USER   = "abf.skyros@gmail.com"
INVOICES_EMAIL_SENDER = "Notifications@WeDoConnect.com"
SALES_EMAIL_USER      = "ftoulisgm@gmail.com"
SALES_EMAIL_SENDER    = "abf.skyros@gmail.com"
SALES_SUBJECT_KW      = "ΑΒ ΣΚΥΡΟΣ"

INV_PW   = os.environ.get("INV_EMAIL_PASS", "")
SALES_PW = os.environ.get("SALES_EMAIL_PASS", "")
KEY_PATH = os.environ.get("GOOGLE_KEY_PATH", "ab-skyros-key.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_NS_EXCLUDE = [1082.0]
_YEAR_GUARD = set(range(2018, 2032))

# ── GOOGLE SHEETS AUTH ────────────────────────────────────────────────────────
def get_sheet(name):
    with open(KEY_PATH) as f:
        info = json.load(f)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    wb = client.open_by_key(SPREADSHEET_ID)
    return wb.worksheet(name)

# ── OCR HELPERS ───────────────────────────────────────────────────────────────
def _num(s):
    if not s: return None
    s = s.strip().replace(" ","").replace("€","").rstrip(".,")
    if not s: return None
    if "." in s and "," in s:
        s = s.replace(".","").replace(",",".") if s.rfind(",") > s.rfind(".") else s.replace(",","")
    elif "," in s:
        s = s.replace(",",".")
    try: return float(s)
    except: return None

def extract_pdf(pdf_bytes):
    r = {"date": None, "net_sales": None, "customers": None, "avg_basket": None}
    try:
        images = convert_from_bytes(pdf_bytes, dpi=180, first_page=1, last_page=10)
        if not images: return r
        pages = []
        for img in images:
            t = pytesseract.image_to_string(img, lang="ell+eng", config="--psm 6 --oem 3")
            if not any(k in t for k in ("Run On","Totals","NetDay","Branch","For ","Department","Hourly")):
                t = pytesseract.image_to_string(img.rotate(90, expand=True), lang="ell+eng", config="--psm 6 --oem 3")
            pages.append(t)
        txt_all = "\n".join(pages)

        m = re.search(r'[Rr]un\s+[Oo0]n\s*[:\s]+(\d{1,2})[/.](\d{1,2})[/.](\d{4})', txt_all)
        if m:
            try: r["date"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except: pass
        if not r["date"]:
            m = re.search(r'\bFor\s+(\d{1,2})[/.](\d{1,2})[/.](\d{4})', txt_all, re.IGNORECASE)
            if m:
                try: r["date"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                except: pass

        for page_txt in pages:
            if "Totals" not in page_txt and "totals" not in page_txt: continue
            m = re.search(r'[Tt]otals?\s*:?\s*([\d.,]{4,12})\s+(100[.,]\d+)\s+(\d{2,4})', page_txt)
            if m:
                ns = _num(m.group(1))
                try: cus = int(re.sub(r'[^\d]', '', m.group(3)))
                except: cus = 0
                if ns and 2000 < ns < 80000 and ns not in _NS_EXCLUDE:
                    r["net_sales"] = ns
                if 50 < cus < 2000 and cus not in _YEAR_GUARD:
                    r["customers"] = cus
                if r["net_sales"]: break

        if not r["net_sales"]:
            for pat in [r'NetDaySalDis\s+([\d.,]+)', r'Ne[t7][Dd]ay[Ss]al[Dd][i1][s5]\s+([\d.,]+)']:
                m = re.search(pat, txt_all, re.IGNORECASE)
                if m:
                    v = _num(m.group(1))
                    if v and 2000 < v < 80000 and v not in _NS_EXCLUDE:
                        r["net_sales"] = v; break

        if r["net_sales"] and r["customers"] and not r["avg_basket"]:
            ab = r["net_sales"] / r["customers"]
            if 5 < ab < 200: r["avg_basket"] = round(ab, 2)
    except Exception as e:
        print(f"  OCR error: {e}")
    return r

# ── INVOICES SYNC ─────────────────────────────────────────────────────────────
def find_header_and_load(file_content, filename):
    try:
        is_excel = filename.lower().endswith(('.xlsx', '.xls'))
        df_raw = pd.read_excel(io.BytesIO(file_content), header=None) if is_excel else \
                 pd.read_csv(io.BytesIO(file_content), header=None, sep=None, engine='python')
        for i in range(min(40, len(df_raw))):
            row_str = " ".join([str(x).upper() for x in df_raw.iloc[i].values if pd.notna(x)])
            if "ΤΥΠΟΣ" in row_str and "ΗΜΕΡΟΜΗΝΙΑ" in row_str:
                df = df_raw.iloc[i+1:].copy()
                headers = [str(h).strip().upper() for h in df_raw.iloc[i]]
                df.columns = headers
                df = df.loc[:, ~df.columns.str.contains('NAN|UNNAMED', case=False)]
                return df.reset_index(drop=True)
    except: pass
    return None

def sync_invoices():
    print("📄 Συγχρονισμός Παραστατικών...")
    if not INV_PW:
        print("  ⚠️  INV_EMAIL_PASS δεν ορίστηκε — παράλειψη.")
        return

    ws = get_sheet("invoices")
    existing = ws.get_all_records()
    existing_keys = {f"{r.get('date','')}|{r.get('type','')}|{r.get('value','')}" for r in existing}
    if not existing:
        ws.append_row(["date", "type", "value"])

    new_rows = []
    try:
        with MailBox('imap.gmail.com').login(INVOICES_EMAIL_USER, INV_PW) as mb:
            # Μόνο emails των τελευταίων 7 ημερών
            since_dt = date.today() - timedelta(days=7)
            messages = list(mb.fetch(AND(from_=INVOICES_EMAIL_SENDER, date_gte=since_dt), limit=30, reverse=True))
            print(f"  Βρέθηκαν {len(messages)} emails.")
            for msg in messages:
                for att in msg.attachments:
                    if att.filename.lower().endswith(('.xlsx', '.csv', '.xls')):
                        df = find_header_and_load(att.payload, att.filename)
                        if df is None: continue
                        col_date  = next((c for c in df.columns if 'ΗΜΕΡΟΜΗΝΙΑ' in c), None)
                        col_value = next((c for c in df.columns if 'ΑΞΙΑ' in c or 'ΣΥΝΟΛΟ' in c), None)
                        col_type  = next((c for c in df.columns if 'ΤΥΠΟΣ' in c), None)
                        if not (col_date and col_value and col_type): continue
                        for _, row in df.iterrows():
                            d = pd.to_datetime(row[col_date], errors='coerce')
                            if pd.isna(d): continue
                            d_str = d.strftime("%Y-%m-%d")
                            v_raw = str(row[col_value]).replace('€','').replace(',','.').strip()
                            try: v = round(float(v_raw), 2)
                            except: v = 0.0
                            t = str(row[col_type])
                            key = f"{d_str}|{t}|{v}"
                            if key in existing_keys: continue
                            existing_keys.add(key)
                            new_rows.append([d_str, t, v])
    except Exception as e:
        print(f"  ❌ Email error: {e}")

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    print(f"  ✅ {len(new_rows)} νέα παραστατικά αποθηκεύτηκαν.")

# ── SALES SYNC ────────────────────────────────────────────────────────────────
def sync_sales():
    print("📊 Συγχρονισμός Πωλήσεων...")
    if not SALES_PW:
        print("  ⚠️  SALES_EMAIL_PASS δεν ορίστηκε — παράλειψη.")
        return

    ws = get_sheet("sales")
    existing = ws.get_all_records()
    existing_dates = {str(r.get("date","")) for r in existing}
    if not existing:
        ws.append_row(["date", "net_sales", "customers", "avg_basket"])

    # Σκανάρουμε τα τελευταία 10 ημέρες για να μην χάσουμε τίποτα
    since_dt = date.today() - timedelta(days=10)
    new_rows = []
    n_checked = 0
    try:
        with MailBox("imap.gmail.com").login(SALES_EMAIL_USER, SALES_PW) as mb:
            msgs = list(mb.fetch(AND(from_=SALES_EMAIL_SENDER, date_gte=since_dt), limit=50, reverse=True, mark_seen=False))
            print(f"  Βρέθηκαν {len(msgs)} emails.")
            for msg in msgs:
                subj = (msg.subject or "").upper()
                if SALES_SUBJECT_KW not in subj and "SKYROS" not in subj: continue
                pdf = next((a for a in msg.attachments if a.filename and a.filename.lower().endswith(".pdf")), None)
                if not pdf: continue
                n_checked += 1
                rec = extract_pdf(pdf.payload)
                if not rec["date"] or rec["net_sales"] is None: continue
                d_str = rec["date"].isoformat()
                if d_str in existing_dates: continue
                existing_dates.add(d_str)
                new_rows.append([
                    d_str,
                    round(float(rec["net_sales"]), 2),
                    int(rec["customers"]) if rec["customers"] else "",
                    round(float(rec["avg_basket"]), 2) if rec["avg_basket"] else "",
                ])
    except Exception as e:
        print(f"  ❌ Email error: {e}")

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    print(f"  ✅ {len(new_rows)} νέες εγγραφές (ελέγχθηκαν {n_checked} PDF).")

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"🚀 Daily Sync — {date.today()}")
    sync_invoices()
    sync_sales()
    print("✅ Ολοκληρώθηκε!")
