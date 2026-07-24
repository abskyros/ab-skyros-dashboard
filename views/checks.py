"""
views/checks.py — «Επιταγές» (μόνο κινητό).

Η δεξαμενή σε δική της καρτέλα: πόσο φτάνει το ταμείο στις επόμενες επιταγές,
και η λίστα των επιταγών που έρχονται.

Στο desktop, η ίδια μπάρα ζει μέσα στη σελίδα «Μήνας» (δεξιά του πίνακα). Εδώ
είναι η αποκλειστικά-κινητή εκδοχή, χωρίς τον πίνακα εξόδων — καθαρή εικόνα
ταμείου με το ένα χέρι.
"""

from datetime import date

import pandas as pd
import streamlit as st

from core.metrics import cash_runway, upcoming_checks
from core.sheets import load_setting, save_setting
from ui import components as c

CASH_SETTING = "cash_on_hand"   # ίδιο κλειδί με τη σελίδα «Μήνας» — μοιράζονται το ταμείο


def render(df_t: pd.DataFrame, today: date) -> None:
    if df_t.empty:
        c.empty(
            "Δεν υπάρχουν τιμολογήσεις ακόμη",
            "Οι επιταγές έρχονται αυτόματα κάθε 2 ώρες."
        )
        return

    checks = upcoming_checks(df_t, today)
    if not checks:
        c.empty(
            "Καμία επιταγή μπροστά",
            "Ό,τι έληξε δεν μετράει εδώ. Μόλις μπει νέα επιταγή, θα φανεί."
        )
        return

    # ── ΤΑΜΕΙΟ (με μνήμη) ──
    c.section("Ταμείο")

    ss_key = "cash_checks"
    if ss_key not in st.session_state:
        saved = load_setting(CASH_SETTING, "0")
        try:
            st.session_state[ss_key] = float(saved)
        except (ValueError, TypeError):
            st.session_state[ss_key] = 0.0

    cash = st.number_input(
        "Διαθέσιμα μετρητά (€)",
        min_value=0.0,
        step=1000.0,
        format="%.0f",
        key=ss_key,
        help="Το ποσό που έχεις τώρα. Θυμάται την τελευταία τιμή που έβαλες.",
    )

    # Αποθήκευση μόνο σε αλλαγή
    last = st.session_state.get(f"{ss_key}_saved")
    if cash != last:
        save_setting(CASH_SETTING, str(int(cash)))
        st.session_state[f"{ss_key}_saved"] = cash

    # ── Η ΔΕΞΑΜΕΝΗ ──
    runway = cash_runway(df_t, today, cash)
    c.cash_runway_card(runway)
