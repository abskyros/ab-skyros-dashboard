"""
app.py — Κεντρική εφαρμογή ΑΒ Σκύρος
Tabs: 📄 Παραστατικά | 📊 Πωλήσεις
"""
import streamlit as st
import pandas as pd
import io
import re
from datetime import datetime, date, timedelta
from imap_tools import MailBox, AND
from pdf2image import convert_from_bytes
import pytesseract

from gsheets_helper import (
    load_sales, merge_sales,
    load_invoices, merge_invoices,
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
INVOICES_EMAIL_USER   = "abf.skyros@gmail.com"
INVOICES_EMAIL_SENDER = "Notifications@WeDoConnect.com"

SALES_EMAIL_USER   = "ftoulisgm@gmail.com"
SALES_EMAIL_SENDER = "abf.skyros@gmail.com"
SALES_SUBJECT_KW   = "ΑΒ ΣΚΥΡΟΣ"
BATCH_SIZE         = 25
DEEP_SCAN_YEARS    = 2

# ── SECRETS ───────────────────────────────────────────────────────────────────
def _secret(key, fallback=""):
    try:
        v = st.secrets.get(key, "")
        return v if v else fallback
    except:
        return fallback

INV_PW   = _secret("EMAIL_PASS")
SALES_PW = _secret("SALES_EMAIL_PASS") or _secret("EMAIL_PASS")

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ΑΒ Σκύρος — Dashboard",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
*{box-sizing:border-box;margin:0;padding:0;}
html,body,[class*="css"]{font-family:'Inter',sans-serif!important;background:#f8f9fb!important;color:#111827!important;}
.stApp{background:#f8f9fb!important;}
section[data-testid="stSidebar"]{display:none!important;}
#MainMenu,footer,header{visibility:hidden!important;}
.block-container{padding:1.5rem 1.5rem 4rem!important;max-width:980px!important;margin:0 auto!important;}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;padding-bottom:1rem;border-bottom:2px solid #e5e7eb;}
.ptitle{font-size:1.4rem;font-weight:700;color:#111827;}
.sh{font-size:.58rem;font-weight:600;letter-spacing:.18em;text-transform:uppercase;color:#9ca3af;margin:1.8rem 0 .7rem;border-bottom:1px solid #f3f4f6;padding-bottom:.4rem;}
.kr{display:grid;gap:.75rem;margin:.5rem 0 1.2rem;}
.kr4{grid-template-columns:repeat(4,1fr);}
.kr3{grid-template-columns:repeat(3,1fr);}
@media(max-width:900px){.kr4{grid-template-columns:repeat(2,1fr);}}
@media(max-width:580px){.kr4,.kr3{grid-template-columns:1fr;}.block-container{padding:1rem 1rem 3rem!important;}}
.kc{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:.9rem 1rem;position:relative;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.04);}
.kc::before{content:'';position:absolute;top:0;left:0;bottom:0;width:3px;background:var(--a,#10b981);}
.kl{font-size:.58rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#9ca3af;margin-bottom:.3rem;}
.kv{font-size:1.1rem;font-weight:700;color:#111827;}
.kv-green{color:#059669;}
.kv-red{color:#dc2626;}
.stButton>button{border-radius:9px!important;font-family:'Inter',sans-serif!important;font-size:.82rem!important;font-weight:600!important;padding:.6rem 1rem!important;transition:all .15s!important;}
.btn-g>button{background:#10b981!important;border:none!important;color:#fff!important;}
.btn-g>button:hover{opacity:.88!important;}
[data-baseweb="tab-list"]{background:transparent!important;border-bottom:1px solid #e5e7eb!important;gap:.2rem!important;}
[data-baseweb="tab"]{background:transparent!important;border:none!important;color:#6b7280!important;font-size:.78rem!important;font-weight:600!important;letter-spacing:.05em!important;text-transform:uppercase!important;padding:.5rem .9rem!important;border-radius:8px 8px 0 0!important;}
[aria-selected="true"][data-baseweb="tab"]{color:#10b981!important;background:#ecfdf5!important;border-bottom:2px solid #10b981!important;}
[data-testid="stDataFrame"]{border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;}
.info-box{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:.8rem 1rem;font-size:.73rem;color:#059669;margin:.6rem 0;}
.warn-box{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:.8rem 1rem;font-size:.73rem;color:#92400e;margin:.6rem 0;}
.prog-wrap{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;margin:.5rem 0;}
.prog-title{font-size:.75rem;font-weight:600;color:#0f172a;margin-bottom:.4rem;}
.prog-sub{font-size:.65rem;color:#94a3b8;margin-top:.35rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.main-tabs>[data-baseweb="tab"]{font-size:.9rem!important;padding:.7rem 1.5rem!important;}
</style>
""", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
MONTHS_GR = ["Ιαν","Φεβ","Μαρ","Απρ","Μαι","Ιουν","Ιουλ","Αυγ","Σεπ","Οκτ","Νοε","Δεκ"]
MONTHS_GR_FULL = ["Ιανουάριος","Φεβρουάριος","Μάρτιος","Απρίλιος","Μάιος","Ιούνιος",
                  "Ιούλιος","Αύγουστος","Σεπτέμβριος","Οκτώβριος","Νοέμβριος","Δεκέμβριος"]

def fmt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "—"
    rounded = round(float(v), 2)
    if rounded == int(rounded):
        return f"{int(rounded):,}€".replace(",",".")
    return f"{rounded:,.2f}€".replace(",","X").replace(".",",").replace("X",".")

def get_week_range(d):
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)

# ══════════════════════════════════════════════════════════════════════════════
# OCR ENGINE (από Sales.py)
# ══════════════════════════════════════════════════════════════════════════════
def _num(s: str):
    if not s: return None
    s = s.strip().replace(" ","").replace("€","").rstrip(".,")
    if not s: return None
    if "." in s and "," in s:
        s = s.replace(".","").replace(",",".") if s.rfind(",") > s.rfind(".") else s.replace(",","")
    elif "," in s:
        s = s.replace(",",".")
    try: return float(s)
    except: return None

def _find(txt, patterns, lo=None, hi=None, exclude=None):
    for pat in patterns:
        m = re.search(pat, txt, re.IGNORECASE)
        if m:
            try:
                v = _num(m.group(1))
                if v is None: continue
                if lo is not None and v < lo: continue
                if hi is not None and v > hi: continue
                if exclude and any(abs(v - ex) < 0.5 for ex in exclude): continue
                return v
            except: continue
    return None

_NS_EXCLUDE = [1082.0]
_YEAR_GUARD = set(range(2018, 2032))

def extract_pdf(pdf_bytes: bytes) -> dict:
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
                if r["net_sales"] and not r["avg_basket"]:
                    m2 = re.search(
                        r'[Tt]otals?\s*:?\s*[\d.,]+\s+100[.,]\d+\s+\d+\s+[\d.,]+\s+[\d.,]+\s+[\d.,]+\s+([\d.,]+)',
                        page_txt)
                    if m2:
                        ab = _num(m2.group(1))
                        if ab and 5 < ab < 200: r["avg_basket"] = ab
                if r["net_sales"]: break

        if not r["net_sales"]:
            r["net_sales"] = _find(txt_all, [
                r'NetDaySalDis\s+([\d.,]+)',
                r'Ne[t7][Dd]ay[Ss]al[Dd][i1][s5]\s+([\d.,]+)',
            ], lo=2000, hi=80000, exclude=_NS_EXCLUDE)

        if not r["customers"]:
            m = re.search(r'Num[O0]fCus\s+([\d.,\s]+)', txt_all, re.IGNORECASE)
            if m:
                try:
                    v = int(re.sub(r'[.,\s]', '', m.group(1).strip()))
                    if 50 < v < 2000 and v not in _YEAR_GUARD: r["customers"] = v
                except: pass

        if not r["avg_basket"]:
            r["avg_basket"] = _find(txt_all, [r'AvgSalCus\s+([\d.,]+)'], lo=5, hi=200)

        if r["net_sales"] and r["customers"] and not r["avg_basket"]:
            ab = r["net_sales"] / r["customers"]
            if 5 < ab < 200: r["avg_basket"] = round(ab, 2)
    except: pass
    return r

# ── SALES: Email fetch ─────────────────────────────────────────────────────────
def _is_valid_sales(subj):
    s = (subj or "").upper()
    return SALES_SUBJECT_KW in s or "SKYROS" in s

def fetch_sales(pw, since=None, want_records=60, email_scan_limit=400):
    recs, errs, n = [], [], 0
    try:
        with MailBox("imap.gmail.com").login(SALES_EMAIL_USER, pw) as mb:
            for msg in mb.fetch(AND(from_=SALES_EMAIL_SENDER), limit=email_scan_limit, reverse=True, mark_seen=False):
                if len(recs) >= want_records: break
                msg_dt = msg.date
                if msg_dt and hasattr(msg_dt, 'tzinfo') and msg_dt.tzinfo is not None:
                    msg_dt = msg_dt.replace(tzinfo=None)
                d = msg_dt.date() if msg_dt else None
                if since and d and d < since: continue
                if not _is_valid_sales(msg.subject): continue
                pdf = next((a for a in msg.attachments if a.filename and a.filename.lower().endswith(".pdf")), None)
                if not pdf: continue
                n += 1
                rec = extract_pdf(pdf.payload)
                if rec["date"] and rec["net_sales"] is not None:
                    recs.append(rec)
    except Exception as e: errs.append(str(e))
    return recs, errs, n

def deep_scan_sales(pw):
    cutoff = date.today() - timedelta(days=365*DEEP_SCAN_YEARS)
    s = {"phase":"connect","total":0,"done":0,"saved":0,"cur":"","err":None,"ok":False}
    yield s.copy()
    try:
        with MailBox("imap.gmail.com").login(SALES_EMAIL_USER, pw) as mb:
            s["phase"] = "listing"; yield s.copy()
            hdrs = [h for h in mb.fetch(AND(from_=SALES_EMAIL_SENDER), limit=3000, reverse=True, mark_seen=False, headers_only=True)
                    if h.date and h.date.date() >= cutoff and _is_valid_sales(h.subject)]
            s["total"] = len(hdrs); s["phase"] = "ocr"; yield s.copy()
            if not hdrs: s["ok"] = True; yield s.copy(); return
            batch = []
            for i, h in enumerate(hdrs):
                s["done"] = i+1; s["cur"] = (h.subject or "")[:50]; yield s.copy()
                try:
                    full = list(mb.fetch(AND(uid=str(h.uid)), mark_seen=False))
                    if not full: continue
                    pdf = next((a for a in full[0].attachments if a.filename and a.filename.lower().endswith(".pdf")), None)
                    if not pdf: continue
                    rec = extract_pdf(pdf.payload)
                    if rec["date"] and rec["net_sales"] is not None:
                        batch.append(rec)
                    if len(batch) >= BATCH_SIZE:
                        s["saved"] += merge_sales(batch); batch = []; yield s.copy()
                except: continue
            if batch: s["saved"] += merge_sales(batch)
            s["ok"] = True; yield s.copy()
    except Exception as e:
        s["err"] = str(e); s["ok"] = True; yield s.copy()

# ── INVOICES: Email fetch ──────────────────────────────────────────────────────
def find_header_and_load(file_content, filename):
    try:
        is_excel = filename.lower().endswith(('.xlsx', '.xls'))
        if is_excel:
            df_raw = pd.read_excel(io.BytesIO(file_content), header=None)
        else:
            try:
                df_raw = pd.read_csv(io.BytesIO(file_content), header=None, sep=None, engine='python')
            except:
                df_raw = pd.read_csv(io.BytesIO(file_content), header=None, encoding='cp1253', sep=None, engine='python')

        header_row_index = -1
        for i in range(min(40, len(df_raw))):
            row_values = [str(x).upper() for x in df_raw.iloc[i].values if pd.notna(x)]
            row_str = " ".join(row_values)
            if "ΤΥΠΟΣ" in row_str and "ΗΜΕΡΟΜΗΝΙΑ" in row_str:
                header_row_index = i
                break
        if header_row_index == -1: return None
        df = df_raw.iloc[header_row_index + 1:].copy()
        headers = [str(h).strip().upper() for h in df_raw.iloc[header_row_index]]
        df.columns = headers
        df = df.loc[:, df.columns.notna()]
        df = df.loc[:, ~df.columns.str.contains('NAN|UNNAMED', case=False)]
        return df.reset_index(drop=True)
    except:
        return None

def fetch_and_store_invoices(pw, limit=50):
    """Κατεβάζει παραστατικά από email και τα αποθηκεύει στο Sheets."""
    new_recs = []
    errors = []
    try:
        with MailBox('imap.gmail.com').login(INVOICES_EMAIL_USER, pw) as mailbox:
            messages = list(mailbox.fetch(AND(from_=INVOICES_EMAIL_SENDER), limit=limit, reverse=True))
            for msg in messages:
                for att in msg.attachments:
                    if att.filename.lower().endswith(('.xlsx', '.csv', '.xls')):
                        df = find_header_and_load(att.payload, att.filename)
                        if df is not None:
                            col_date  = next((c for c in df.columns if 'ΗΜΕΡΟΜΗΝΙΑ' in c), None)
                            col_value = next((c for c in df.columns if 'ΑΞΙΑ' in c or 'ΣΥΝΟΛΟ' in c), None)
                            col_type  = next((c for c in df.columns if 'ΤΥΠΟΣ' in c), None)
                            if col_date and col_value and col_type:
                                for _, row in df.iterrows():
                                    d = pd.to_datetime(row[col_date], errors='coerce')
                                    if pd.isna(d): continue
                                    v_raw = str(row[col_value]).replace('€','').replace(',','.').strip()
                                    try: v = float(v_raw)
                                    except: v = 0.0
                                    new_recs.append({
                                        "date": d,
                                        "type": str(row[col_type]),
                                        "value": v,
                                    })
    except Exception as e:
        errors.append(str(e))
    saved = merge_invoices(new_recs)
    return saved, errors

# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="topbar">
  <div class="ptitle">🏪 ΑΒ Σκύρος — Dashboard</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_inv, tab_sales = st.tabs(["📄 Παραστατικά", "📊 Πωλήσεις"])

today = date.today()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — ΠΑΡΑΣΤΑΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
with tab_inv:
    df_inv = load_invoices()

    col_ref, _ = st.columns([1, 4])
    with col_ref:
        st.markdown('<div class="btn-g">', unsafe_allow_html=True)
        if st.button("🔄 Ανανέωση Παραστατικών", key="inv_refresh", use_container_width=True):
            if INV_PW:
                with st.spinner("Σύνδεση στο email & αποθήκευση..."):
                    saved, errs = fetch_and_store_invoices(INV_PW, limit=50)
                if errs:
                    st.error(f"❌ {errs[0]}")
                else:
                    st.success(f"✅ {saved} νέα παραστατικά αποθηκεύτηκαν.")
                    load_invoices.clear()
                    st.rerun()
            else:
                st.error("❌ Δεν βρέθηκε EMAIL_PASS στα Secrets.")
        st.markdown("</div>", unsafe_allow_html=True)

    sub1, sub2 = st.tabs(["📅 Εβδομαδιαία", "📆 Μηνιαία"])

    # ── Εβδομαδιαία ────────────────────────────────────────────────────────
    with sub1:
        if df_inv.empty:
            st.markdown('<div class="warn-box">⚠️ Δεν υπάρχουν δεδομένα. Πατήστε "Ανανέωση Παραστατικών".</div>', unsafe_allow_html=True)
        else:
            sel_date = st.date_input("Επίλεξε ημέρα για εβδομάδα:", today, key="inv_week_date")
            start_w, end_w = get_week_range(datetime.combine(sel_date, datetime.min.time()))
            st.markdown(f'<div class="info-box">📅 Εβδομάδα: <b>{start_w.strftime("%d/%m/%Y")}</b> — <b>{end_w.strftime("%d/%m/%Y")}</b></div>', unsafe_allow_html=True)

            mask = (df_inv['date'] >= pd.Timestamp(start_w)) & (df_inv['date'] <= pd.Timestamp(end_w))
            w_df = df_inv.loc[mask]

            if not w_df.empty:
                inv_v = w_df[~w_df['type'].str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]['value'].sum()
                crd_v = w_df[w_df['type'].str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]['value'].sum()
                net_v = inv_v - crd_v

                st.markdown(f"""<div class="kr kr3">
                  <div class="kc" style="--a:#10b981"><div class="kl">Τιμολόγια</div><div class="kv kv-green">{fmt(inv_v)}</div></div>
                  <div class="kc" style="--a:#ef4444"><div class="kl">Πιστωτικά</div><div class="kv kv-red">-{fmt(crd_v)}</div></div>
                  <div class="kc" style="--a:#6b8fd4"><div class="kl">Καθαρό Σύνολο</div><div class="kv">{fmt(net_v)}</div></div>
                </div>""", unsafe_allow_html=True)

                disp = w_df.copy()
                disp["date"] = disp["date"].dt.strftime("%d/%m/%Y")
                st.dataframe(
                    disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"})
                        .style.format({"ΑΞΙΑ": "{:.2f} €"}),
                    use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="warn-box">Δεν υπάρχουν εγγραφές για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

    # ── Μηνιαία ─────────────────────────────────────────────────────────────
    with sub2:
        if df_inv.empty:
            st.markdown('<div class="warn-box">⚠️ Δεν υπάρχουν δεδομένα.</div>', unsafe_allow_html=True)
        else:
            col_a, col_b = st.columns(2)
            with col_a:
                s_m = st.selectbox("Μήνας", range(1,13), format_func=lambda x: MONTHS_GR_FULL[x-1], index=today.month-1, key="inv_month")
            with col_b:
                years_inv = sorted(df_inv['date'].dt.year.unique(), reverse=True)
                s_y = st.selectbox("Έτος", years_inv, key="inv_year")

            mask_m = (df_inv['date'].dt.month == s_m) & (df_inv['date'].dt.year == s_y)
            m_df = df_inv.loc[mask_m]

            if not m_df.empty:
                inv_m = m_df[~m_df['type'].str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]['value'].sum()
                crd_m = m_df[m_df['type'].str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]['value'].sum()
                net_m = inv_m - crd_m

                st.markdown(f"""<div class="kr kr3">
                  <div class="kc" style="--a:#10b981"><div class="kl">Τιμολόγια Μήνα</div><div class="kv kv-green">{fmt(inv_m)}</div></div>
                  <div class="kc" style="--a:#ef4444"><div class="kl">Πιστωτικά Μήνα</div><div class="kv kv-red">-{fmt(crd_m)}</div></div>
                  <div class="kc" style="--a:#6b8fd4"><div class="kl">Σύνολο Μήνα</div><div class="kv">{fmt(net_m)}</div></div>
                </div>""", unsafe_allow_html=True)

                disp = m_df.copy()
                disp["date"] = disp["date"].dt.strftime("%d/%m/%Y")
                st.dataframe(
                    disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"})
                        .style.format({"ΑΞΙΑ": "{:.2f} €"}),
                    use_container_width=True, hide_index=True)

                csv = m_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).to_csv(index=False).encode("utf-8-sig")
                st.download_button(f"📥 Λήψη {MONTHS_GR_FULL[s_m-1]} {s_y} CSV", csv, f"invoices_{s_y}_{s_m:02d}.csv", "text/csv")
            else:
                st.markdown('<div class="warn-box">Δεν υπάρχουν εγγραφές για αυτόν τον μήνα.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ΠΩΛΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
with tab_sales:
    df_sales = load_sales()

    sub_week, sub_month, sub_update = st.tabs(["📅 Εβδομαδιαία", "📆 Μηνιαία", "🔄 Ενημέρωση"])

    # ── Εβδομαδιαία ────────────────────────────────────────────────────────
    with sub_week:
        if df_sales.empty:
            st.markdown('<div class="warn-box">⚠️ Δεν υπάρχουν δεδομένα. Μεταβείτε στην καρτέλα <b>Ενημέρωση</b>.</div>', unsafe_allow_html=True)
        else:
            sel_date = st.date_input("Επίλεξε ημέρα για εβδομάδα:", today, key="sales_week_date")
            start_w, end_w = get_week_range(sel_date)
            st.markdown(f'<div class="info-box">📅 Εβδομάδα: <b>{start_w.strftime("%d/%m/%Y")}</b> — <b>{end_w.strftime("%d/%m/%Y")}</b></div>', unsafe_allow_html=True)

            mask_w = (df_sales["date"] >= start_w) & (df_sales["date"] <= end_w)
            w_df = df_sales[mask_w]

            if not w_df.empty:
                tot_sales = w_df["net_sales"].sum()
                avg_bask  = w_df["avg_basket"].mean()
                tot_cust  = w_df["customers"].sum()

                st.markdown(f"""<div class="kr kr3">
                  <div class="kc" style="--a:#10b981"><div class="kl">Καθαρό Εβδομάδας</div><div class="kv kv-green">{fmt(tot_sales)}</div></div>
                  <div class="kc" style="--a:#6b8fd4"><div class="kl">Πελάτες Εβδομάδας</div><div class="kv">{int(tot_cust) if pd.notna(tot_cust) else '—'}</div></div>
                  <div class="kc" style="--a:#7c5abf"><div class="kl">ΜΟ Καλαθιού</div><div class="kv">{fmt(avg_bask)}</div></div>
                </div>""", unsafe_allow_html=True)

                disp = w_df.copy()
                disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
                st.dataframe(
                    disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΚΑΘΑΡΕΣ ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"})
                        .style.format({
                            "ΚΑΘΑΡΕΣ ΠΩΛΗΣΕΙΣ": lambda v: fmt(v),
                            "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—",
                            "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—",
                        }),
                    use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="warn-box">Δεν υπάρχουν εγγραφές για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

    # ── Μηνιαία ─────────────────────────────────────────────────────────────
    with sub_month:
        if df_sales.empty:
            st.markdown('<div class="warn-box">⚠️ Δεν υπάρχουν δεδομένα.</div>', unsafe_allow_html=True)
        else:
            col_a, col_b = st.columns(2)
            with col_a:
                s_m = st.selectbox("Μήνας", range(1,13), format_func=lambda x: MONTHS_GR_FULL[x-1], index=today.month-1, key="sales_month")
            with col_b:
                available_years = sorted({r.year for r in df_sales["date"]}, reverse=True)
                s_y = st.selectbox("Έτος", available_years, key="sales_year")

            mask_m = (df_sales["date"].apply(lambda d: d.month) == s_m) & (df_sales["date"].apply(lambda d: d.year) == s_y)
            m_df = df_sales[mask_m]

            if not m_df.empty:
                tot_sales = m_df["net_sales"].sum()
                avg_daily = m_df["net_sales"].mean()
                best_day  = m_df["net_sales"].max()

                st.markdown(f"""<div class="kr kr3">
                  <div class="kc" style="--a:#10b981"><div class="kl">Σύνολο Μήνα</div><div class="kv kv-green">{fmt(tot_sales)}</div></div>
                  <div class="kc" style="--a:#6b8fd4"><div class="kl">Ημερήσιος ΜΟ</div><div class="kv">{fmt(avg_daily)}</div></div>
                  <div class="kc" style="--a:#7c5abf"><div class="kl">Καλύτερη Ημέρα</div><div class="kv">{fmt(best_day)}</div></div>
                </div>""", unsafe_allow_html=True)

                disp = m_df.copy()
                disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
                st.dataframe(
                    disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΚΑΘΑΡΕΣ ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"})
                        .style.format({
                            "ΚΑΘΑΡΕΣ ΠΩΛΗΣΕΙΣ": lambda v: fmt(v),
                            "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—",
                            "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—",
                        }),
                    use_container_width=True, hide_index=True)

                csv = m_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΚΑΘΑΡΕΣ ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).to_csv(index=False).encode("utf-8-sig")
                st.download_button(f"📥 Λήψη {MONTHS_GR_FULL[s_m-1]} {s_y} CSV", csv, f"sales_{s_y}_{s_m:02d}.csv", "text/csv")
            else:
                st.markdown('<div class="warn-box">Δεν υπάρχουν εγγραφές για αυτόν τον μήνα.</div>', unsafe_allow_html=True)

    # ── Ενημέρωση ───────────────────────────────────────────────────────────
    with sub_update:
        st.markdown('<div class="sh">Σύνδεση Email Πωλήσεων</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="info-box">📧 Λογαριασμός: <b>{SALES_EMAIL_USER}</b> — Αποστολέας: <b>{SALES_EMAIL_SENDER}</b></div>', unsafe_allow_html=True)

        if SALES_PW:
            st.markdown('<div class="info-box">🔐 App Password φορτώθηκε αυτόματα από Streamlit Secrets.</div>', unsafe_allow_html=True)
            sales_pw = SALES_PW
        else:
            st.markdown('<div class="warn-box">⚠️ Δεν βρέθηκε SALES_EMAIL_PASS στα Secrets.</div>', unsafe_allow_html=True)
            sales_pw = st.text_input("🔐 Gmail App Password", type="password", key="sales_pw_input")

        col_test, col_inc, col_full = st.columns(3)
        run_test = col_test.button("🧪 Δοκιμή (10 τελ.)", use_container_width=True)
        run_inc  = col_inc.button("⚡ Γρήγορη (Νέα μόνο)", use_container_width=True)
        run_full = col_full.button("🔍 Βαθιά (2 χρόνια)", use_container_width=True)

        if run_test and sales_pw:
            with st.spinner("OCR σε 10 τελευταία email..."):
                recs, errs, n_checked = fetch_sales(sales_pw, since=None, want_records=10, email_scan_limit=100)
            if errs:
                st.error(f"❌ {errs[0]}")
            elif recs:
                st.success(f"✅ Διαβάστηκαν {len(recs)} εγγραφές.")
                test_df = pd.DataFrame(recs).sort_values("net_sales", ascending=False).drop_duplicates("date").sort_values("date", ascending=False)
                test_df["date"] = pd.to_datetime(test_df["date"]).dt.strftime("%d/%m/%Y")
                st.dataframe(test_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}), use_container_width=True, hide_index=True)
                saved = merge_sales(recs)
                st.info(f"💾 {saved} νέες εγγραφές αποθηκεύτηκαν.")
                load_sales.clear()
            else:
                st.warning(f"⚠️ Ελέγχθηκαν {n_checked} PDF — δεν βρέθηκαν δεδομένα.")

        elif run_inc and sales_pw:
            with st.spinner("Ανάγνωση νέων email..."):
                existing = load_sales()
                since_dt = (existing["date"].max() - timedelta(days=5)) if not existing.empty else None
                recs, errs, n_checked = fetch_sales(sales_pw, since=since_dt, want_records=30, email_scan_limit=150)
            if errs:
                st.error(f"❌ {errs[0]}")
            else:
                saved = merge_sales(recs)
                if saved > 0:
                    st.success(f"✅ {saved} νέες εγγραφές από {n_checked} PDF.")
                    load_sales.clear()
                    st.rerun()
                else:
                    st.markdown(f'<div class="info-box">✅ Ελέγχθηκαν {n_checked} PDF — δεν βρέθηκαν νέα δεδομένα.</div>', unsafe_allow_html=True)

        elif run_full and sales_pw:
            st.markdown('<div class="warn-box">⏳ Βαθιά Σάρωση σε εξέλιξη. Μην κλείσετε τη σελίδα.</div>', unsafe_allow_html=True)
            prog_bar = st.progress(0)
            info_box = st.empty()
            for s in deep_scan_sales(sales_pw):
                if s["err"]:
                    info_box.error(f"Σφάλμα: {s['err']}"); break
                ph = s["phase"]
                if ph == "connect":
                    info_box.markdown('<div class="prog-wrap"><div class="prog-title">Σύνδεση...</div></div>', unsafe_allow_html=True)
                elif ph == "listing":
                    info_box.markdown('<div class="prog-wrap"><div class="prog-title">Ανάκτηση λίστας emails...</div></div>', unsafe_allow_html=True)
                elif ph == "ocr":
                    t = s["total"]; d = s["done"]
                    pct = int(d/t*100) if t else 0
                    prog_bar.progress(pct)
                    info_box.markdown(f"""<div class="prog-wrap">
                      <div class="prog-title">OCR: {d} / {t} emails</div>
                      <div class="prog-sub">💾 {s['saved']} εγγραφές ({pct}%)</div>
                      <div class="prog-sub">{s['cur']}</div>
                    </div>""", unsafe_allow_html=True)
                if s["ok"]:
                    prog_bar.progress(100)
                    st.success(f"✅ {s['total']} emails → {s['saved']} εγγραφές.")
                    load_sales.clear()
                    break

        elif (run_test or run_inc or run_full) and not sales_pw:
            st.error("❌ Εισάγετε App Password.")

        if not df_sales.empty:
            st.markdown('<div class="sh">Στατιστικά Google Sheets</div>', unsafe_allow_html=True)
            oldest = min(df_sales["date"]).strftime("%d/%m/%Y")
            newest = max(df_sales["date"]).strftime("%d/%m/%Y")
            st.markdown(f"""<div class="kr kr3">
              <div class="kc" style="--a:#10b981"><div class="kl">Σύνολο Εγγραφών</div><div class="kv">{len(df_sales)}</div></div>
              <div class="kc" style="--a:#6b8fd4"><div class="kl">Από</div><div class="kv" style="font-size:.85rem;">{oldest}</div></div>
              <div class="kc" style="--a:#6b8fd4"><div class="kl">Έως</div><div class="kv" style="font-size:.85rem;">{newest}</div></div>
            </div>""", unsafe_allow_html=True)
