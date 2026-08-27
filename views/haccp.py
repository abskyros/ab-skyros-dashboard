"""
views/haccp.py — Ποιοτικός Έλεγχος (HACCP).

Ψηφιακά αντίστοιχα των χάρτινων εντύπων του εγχειριδίου «Κανόνες Υγιεινής» ΑΒ:

  • Καθαριότητα  → Έντυπο Ε1 (Πλάνο Καθαρισμού-Απολύμανσης), ανά τμήμα.
  • Θερμοκρασίες → Έντυπο Ε3 (ψυχόμενοι χώροι), απλή ημερήσια καταγραφή.
  • Παραλαβή     → Έντυπο Ε5, οι 5 έλεγχοι ποιότητας ανά παραλαβή.

Κάθε καταχώρηση είναι ΜΟΝΙΜΗ γραμμή σε log — δεν διορθώνεται, δεν σβήνεται.
Το ιστορικό είναι η ίδια η απόδειξη συμμόρφωσης.
"""

from datetime import date

import pandas as pd
import streamlit as st

from core.haccp import DEPARTMENTS
from core.sheets import (
    load_haccp_cleaning, log_cleaning_done,
    load_haccp_temperature, log_temperature,
    load_haccp_receiving, log_receiving,
    current_suppliers,
)
from ui import components as c


def render(today: date) -> None:
    tab_clean, tab_temp, tab_recv = st.tabs(["🧹 Καθαριότητα", "🌡️ Θερμοκρασίες", "📥 Παραλαβή"])

    with tab_clean:
        _cleaning(today)
    with tab_temp:
        _temperature(today)
    with tab_recv:
        _receiving(today)


# ══════════════════════════════════════════════════════════════════════════════
# ΚΑΘΑΡΙΟΤΗΤΑ — Έντυπο Ε1
# ══════════════════════════════════════════════════════════════════════════════
def _cleaning(today: date) -> None:
    date_str = today.strftime("%Y-%m-%d")

    c.section("Καθαριότητα σήμερα")
    department = st.selectbox("Τμήμα", list(DEPARTMENTS.keys()), key="haccp_dept")
    done_by = st.text_input("Ποιος κάνει τον έλεγχο", key="haccp_clean_by")

    items = DEPARTMENTS[department]
    log = load_haccp_cleaning()
    done_today = set()
    if not log.empty:
        today_dept = log[(log["date"] == date_str) & (log["department"] == department)]
        done_today = set(today_dept["item"])

    st.caption(f"{len(done_today)}/{len(items)} ολοκληρώθηκαν σήμερα σε αυτό το τμήμα.")

    for item in items:
        checked = item in done_today
        new_val = st.checkbox(item, value=checked, key=f"haccp_{department}_{item}")
        if new_val and not checked:
            if log_cleaning_done(date_str, department, item, done_by.strip()):
                st.rerun()

    if len(done_today) == len(items):
        c.note("Όλα τα σημεία αυτού του τμήματος καθαρίστηκαν σήμερα.", "ok")


