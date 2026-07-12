"""
app.py — ΤΕΣΤ Α: Επισκόπηση ΜΕ δεδομένα, ΧΩΡΙΣ το βαρύ CSS/rail
Αν ΑΥΤΟ δουλεύει → φταίει το CSS/HTML.
Αν σκάει → φταίνε τα δεδομένα/gsheets.
"""
import streamlit as st
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="ΑΒ Σκύρος — Τεστ Α", layout="wide")


def _mem():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return 0.0


st.title("🅰️ ΤΕΣΤ Α — Δεδομένα χωρίς CSS")
st.caption(f"Μνήμη στην εκκίνηση: {_mem():.0f} MB")

from gsheets_helper import load_sales, load_invoices, load_timologiseis

today = date.today()


def fmt(v, suffix=" €"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".") + suffix


st.write("**Φορτώνω πωλήσεις...**")
df_s = load_sales()
st.success(f"✅ Πωλήσεις: {len(df_s)} γραμμές · Μνήμη: {_mem():.0f} MB")

st.write("**Φορτώνω παραστατικά...**")
df_i = load_invoices()
st.success(f"✅ Παραστατικά: {len(df_i)} γραμμές · Μνήμη: {_mem():.0f} MB")

st.write("**Φορτώνω τιμολογήσεις...**")
df_t = load_timologiseis()
st.success(f"✅ Τιμολογήσεις: {len(df_t)} γραμμές · Μνήμη: {_mem():.0f} MB")

# ── Οι ΙΔΙΟΙ υπολογισμοί με την Επισκόπηση, αλλά με απλά widgets ──
st.divider()
st.subheader("Επισκόπηση (απλή μορφή)")


def get_week_range(d):
    s = d - timedelta(days=d.weekday())
    return s, s + timedelta(days=6)


sw, ew = get_week_range(today)
ly_same = today - timedelta(days=364)

_sdates = df_s["date"].apply(lambda x: x.date() if hasattr(x, "date") else x)


def _day_sales(d):
    m = df_s[_sdates == d]
    return float(m["net_sales"].sum()) if not m.empty else None


c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Σήμερα", fmt(_day_sales(today)))
with c2:
    st.metric("Πέρσι σαν σήμερα", fmt(_day_sales(ly_same)))
with c3:
    _wtd = df_s[(_sdates >= sw) & (_sdates <= today)]["net_sales"].sum()
    st.metric("Εβδομάδα ως τώρα", fmt(float(_wtd)))

st.caption(f"Μνήμη μετά τους υπολογισμούς: {_mem():.0f} MB")

# ── Παραστατικά εβδομάδας ──
st.divider()
st.subheader("Παραστατικά εβδομάδας")
mask = (df_i["date"] >= pd.Timestamp(sw)) & (df_i["date"] <= pd.Timestamp(ew) + pd.Timedelta(hours=23))
wi = df_i.loc[mask]
if "is_credit" in wi.columns:
    _inv = wi.loc[~wi["is_credit"], "value"].sum()
    _crd = wi.loc[wi["is_credit"], "value"].sum()
else:
    _inv = _crd = 0.0
c1, c2 = st.columns(2)
c1.metric("Τιμολόγια", fmt(float(_inv)))
c2.metric("Πιστωτικά", fmt(float(_crd)))

st.caption(f"Μνήμη μετά τα παραστατικά: {_mem():.0f} MB")

# ── Γράφημα (όπως στην Επισκόπηση) ──
st.divider()
st.subheader("Γράφημα εβδομάδων")
_dfc = df_s.copy()
_dfc["d"] = _dfc["date"].apply(lambda x: x.date() if hasattr(x, "date") else x)
_dfc["isoyear"] = _dfc["d"].apply(lambda d: d.isocalendar()[0])
_dfc["isoweek"] = _dfc["d"].apply(lambda d: d.isocalendar()[1])
_cy, _cw = today.isocalendar()[0], today.isocalendar()[1]
_g_cur = _dfc[_dfc["isoyear"] == _cy].groupby("isoweek")["net_sales"].sum()
_g_prev = _dfc[_dfc["isoyear"] == _cy - 1].groupby("isoweek")["net_sales"].sum()
_weeks = list(range(1, _cw + 1))
_chart = pd.DataFrame(index=_weeks)
_chart["Φέτος"] = [(_g_cur.get(w) if w in _g_cur.index else None) for w in _weeks]
_chart["Πέρσι"] = [(_g_prev.get(w) if w in _g_prev.index else None) for w in _weeks]
st.line_chart(_chart, height=260)

st.caption(f"Μνήμη μετά το γράφημα: {_mem():.0f} MB")

st.balloons()
st.header(f"🎉 ΤΕΣΤ Α ΠΕΡΑΣΕ — Τελική μνήμη: {_mem():.0f} MB")
st.info("Αν βλέπεις αυτό ΚΑΙ η σελίδα ΔΕΝ πέφτει μετά από 30 δευτερόλεπτα → "
        "τα δεδομένα είναι ΕΝΤΑΞΕΙ και φταίει το CSS/HTML/rail.")
