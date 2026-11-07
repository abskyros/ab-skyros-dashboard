"""
views/forecast.py — Πρόβλεψη ρευστότητας (δική της σελίδα).

Ήταν μέσα στη σελίδα «Μήνας»· τώρα είναι ξεχωριστή κύρια καρτέλα.

Δείχνει: το διαθέσιμο ταμείο, τα πάγια έξοδα (επεξεργάσιμα), και την πρόβλεψη
ρευστότητας από σήμερα για 1/2/3/12 μήνες — με πραγματικές επιταγές όπου
υπάρχουν, περσινές για πρόβλεψη όπου λείπουν.

Οι βοηθητικές συναρτήσεις (ταμείο, πάγια, εμφάνιση) ζουν στο month.py και τις
επαναχρησιμοποιούμε εδώ — μία πηγή αλήθειας, χωρίς διπλό κώδικα.
"""

from __future__ import annotations

import calendar
from datetime import date

import pandas as pd
import streamlit as st

from core.metrics import cash_forecast
from core.sheets import load_agores, load_setting, save_setting
from ui import components as c

# Πόσο μπροστά δείχνει η πρόβλεψη. Μετράει ΑΠΟ ΣΗΜΕΡΑ και περνάει κανονικά
# στη νέα χρονιά (παλιά σταματούσε καρφωτά στις 31/12).
HORIZONS = {"1 μήνας": 1, "2 μήνες": 2, "3 μήνες": 3, "12 μήνες": 12}
DEFAULT_HORIZON = "3 μήνες"
HORIZON_SETTING = "forecast_horizon"


def _add_months(d: date, k: int) -> date:
    """d + k μήνες (31/01 + 1 → 28/02)."""
    y, m = divmod(d.month - 1 + k, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _horizon(today: date) -> date:
    """Η επιλογή «1/2/3/12 μήνες» → ως ποια μέρα. Θυμάται την τελευταία."""
    saved = load_setting(HORIZON_SETTING, DEFAULT_HORIZON)
    if saved not in HORIZONS:
        saved = DEFAULT_HORIZON
    picked = st.segmented_control(
        "Πόσο μπροστά", list(HORIZONS), default=saved, key="forecast_horizon",
    ) or saved
    if picked != saved:
        save_setting(HORIZON_SETTING, picked)
    until = _add_months(today, HORIZONS[picked])
    st.caption(f"Από σήμερα ως **{until:%d/%m/%Y}**.")
    return until

# Επαναχρήση των εργαλείων της σελίδας «Μήνας».
from views.month import _cash_input, _fixed_expenses_input, _forecast_display


def render(df_t: pd.DataFrame, df_s: pd.DataFrame, today: date) -> None:
    if df_t.empty:
        c.empty(
            "Δεν υπάρχουν τιμολογήσεις ακόμη",
            "Η πρόβλεψη χρειάζεται επιταγές για να δουλέψει."
        )
        return

    c.html(
        '<div class="page-note">Πρόβλεψη ρευστότητας — από σήμερα και μπροστά, '
        'με βάση τις περσινές πωλήσεις και επιταγές.</div>'
    )

    # Ταμείο + πάγια έξοδα (τα ίδια εργαλεία με τη σελίδα Μήνας).
    cash = _cash_input(key="forecast")
    fixed = _fixed_expenses_input()

    # Η πρόβλεψη, ως το διάστημα που διάλεξες.
    until = _horizon(today)
    forecast = cash_forecast(df_t, df_s, today, cash, fixed=fixed, until=until,
                             df_agores=load_agores())
    _forecast_display(forecast)
