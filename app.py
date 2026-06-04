"""
app.py — Κεντρική εφαρμογή ΑΒ Σκύρος
Tabs: 📄 Παραστατικά | 📊 Πωλήσεις
"""
import streamlit as st
import pandas as pd
import io, re
from datetime import datetime, date, timedelta
from imap_tools import MailBox, AND
from pdf2image import convert_from_bytes
import pytesseract
from gsheets_helper import (
    load_sales, merge_sales,
    load_invoices, merge_invoices,
)

INVOICES_EMAIL_USER   = "abf.skyros@gmail.com"
INVOICES_EMAIL_SENDER = "Notifications@WeDoConnect.com"
SALES_EMAIL_USER      = "ftoulisgm@gmail.com"
SALES_EMAIL_SENDER    = "abf.skyros@gmail.com"
SALES_SUBJECT_KW      = "ΑΒ ΣΚΥΡΟΣ"
BATCH_SIZE            = 25
DEEP_SCAN_YEARS       = 2

def _secret(key, fallback=""):
    try:
        v = st.secrets.get(key, "")
        return v if v else fallback
    except:
        return fallback

INV_PW   = _secret("EMAIL_PASS")
SALES_PW = _secret("SALES_EMAIL_PASS") or _secret("EMAIL_PASS")