# ══════════════════════════════════════════════════════════════════════════════
# ΘΕΡΜΟΚΡΑΣΙΕΣ — Έντυπο Ε3
# ══════════════════════════════════════════════════════════════════════════════
def _temperature(today: date) -> None:
    date_str = today.strftime("%Y-%m-%d")

    c.section("Καταγραφή θερμοκρασίας")

    with st.form("haccp_temp_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            unit = st.text_input("Ψυχόμενος χώρος", placeholder="π.χ. Ψυγείο κατάψυξης 1")
        with col2:
            reading = st.number_input("Μέτρηση (°C)", step=0.5, format="%.1f")

        status = st.radio("Κατάσταση", ["ΟΚ", "ΕΚΤΟΣ ΟΡΙΩΝ"], horizontal=True)
        notes = st.text_input("Σημειώσεις", key="haccp_temp_notes")

        submitted = st.form_submit_button("Καταχώρηση", type="primary")

    if submitted:
        if not unit.strip():
            c.note("Χρειάζεται όνομα ψυχόμενου χώρου.", "bad")
        else:
            ok = log_temperature({
                "date": date_str,
                "time": pd.Timestamp.now().strftime("%H:%M"),
                "unit": unit.strip(),
                "reading": reading,
                "status": status,
                "notes": notes.strip(),
            })
            if ok:
                c.note(f"Καταχωρήθηκε: {unit} → {reading}°C ({status})", "ok")
                st.rerun()

    log = load_haccp_temperature()
    today_log = log[log["date"] == date_str] if not log.empty else log

    c.spacer(0.8)
    c.section("Μετρήσεις σήμερα")
    if today_log.empty:
        c.empty("Καμία μέτρηση ακόμη σήμερα")
    else:
        bad = today_log[today_log["status"] != "ΟΚ"]
        if not bad.empty:
            c.note(f"⚠️ {len(bad)} μέτρηση(εις) εκτός ορίων σήμερα.", "warn")
        st.dataframe(
            today_log[["time", "unit", "reading", "status", "notes"]].rename(columns={
                "time": "Ώρα", "unit": "Χώρος", "reading": "°C",
                "status": "Κατάσταση", "notes": "Σημειώσεις",
            }),
            hide_index=True, width="stretch",
        )


# ══════════════════════════════════════════════════════════════════════════════
# ΠΑΡΑΛΑΒΗ — Έντυπο Ε5
# ══════════════════════════════════════════════════════════════════════════════
def _receiving(today: date) -> None:
    date_str = today.strftime("%Y-%m-%d")

    c.section("Καταχώρηση παραλαβής")

    suppliers = current_suppliers()
    supplier_names = sorted(suppliers["supplier"].unique()) if not suppliers.empty else []

    with st.form("haccp_receiving_form", clear_on_submit=True):
        supplier = st.selectbox("Προμηθευτής / αποστολέας", ["— άλλο —"] + supplier_names)
        if supplier == "— άλλο —":
            supplier = st.text_input("Όνομα προμηθευτή")
        product = st.text_input("Προϊόν (που ελέγχεται)")

        st.caption("Έλεγχοι ποιότητας — Πίνακας 7.1/7.2 του εγχειριδίου υγιεινής")
        c1, c2, c3 = st.columns(3)
        with c1:
            temp_ok = st.radio("Θερμοκρασία προϊόντος", ["ΑΠΟΔΕΚΤΟ", "ΜΗ ΑΠΟΔΕΚΤΟ"], key="r_temp")
            vehicle_ok = st.radio("Όχημα & φόρτωση", ["ΑΠΟΔΕΚΤΟ", "ΜΗ ΑΠΟΔΕΚΤΟ"], key="r_veh")
        with c2:
            expiry_ok = st.radio("Ημ/νία λήξης", ["ΑΠΟΔΕΚΤΟ", "ΜΗ ΑΠΟΔΕΚΤΟ"], key="r_exp")
            packaging_ok = st.radio("Συσκευασία", ["ΑΠΟΔΕΚΤΟ", "ΜΗ ΑΠΟΔΕΚΤΟ"], key="r_pack")
        with c3:
            organoleptic_ok = st.radio("Οργανοληπτικά", ["ΑΠΟΔΕΚΤΟ", "ΜΗ ΑΠΟΔΕΚΤΟ"], key="r_org")

        corrective_action = st.text_input("Διορθωτική ενέργεια (αν χρειάστηκε)")
        received_by = st.text_input("Υπεύθυνος παραλαβής")

        submitted = st.form_submit_button("Καταχώρηση", type="primary")

    if submitted:
        if not supplier.strip() or not product.strip():
            c.note("Χρειάζεται προμηθευτής και προϊόν.", "bad")
        else:
            ok = log_receiving({
                "date": date_str, "supplier": supplier.strip(), "product": product.strip(),
                "temp_ok": temp_ok, "vehicle_ok": vehicle_ok, "expiry_ok": expiry_ok,
                "packaging_ok": packaging_ok, "organoleptic_ok": organoleptic_ok,
                "corrective_action": corrective_action.strip(), "received_by": received_by.strip(),
            })
            if ok:
                rejected = "ΜΗ ΑΠΟΔΕΚΤΟ" in (temp_ok, vehicle_ok, expiry_ok, packaging_ok, organoleptic_ok)
                c.note(
                    "⚠️ Καταχωρήθηκε ΜΕ ΑΠΟΡΡΙΨΗ — βεβαιώσου ότι σημειώθηκε διορθωτική ενέργεια." if rejected
                    else "Καταχωρήθηκε η παραλαβή.",
                    "warn" if rejected else "ok",
                )
                st.rerun()

    log = load_haccp_receiving()
    today_log = log[log["date"] == date_str] if not log.empty else log

    c.spacer(0.8)
    c.section("Παραλαβές σήμερα")
    if today_log.empty:
        c.empty("Καμία παραλαβή καταχωρημένη ακόμη σήμερα")
        return

    checks = ["temp_ok", "vehicle_ok", "expiry_ok", "packaging_ok", "organoleptic_ok"]
    rejected_mask = (today_log[checks] == "ΜΗ ΑΠΟΔΕΚΤΟ").any(axis=1)
    if rejected_mask.any():
        c.note(f"⚠️ {int(rejected_mask.sum())} παραλαβή(ές) σήμερα με απόρριψη σε κάποιον έλεγχο.", "warn")

    st.dataframe(
        today_log[["supplier", "product"] + checks + ["corrective_action", "received_by"]].rename(columns={
            "supplier": "Προμηθευτής", "product": "Προϊόν",
            "temp_ok": "Θερμ/σία", "vehicle_ok": "Όχημα", "expiry_ok": "Ημ. λήξης",
            "packaging_ok": "Συσκ/σία", "organoleptic_ok": "Οργανοληπτικά",
            "corrective_action": "Διορθωτική ενέργεια", "received_by": "Υπεύθυνος",
        }),
        hide_index=True, width="stretch",
    )
