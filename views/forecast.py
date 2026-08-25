"""
views/forecast.py — Πρόβλεψη ρευστότητας (δική της σελίδα).

Ήταν μέσα στη σελίδα «Μήνας»· τώρα είναι ξεχωριστή κύρια καρτέλα.

Δείχνει: το διαθέσιμο ταμείο, τα πάγια έξοδα (επεξεργάσιμα), και την πρόβλεψη
ρευστότητας από σήμερα ως το τέλος του έτους — με πραγματικές επιταγές όπου
υπάρχουν, περσινές για πρόβλεψη όπου λείπουν.

Οι βοηθητικές συναρτήσεις (ταμείο, πάγια, εμφάνιση) ζουν στο month.py και τις
επαναχρησιμοποιούμε εδώ — μία πηγή αλήθειας, χωρίς διπλό κώδικα.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.metrics import cash_forecast
from ui import components as c

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
        '<div class="page-note">Πρόβλεψη ρευστότητας — από σήμερα ως το '
        'τέλος του έτους, με βάση τις περσινές πωλήσεις και επιταγές.</div>'
    )

    # Ταμείο + πάγια έξοδα (τα ίδια εργαλεία με τη σελίδα Μήνας).
    cash = _cash_input(key="forecast")
    fixed = _fixed_expenses_input()

    # Η πρόβλεψη.
    forecast = cash_forecast(df_t, df_s, today, cash, fixed=fixed)
    _forecast_display(forecast)