st.set_page_config(page_title="ΑΒ Σκύρος — Dashboard", page_icon="🏪", layout="wide", initial_sidebar_state="collapsed")

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
.kr3{grid-template-columns:repeat(3,1fr);}
@media(max-width:580px){.kr3{grid-template-columns:1fr;}.block-container{padding:1rem 1rem 3rem!important;}}
.kc{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:.9rem 1rem;position:relative;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.04);}
.kc::before{content:'';position:absolute;top:0;left:0;bottom:0;width:3px;background:var(--a,#10b981);}
.kl{font-size:.58rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:#9ca3af;margin-bottom:.3rem;}
.kv{font-size:1.1rem;font-weight:700;color:#111827;}
.kv-green{color:#059669;}
.kv-red{color:#dc2626;}
.stButton>button{border-radius:9px!important;font-family:'Inter',sans-serif!important;font-size:.82rem!important;font-weight:600!important;padding:.6rem 1rem!important;transition:all .15s!important;}
.btn-g>button{background:#10b981!important;border:none!important;color:#fff!important;}
[data-baseweb="tab-list"]{background:transparent!important;border-bottom:1px solid #e5e7eb!important;gap:.2rem!important;}
[data-baseweb="tab"]{background:transparent!important;border:none!important;color:#6b7280!important;font-size:.78rem!important;font-weight:600!important;letter-spacing:.05em!important;text-transform:uppercase!important;padding:.5rem .9rem!important;border-radius:8px 8px 0 0!important;}
[aria-selected="true"][data-baseweb="tab"]{color:#10b981!important;background:#ecfdf5!important;border-bottom:2px solid #10b981!important;}
[data-testid="stDataFrame"]{border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;}
.info-box{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:.8rem 1rem;font-size:.73rem;color:#059669;margin:.6rem 0;}
.warn-box{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:.8rem 1rem;font-size:.73rem;color:#92400e;margin:.6rem 0;}
.err-box{background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:.8rem 1rem;font-size:.73rem;color:#dc2626;margin:.6rem 0;}
.prog-wrap{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem;margin:.5rem 0;}
.prog-title{font-size:.75rem;font-weight:600;color:#0f172a;margin-bottom:.4rem;}
.prog-sub{font-size:.65rem;color:#94a3b8;margin-top:.35rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
</style>
""", unsafe_allow_html=True)

MONTHS_GR = ["Ιανουάριος","Φεβρουάριος","Μάρτιος","Απρίλιος","Μάιος","Ιούνιος",
             "Ιούλιος","Αύγουστος","Σεπτέμβριος","Οκτώβριος","Νοέμβριος","Δεκέμβριος"]

def fmt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "—"
    r = round(float(v), 2)
    if r == int(r):
        return f"{int(r):,}€".replace(",",".")
    return f"{r:,.2f}€".replace(",","X").replace(".",",").replace("X",".")

def get_week_range(d):
    if isinstance(d, datetime): d = d.date()
    s = d - timedelta(days=d.weekday())
    return s, s + timedelta(days=6)

# ══════════════════════════════════════════════════════════════════════════════
# INVOICES PARSER
# ══════════════════════════════════════════════════════════════════════════════
def parse_invoice_xlsx(file_content, filename):
    records = []
    try:
        if filename.lower().endswith(('.xlsx', '.xls')):
            df_raw = pd.read_excel(io.BytesIO(file_content), header=None)
        else:
            try:
                df_raw = pd.read_csv(io.BytesIO(file_content), header=None, sep=None, engine='python')
            except:
                df_raw = pd.read_csv(io.BytesIO(file_content), header=None, encoding='cp1253', sep=None, engine='python')

        header_idx = -1
        for i in range(min(20, len(df_raw))):
            row_str = " ".join([str(x).upper() for x in df_raw.iloc[i].values if pd.notna(x)])
            if "ΤΥΠΟΣ" in row_str and ("ΠΑΡΑΣΤΑΤ" in row_str or "ΗΜΕΡΟΜΗΝΙΑ" in row_str):
                header_idx = i
                break
        if header_idx == -1:
            return records

        headers = [str(h).strip() for h in df_raw.iloc[header_idx].values]
        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = headers
        df = df.reset_index(drop=True)

        col_date  = next((c for c in df.columns if "ΗΜΕΡΟΜΗΝΙΑ" in str(c).upper()), None)
        col_value = next((c for c in df.columns if "ΣΥΝΟΛΙΚΗ" in str(c).upper() or ("ΑΞΙΑ" in str(c).upper() and "ΣΧΕΤ" not in str(c).upper())), None)
        col_type  = next((c for c in df.columns if "ΤΥΠΟΣ" in str(c).upper()), None)

        if not (col_date and col_value and col_type):
            return records

        for _, row in df.iterrows():
            d_raw = row[col_date]
            if pd.isna(d_raw): continue
            d = pd.to_datetime(d_raw, errors="coerce")
            if pd.isna(d): continue
            v_raw = row[col_value]
            if isinstance(v_raw, (int, float)):
                v = float(v_raw)
            else:
                v_str = str(v_raw).replace("€","").replace(" ","").strip()
                if "," in v_str and "." in v_str:
                    v_str = v_str.replace(".","").replace(",",".")
                elif "," in v_str:
                    v_str = v_str.replace(",",".")
                try: v = float(v_str)
                except: v = 0.0
            t = str(row[col_type]).strip()
            if not t or t.lower() == "nan": continue
            records.append({"date": d, "type": t, "value": v})
    except:
        pass
    return records

def fetch_and_store_invoices(pw, limit=30):
    new_recs, errors = [], []
    try:
        with MailBox("imap.gmail.com").login(INVOICES_EMAIL_USER, pw) as mb:
            msgs = list(mb.fetch(AND(from_=INVOICES_EMAIL_SENDER), limit=limit, reverse=True))
            for msg in msgs:
                for att in msg.attachments:
                    fname = att.filename or ""
                    if fname.lower().endswith((".xlsx", ".xls", ".csv")):
                        new_recs.extend(parse_invoice_xlsx(att.payload, fname))
    except Exception as e:
        errors.append(str(e))
    saved = merge_invoices(new_recs)
    return saved, errors, len(new_recs)

# ══════════════════════════════════════════════════════════════════════════════
# SALES OCR ENGINE V9
# Τα PDFs είναι landscape (rotated 90°).
# Σελίδα 1 = Department Report που έχει ΟΛΑ τα στοιχεία.
# ══════════════════════════════════════════════════════════════════════════════
def extract_sales_from_pdf(pdf_bytes):
    r = {"date": None, "net_sales": None, "customers": None, "avg_basket": None}
    try:
        images = convert_from_bytes(pdf_bytes, dpi=180, first_page=1, last_page=1)
        if not images:
            return r

        # Τα PDFs είναι landscape — rotate 90°
        t = pytesseract.image_to_string(
            images[0].rotate(90, expand=True),
            lang="ell+eng", config="--psm 6 --oem 3"
        )

        # Ημερομηνία: "Run On DD/MM/YYYY" = η ημέρα των πωλήσεων
        m = re.search(r"Run\s+[Oo0]n\s*[:\s]+(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t, re.IGNORECASE)
        if m:
            try:
                r["date"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except:
                pass
        # Fallback: "For DD/MM/YYYY" - 1 ημέρα
        if not r["date"]:
            m = re.search(r"\bFor\s+(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t, re.IGNORECASE)
            if m:
                try:
                    d_for = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    r["date"] = d_for - timedelta(days=1)
                except:
                    pass

        # NetDaySalDis: format "1.234,56" (. = χιλιάδες, , = δεκαδικά)
        m = re.search(r"Net[Dd]ay[Ss]al[Dd]is\s+([\d.,]+)", t, re.IGNORECASE)
        if not m:
            m = re.search(r"Ne[t7][Dd]ay\S+\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                v = float(raw)
                if 500 < v < 500000:
                    r["net_sales"] = round(v, 2)
            except:
                pass

        # NumOfCus
        m = re.search(r"Num[O0]fCus\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            try:
                v = int(re.sub(r"[.,]", "", m.group(1).split()[0]))
                if 10 < v < 5000:
                    r["customers"] = v
            except:
                pass

        # AvgSalCus
        m = re.search(r"Avg[Ss]al[Cc]us\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            try:
                raw = m.group(1).replace(".", "").replace(",", ".")
                v = float(raw)
                if 1 < v < 1000:
                    r["avg_basket"] = round(v, 2)
            except:
                pass

        # Αν λείπει avg_basket, υπολόγισε
        if r["net_sales"] and r["customers"] and not r["avg_basket"]:
            ab = r["net_sales"] / r["customers"]
            if 1 < ab < 1000:
                r["avg_basket"] = round(ab, 2)

    except Exception:
        pass
    return r

# ── SALES EMAIL FETCH ─────────────────────────────────────────────────────────
def _valid_sales_subj(subj):
    s = (subj or "").upper()
    return SALES_SUBJECT_KW in s or "SKYROS" in s

def fetch_sales_emails(pw, since=None, want_records=4, email_scan_limit=30):
    recs, errs, n = [], [], 0
    try:
        with MailBox("imap.gmail.com").login(SALES_EMAIL_USER, pw) as mb:
            for msg in mb.fetch(AND(from_=SALES_EMAIL_SENDER), limit=email_scan_limit, reverse=True, mark_seen=False):
                if len(recs) >= want_records:
                    break
                msg_dt = msg.date
                if msg_dt and hasattr(msg_dt, "tzinfo") and msg_dt.tzinfo:
                    msg_dt = msg_dt.replace(tzinfo=None)
                msg_d = msg_dt.date() if msg_dt else None
                if since and msg_d and msg_d < since:
                    continue
                if not _valid_sales_subj(msg.subject):
                    continue
                pdfs = [a for a in msg.attachments if a.filename and a.filename.lower().endswith(".pdf")]
                if not pdfs:
                    continue
                n += 1
                # Δοκίμασε όλα τα PDFs — το Department Report είναι συνήθως το πρώτο
                for pdf in pdfs:
                    rec = extract_sales_from_pdf(pdf.payload)
                    if rec["date"] and rec["net_sales"] is not None:
                        recs.append(rec)
                        break
    except Exception as e:
        errs.append(str(e))
    return recs, errs, n

def deep_scan_sales(pw):
    cutoff = date.today() - timedelta(days=365 * DEEP_SCAN_YEARS)
    s = {"phase":"connect","total":0,"done":0,"saved":0,"cur":"","err":None,"ok":False}
    yield s.copy()
    try:
        with MailBox("imap.gmail.com").login(SALES_EMAIL_USER, pw) as mb:
            s["phase"] = "listing"; yield s.copy()
            hdrs = [h for h in mb.fetch(AND(from_=SALES_EMAIL_SENDER), limit=3000, reverse=True, mark_seen=False, headers_only=True)
                    if h.date and h.date.date() >= cutoff and _valid_sales_subj(h.subject)]
            s["total"] = len(hdrs); s["phase"] = "ocr"; yield s.copy()
            if not hdrs:
                s["ok"] = True; yield s.copy(); return
            batch = []
            for i, h in enumerate(hdrs):
                s["done"] = i + 1; s["cur"] = (h.subject or "")[:60]; yield s.copy()
                try:
                    full = list(mb.fetch(AND(uid=str(h.uid)), mark_seen=False))
                    if not full: continue
                    pdfs = [a for a in full[0].attachments if a.filename and a.filename.lower().endswith(".pdf")]
                    if not pdfs: continue
                    for pdf in pdfs:
                        rec = extract_sales_from_pdf(pdf.payload)
                        if rec["date"] and rec["net_sales"] is not None:
                            batch.append(rec); break
                    if len(batch) >= BATCH_SIZE:
                        s["saved"] += merge_sales(batch); batch = []; yield s.copy()
                except:
                    continue
            if batch:
                s["saved"] += merge_sales(batch)
            s["ok"] = True; yield s.copy()
    except Exception as e:
        s["err"] = str(e); s["ok"] = True; yield s.copy()

# ══════════════════════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="topbar"><div class="ptitle">🏪 ΑΒ Σκύρος — Dashboard</div></div>', unsafe_allow_html=True)

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
                with st.spinner("Σύνδεση & αποθήκευση..."):
                    saved, errs, total = fetch_and_store_invoices(INV_PW, limit=30)
                if errs:
                    st.markdown(f'<div class="err-box">❌ {errs[0]}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="info-box">✅ Βρέθηκαν {total} εγγραφές — {saved} νέες αποθηκεύτηκαν.</div>', unsafe_allow_html=True)
                    load_invoices.clear()
                    st.rerun()
            else:
                st.markdown('<div class="err-box">❌ Δεν βρέθηκε EMAIL_PASS στα Secrets.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    sub_w, sub_m = st.tabs(["📅 Εβδομαδιαία", "📆 Μηνιαία"])

    with sub_w:
        if df_inv.empty:
            st.markdown('<div class="warn-box">⚠️ Χωρίς δεδομένα. Πατήστε "Ανανέωση Παραστατικών".</div>', unsafe_allow_html=True)
        else:
            sel = st.date_input("Επίλεξε ημέρα:", today, key="inv_wk")
            sw, ew = get_week_range(sel)
            st.markdown(f'<div class="info-box">📅 <b>{sw.strftime("%d/%m/%Y")}</b> — <b>{ew.strftime("%d/%m/%Y")}</b></div>', unsafe_allow_html=True)
            mask = (df_inv["date"] >= pd.Timestamp(sw)) & (df_inv["date"] <= pd.Timestamp(ew) + pd.Timedelta(hours=23, minutes=59))
            w_df = df_inv.loc[mask]
            if not w_df.empty:
                inv_v = w_df[~w_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                crd_v = w_df[w_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                st.markdown(f"""<div class="kr kr3">
                  <div class="kc" style="--a:#10b981"><div class="kl">Τιμολόγια</div><div class="kv kv-green">{fmt(inv_v)}</div></div>
                  <div class="kc" style="--a:#ef4444"><div class="kl">Πιστωτικά</div><div class="kv kv-red">-{fmt(crd_v)}</div></div>
                  <div class="kc" style="--a:#6b8fd4"><div class="kl">Καθαρό</div><div class="kv">{fmt(inv_v - crd_v)}</div></div>
                </div>""", unsafe_allow_html=True)
                disp = w_df.copy(); disp["date"] = disp["date"].dt.strftime("%d/%m/%Y")
                st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).style.format({"ΑΞΙΑ": "{:.2f} €"}), use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="warn-box">Δεν υπάρχουν εγγραφές για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

    with sub_m:
        if df_inv.empty:
            st.markdown('<div class="warn-box">⚠️ Χωρίς δεδομένα.</div>', unsafe_allow_html=True)
        else:
            ca, cb = st.columns(2)
            with ca: sm = st.selectbox("Μήνας", range(1,13), format_func=lambda x: MONTHS_GR[x-1], index=today.month-1, key="inv_mo")
            with cb:
                yrs = sorted(df_inv["date"].dt.year.unique(), reverse=True)
                sy = st.selectbox("Έτος", yrs, key="inv_yr")
            m_df = df_inv[(df_inv["date"].dt.month == sm) & (df_inv["date"].dt.year == sy)]
            if not m_df.empty:
                inv_m = m_df[~m_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                crd_m = m_df[m_df["type"].str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)]["value"].sum()
                st.markdown(f"""<div class="kr kr3">
                  <div class="kc" style="--a:#10b981"><div class="kl">Τιμολόγια</div><div class="kv kv-green">{fmt(inv_m)}</div></div>
                  <div class="kc" style="--a:#ef4444"><div class="kl">Πιστωτικά</div><div class="kv kv-red">-{fmt(crd_m)}</div></div>
                  <div class="kc" style="--a:#6b8fd4"><div class="kl">Σύνολο Μήνα</div><div class="kv">{fmt(inv_m - crd_m)}</div></div>
                </div>""", unsafe_allow_html=True)
                disp = m_df.copy(); disp["date"] = disp["date"].dt.strftime("%d/%m/%Y")
                st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).style.format({"ΑΞΙΑ": "{:.2f} €"}), use_container_width=True, hide_index=True)
                csv = m_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","type":"ΤΥΠΟΣ","value":"ΑΞΙΑ"}).to_csv(index=False).encode("utf-8-sig")
                st.download_button(f"📥 Λήψη {MONTHS_GR[sm-1]} {sy}", csv, f"invoices_{sy}_{sm:02d}.csv", "text/csv")
            else:
                st.markdown('<div class="warn-box">Δεν υπάρχουν εγγραφές για αυτόν τον μήνα.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ΠΩΛΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
with tab_sales:
    df_s = load_sales()
    t_wk, t_mo, t_up = st.tabs(["📅 Εβδομαδιαία", "📆 Μηνιαία", "🔄 Ενημέρωση"])

    with t_wk:
        if df_s.empty:
            st.markdown('<div class="warn-box">⚠️ Δεν υπάρχουν δεδομένα. Μεταβείτε στην καρτέλα <b>Ενημέρωση</b>.</div>', unsafe_allow_html=True)
        else:
            sel = st.date_input("Επίλεξε ημέρα:", today, key="s_wk")
            sw, ew = get_week_range(sel)
            st.markdown(f'<div class="info-box">📅 <b>{sw.strftime("%d/%m/%Y")}</b> — <b>{ew.strftime("%d/%m/%Y")}</b></div>', unsafe_allow_html=True)
            w_df = df_s[(df_s["date"] >= sw) & (df_s["date"] <= ew)]
            if not w_df.empty:
                tot = w_df["net_sales"].sum()
                cst = w_df["customers"].sum()
                avg = w_df["avg_basket"].mean()
                st.markdown(f"""<div class="kr kr3">
                  <div class="kc" style="--a:#10b981"><div class="kl">Καθαρές Πωλήσεις</div><div class="kv kv-green">{fmt(tot)}</div></div>
                  <div class="kc" style="--a:#6b8fd4"><div class="kl">Πελάτες</div><div class="kv">{int(cst) if pd.notna(cst) else '—'}</div></div>
                  <div class="kc" style="--a:#7c5abf"><div class="kl">ΜΟ Καλαθιού</div><div class="kv">{fmt(avg)}</div></div>
                </div>""", unsafe_allow_html=True)
                disp = w_df.copy(); disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
                st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).style.format({"ΠΩΛΗΣΕΙΣ": lambda v: fmt(v), "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—", "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—"}), use_container_width=True, hide_index=True)
            else:
                st.markdown('<div class="warn-box">Δεν υπάρχουν εγγραφές για αυτή την εβδομάδα.</div>', unsafe_allow_html=True)

    with t_mo:
        if df_s.empty:
            st.markdown('<div class="warn-box">⚠️ Δεν υπάρχουν δεδομένα.</div>', unsafe_allow_html=True)
        else:
            ca, cb = st.columns(2)
            with ca: sm = st.selectbox("Μήνας", range(1,13), format_func=lambda x: MONTHS_GR[x-1], index=today.month-1, key="s_mo")
            with cb:
                yrs = sorted({r.year for r in df_s["date"]}, reverse=True)
                sy = st.selectbox("Έτος", yrs, key="s_yr")
            m_df = df_s[(df_s["date"].apply(lambda d: d.month) == sm) & (df_s["date"].apply(lambda d: d.year) == sy)]
            if not m_df.empty:
                tot = m_df["net_sales"].sum(); avg = m_df["net_sales"].mean(); best = m_df["net_sales"].max()
                st.markdown(f"""<div class="kr kr3">
                  <div class="kc" style="--a:#10b981"><div class="kl">Σύνολο Μήνα</div><div class="kv kv-green">{fmt(tot)}</div></div>
                  <div class="kc" style="--a:#6b8fd4"><div class="kl">Ημερήσιος ΜΟ</div><div class="kv">{fmt(avg)}</div></div>
                  <div class="kc" style="--a:#7c5abf"><div class="kl">Καλύτερη Ημέρα</div><div class="kv">{fmt(best)}</div></div>
                </div>""", unsafe_allow_html=True)
                disp = m_df.copy(); disp["date"] = disp["date"].apply(lambda d: d.strftime("%d/%m/%Y"))
                st.dataframe(disp.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).style.format({"ΠΩΛΗΣΕΙΣ": lambda v: fmt(v), "ΜΟ ΚΑΛΑΘΙΟΥ": lambda v: fmt(v) if pd.notna(v) else "—", "ΠΕΛΑΤΕΣ": lambda v: f"{int(v)}" if pd.notna(v) else "—"}), use_container_width=True, hide_index=True)
                csv = m_df.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}).to_csv(index=False).encode("utf-8-sig")
                st.download_button(f"📥 Λήψη {MONTHS_GR[sm-1]} {sy}", csv, f"sales_{sy}_{sm:02d}.csv", "text/csv")
            else:
                st.markdown('<div class="warn-box">Δεν υπάρχουν εγγραφές για αυτόν τον μήνα.</div>', unsafe_allow_html=True)

    with t_up:
        st.markdown('<div class="sh">Σύνδεση Email Πωλήσεων</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="info-box">📧 <b>{SALES_EMAIL_USER}</b> ← <b>{SALES_EMAIL_SENDER}</b></div>', unsafe_allow_html=True)

        if SALES_PW:
            st.markdown('<div class="info-box">🔐 App Password από Streamlit Secrets.</div>', unsafe_allow_html=True)
            spw = SALES_PW
        else:
            st.markdown('<div class="warn-box">⚠️ Δεν βρέθηκε SALES_EMAIL_PASS.</div>', unsafe_allow_html=True)
            spw = st.text_input("🔐 Gmail App Password", type="password", key="spw")

        c1, c2, c3 = st.columns(3)
        r_test = c1.button("🧪 Δοκιμή (4 email)", use_container_width=True)
        r_inc  = c2.button("⚡ Νέα μόνο",          use_container_width=True)
        r_full = c3.button("🔍 Βαθιά (2 χρόνια)", use_container_width=True)

        if r_test and spw:
            with st.spinner("OCR σε 4 email..."):
                recs, errs, n = fetch_sales_emails(spw, want_records=4, email_scan_limit=20)
            if errs:
                st.markdown(f'<div class="err-box">❌ {errs[0]}</div>', unsafe_allow_html=True)
            elif recs:
                st.markdown(f'<div class="info-box">✅ {len(recs)} εγγραφές από {n} email.</div>', unsafe_allow_html=True)
                td = pd.DataFrame(recs).drop_duplicates("date").sort_values("date", ascending=False)
                td["date"] = pd.to_datetime(td["date"]).dt.strftime("%d/%m/%Y")
                st.dataframe(td.rename(columns={"date":"ΗΜΕΡΟΜΗΝΙΑ","net_sales":"ΠΩΛΗΣΕΙΣ","customers":"ΠΕΛΑΤΕΣ","avg_basket":"ΜΟ ΚΑΛΑΘΙΟΥ"}), use_container_width=True, hide_index=True)
                saved = merge_sales(recs)
                st.markdown(f'<div class="info-box">💾 {saved} νέες εγγραφές στο Google Sheets.</div>', unsafe_allow_html=True)
                load_sales.clear()
            else:
                st.markdown(f'<div class="warn-box">⚠️ Ελέγχθηκαν {n} email — δεν βρέθηκαν δεδομένα.</div>', unsafe_allow_html=True)

        elif r_inc and spw:
            with st.spinner("Ανάγνωση νέων..."):
                ex = load_sales()
                since = (max(ex["date"]) - timedelta(days=3)) if not ex.empty else None
                recs, errs, n = fetch_sales_emails(spw, since=since, want_records=60, email_scan_limit=200)
            if errs:
                st.markdown(f'<div class="err-box">❌ {errs[0]}</div>', unsafe_allow_html=True)
            else:
                saved = merge_sales(recs)
                if saved > 0:
                    st.markdown(f'<div class="info-box">✅ {saved} νέες εγγραφές από {n} email.</div>', unsafe_allow_html=True)
                    load_sales.clear(); st.rerun()
                else:
                    st.markdown(f'<div class="info-box">✅ Ελέγχθηκαν {n} email — χωρίς νέα δεδομένα.</div>', unsafe_allow_html=True)

        elif r_full and spw:
            st.markdown('<div class="warn-box">⏳ Βαθιά Σάρωση. Μην κλείσετε τη σελίδα.</div>', unsafe_allow_html=True)
            pb = st.progress(0)
            ib = st.empty()
            for s in deep_scan_sales(spw):
                if s["err"]:
                    ib.error(f"Σφάλμα: {s['err']}"); break
                if s["phase"] == "connect":
                    ib.markdown('<div class="prog-wrap"><div class="prog-title">Σύνδεση...</div></div>', unsafe_allow_html=True)
                elif s["phase"] == "listing":
                    ib.markdown('<div class="prog-wrap"><div class="prog-title">Ανάκτηση emails...</div></div>', unsafe_allow_html=True)
                elif s["phase"] == "ocr":
                    t = s["total"]; d = s["done"]
                    pct = int(d/t*100) if t else 0
                    pb.progress(pct)
                    ib.markdown(f'<div class="prog-wrap"><div class="prog-title">OCR: {d}/{t} ({pct}%)</div><div class="prog-sub">💾 {s["saved"]} αποθηκεύτηκαν — {s["cur"]}</div></div>', unsafe_allow_html=True)
                if s["ok"]:
                    pb.progress(100)
                    st.markdown(f'<div class="info-box">✅ {s["total"]} emails → {s["saved"]} εγγραφές.</div>', unsafe_allow_html=True)
                    load_sales.clear(); break

        elif (r_test or r_inc or r_full) and not spw:
            st.markdown('<div class="err-box">❌ Εισάγετε App Password.</div>', unsafe_allow_html=True)

        if not df_s.empty:
            st.markdown('<div class="sh">Στατιστικά Google Sheets</div>', unsafe_allow_html=True)
            oldest = min(df_s["date"]).strftime("%d/%m/%Y")
            newest = max(df_s["date"]).strftime("%d/%m/%Y")
            st.markdown(f"""<div class="kr kr3">
              <div class="kc" style="--a:#10b981"><div class="kl">Εγγραφές</div><div class="kv">{len(df_s)}</div></div>
              <div class="kc" style="--a:#6b8fd4"><div class="kl">Από</div><div class="kv" style="font-size:.85rem;">{oldest}</div></div>
              <div class="kc" style="--a:#6b8fd4"><div class="kl">Έως</div><div class="kv" style="font-size:.85rem;">{newest}</div></div>
            </div>""", unsafe_allow_html=True)
