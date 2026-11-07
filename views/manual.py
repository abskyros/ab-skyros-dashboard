"""
views/manual.py — Χειροκίνητη καταχώρηση (μέσα στο «Ενημέρωση» της κεφαλίδας).

Για όταν το αυτόματο δεν έπιασε κάτι, ή το έπιασε λάθος:

  • Πωλήσεις     — προσθήκη / διόρθωση ημέρας
  • Παραστατικά  — προσθήκη / διαγραφή (με τον αριθμό)
  • Τιμολογήσεις — προσθήκη / διόρθωση επιταγής

Όλα γράφονται στο ίδιο Sheet με τον ίδιο τρόπο που γράφει και το αυτόματο
(core/sheets.py), άρα ισχύουν οι ίδιοι κανόνες διπλότυπων:
  πωλήσεις → η μέρα · παραστατικά → ο αριθμός · τιμολογήσεις → μέρα + περίοδος.

ΣΗΜΕΙΩΣΗ: καλείται μέσα σε popover, ΔΙΠΛΑ (όχι μέσα) σε άλλο expander — το
Streamlit δεν επιτρέπει expander μέσα σε expander.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.metrics import purchase_period, sales_row
from core.sheets import (
    merge_sales, update_sales,
    merge_invoices, delete_invoice_by_number,
    merge_timologiseis, update_timologisi,
)
from ui import components as c


def render(df_s: pd.DataFrame, df_i: pd.DataFrame, df_t: pd.DataFrame, today: date) -> None:
    with st.expander("✏️ Χειροκίνητη καταχώρηση"):
        st.caption(
            "Για ό,τι δεν έπιασε (ή έπιασε λάθος) το αυτόματο. Γράφεται στο ίδιο "
            "Sheet — ό,τι υπάρχει ήδη δεν μπαίνει δεύτερη φορά."
        )
        s, i, t = st.tabs(["Πωλήσεις", "Παραστατικά", "Τιμολογήσεις"])
        with s:
            _sales(df_s, today)
        with i:
            _invoices(df_i, today)
        with t:
            _timologiseis(df_t, today)


# ══════════════════════════════════════════════════════════════════════════════
# ΠΩΛΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
def _sales(df: pd.DataFrame, today: date) -> None:
    mode = st.radio("Τι θέλεις;", ["Προσθήκη ημέρας", "Διόρθωση ημέρας"],
                    horizontal=True, key="m_s_mode", label_visibility="collapsed")

    picked = st.date_input("Ημέρα", today - timedelta(days=1),
                           key="m_s_day", format="DD/MM/YYYY")
    current = sales_row(df, picked)

    if mode == "Προσθήκη ημέρας":
        if current:
            c.note(f"Η {picked:%d/%m/%Y} υπάρχει ήδη "
                   f"({c.eur(current['net_sales'])}). Διάλεξε «Διόρθωση ημέρας».", "warn")
            return
        a, b, d = st.columns(3)
        with a:
            net = st.number_input("Πωλήσεις (€)", min_value=0.0, step=100.0,
                                  format="%.2f", key="m_s_net")
        with b:
            cust = st.number_input("Πελάτες", min_value=0, step=1, key="m_s_cust")
        with d:
            auto = (net / cust) if (net and cust) else 0.0
            basket = st.number_input("Μέσο καλάθι (€)", min_value=0.0, value=round(auto, 2),
                                     step=0.5, format="%.2f", key="m_s_basket")
        if st.button("Καταχώρηση", key="m_s_add", width="stretch", disabled=not net):
            n = merge_sales([{"date": picked, "net_sales": net,
                              "customers": cust or None, "avg_basket": basket or None}])
            if n:
                c.note(f"Η {picked:%d/%m/%Y} καταχωρήθηκε.", "ok")
            else:
                c.note("Δεν καταχωρήθηκε — η ημέρα υπάρχει ήδη.", "warn")
        return

    # Διόρθωση
    if not current:
        c.note(f"Η {picked:%d/%m/%Y} δεν υπάρχει. Διάλεξε «Προσθήκη ημέρας».", "warn")
        return
    # Το key περιέχει τη μέρα: αλλάζεις μέρα → τα πεδία γεμίζουν με τα δικά της.
    k = f"{picked:%Y%m%d}"
    a, b, d = st.columns(3)
    with a:
        net = st.number_input("Πωλήσεις (€)", value=float(current["net_sales"]),
                              step=100.0, format="%.2f", key=f"m_s_fnet_{k}")
    with b:
        cust = st.number_input("Πελάτες", value=int(current["customers"] or 0),
                               step=1, key=f"m_s_fcust_{k}")
    with d:
        basket = st.number_input("Μέσο καλάθι (€)", value=float(current["avg_basket"] or 0),
                                 step=0.5, format="%.2f", key=f"m_s_fbasket_{k}")
    if st.button("Αποθήκευση", key="m_s_fix", width="stretch"):
        ok, msg = update_sales(picked, net, cust or None, basket or None)
        c.note(msg, "ok" if ok else "bad")


# ══════════════════════════════════════════════════════════════════════════════
# ΠΑΡΑΣΤΑΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
_DEFAULT_TYPES = ["ΤΙΜΟΛΟΓΙΟ (ΠΩΛΗΣΗ ΑΓΑΘΩΝ)", "ΠΙΣΤΩΤΙΚΟ"]


def _invoice_types(df: pd.DataFrame) -> list[str]:
    """Τα είδη όπως είναι ήδη γραμμένα στο Sheet (πιο συχνό πρώτο)."""
    if df.empty or "type" not in df:
        return _DEFAULT_TYPES
    counts = df["type"].astype(str).str.strip().value_counts()
    types = [t for t in counts.index if t]
    return types or _DEFAULT_TYPES


def _invoices(df: pd.DataFrame, today: date) -> None:
    mode = st.radio("Τι θέλεις;", ["Προσθήκη", "Διαγραφή"],
                    horizontal=True, key="m_i_mode", label_visibility="collapsed")

    if mode == "Προσθήκη":
        a, b = st.columns(2)
        with a:
            d = st.date_input("Ημερομηνία", today, key="m_i_day", format="DD/MM/YYYY")
        with b:
            typ = st.selectbox("Είδος", _invoice_types(df), key="m_i_type")
        a, b = st.columns(2)
        with a:
            num = st.text_input("Αριθμός παραστατικού", key="m_i_num").strip()
        with b:
            val = st.number_input("Ποσό (€)", min_value=0.0, step=10.0,
                                  format="%.2f", key="m_i_val",
                                  help="Θετικό ποσό — το είδος (πιστωτικό) το αφαιρεί μόνο του.")
        if num and not df.empty and (df["number"].astype(str).str.strip() == num).any():
            c.note(f"Ο αριθμός {num} υπάρχει ήδη — δεν θα μπει δεύτερη φορά.", "warn")
        if st.button("Καταχώρηση", key="m_i_add", width="stretch", disabled=not (num and val)):
            n = merge_invoices([{"date": d, "type": typ, "value": val, "number": num}])
            c.note(f"Το παραστατικό {num} καταχωρήθηκε." if n
                   else f"Δεν καταχωρήθηκε — ο αριθμός {num} υπάρχει ήδη.",
                   "ok" if n else "warn")
        return

    # Διαγραφή
    num = st.text_input("Αριθμός παραστατικού προς διαγραφή", key="m_i_del_num").strip()
    if not num:
        return
    hit = df[df["number"].astype(str).str.strip() == num] if not df.empty else df
    if hit.empty:
        c.note(f"Δεν βρέθηκε παραστατικό με αριθμό {num}.", "warn")
        return
    r = hit.iloc[0]
    c.note(f"{pd.Timestamp(r['date']):%d/%m/%Y} · {r['type']} · <b>{c.eur(float(r['value']))}</b>"
           f" · αρ. {num}", "info")
    if st.button("Διαγραφή αυτού του παραστατικού", key="m_i_del", width="stretch"):
        ok, msg = delete_invoice_by_number(num)
        c.note(msg, "ok" if ok else "bad")


# ══════════════════════════════════════════════════════════════════════════════
# ΤΙΜΟΛΟΓΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
def _period_text(cd: date) -> str:
    """Η περίοδος αγορών που πληρώνει η επιταγή, στη μορφή του Excel της ΑΒ."""
    a, b = purchase_period(cd)
    return f"{a:%d.%m.%Y} - {b:%d.%m.%Y}"


def _timologiseis(df: pd.DataFrame, today: date) -> None:
    mode = st.radio("Τι θέλεις;", ["Προσθήκη επιταγής", "Διόρθωση επιταγής"],
                    horizontal=True, key="m_t_mode", label_visibility="collapsed")

    if mode == "Προσθήκη επιταγής":
        a, b = st.columns(2)
        with a:
            cd = st.date_input("Ημερομηνία επιταγής", today, key="m_t_day", format="DD/MM/YYYY")
        with b:
            amt = st.number_input("Ποσό (€)", min_value=0.0, step=100.0,
                                  format="%.2f", key="m_t_amt")
        # Η περίοδος βγαίνει μόνη της από την ημερομηνία (εβδομάδα ή δεκαήμερο)·
        # το key περιέχει την ημερομηνία ώστε να ξαναγεμίζει όταν την αλλάζεις.
        period = st.text_input("Περίοδος αγορών", _period_text(cd),
                               key=f"m_t_period_{cd:%Y%m%d}",
                               help="Συμπληρώνεται μόνη της· άλλαξέ τη αν το Excel γράφει άλλη.")
        if st.button("Καταχώρηση", key="m_t_add", width="stretch", disabled=not amt):
            n = merge_timologiseis([{"check_date": cd, "period": period, "amount": amt}])
            c.note(f"Η επιταγή {cd:%d/%m/%Y} καταχωρήθηκε." if n
                   else f"Δεν καταχωρήθηκε — υπάρχει ήδη επιταγή {cd:%d/%m/%Y} με την ίδια περίοδο.",
                   "ok" if n else "warn")
        return

    # Διόρθωση
    if df.empty:
        c.note("Δεν υπάρχουν επιταγές ακόμη.", "info")
        return
    recent = df.sort_values("check_date", ascending=False).head(40)
    options = {
        int(r["_row"]): f"{pd.Timestamp(r['check_date']):%d/%m/%Y} · {r['period']} · {c.eur(float(r['amount']))}"
        for _, r in recent.iterrows()
    }
    row = st.selectbox("Επιταγή", list(options), format_func=options.get, key="m_t_pick")
    r = recent[recent["_row"] == row].iloc[0]
    old_cd = pd.Timestamp(r["check_date"]).date()

    k = str(row)
    a, b = st.columns(2)
    with a:
        cd = st.date_input("Ημερομηνία επιταγής", old_cd, key=f"m_t_fday_{k}", format="DD/MM/YYYY")
    with b:
        amt = st.number_input("Ποσό (€)", value=float(r["amount"]), step=100.0,
                              format="%.2f", key=f"m_t_famt_{k}")
    period = st.text_input("Περίοδος αγορών", str(r["period"]), key=f"m_t_fperiod_{k}")
    if st.button("Αποθήκευση", key="m_t_fix", width="stretch"):
        ok, msg = update_timologisi(row, f"{old_cd:%Y-%m-%d}", cd, period, amt)
        c.note(msg, "ok" if ok else "bad")

