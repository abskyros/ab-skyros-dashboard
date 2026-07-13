"""
views/overview.py — Η πρώτη οθόνη.

Απαντά σε τρία πράγματα, με αυτή τη σειρά:
  1. Πώς πήγε χθες σε σχέση με πέρσι;
  2. Πώς πάει η εβδομάδα ως τώρα;
  3. Τι πρέπει να πληρώσω και τι τιμολόγησα;

Το «πάντα τρέχουσα εβδομάδα» είναι σκόπιμο. Κάθε Δευτέρα μηδενίζει μόνο του —
δεν χρειάζεται να διαλέξεις τίποτα για να δεις τη δουλειά σου.
"""

from datetime import date, timedelta

import pandas as pd

from core.metrics import (
    week_range, last_year, day_name,
    sales_on, sales_row, week_to_date,
    invoice_totals, invoices_in_week,
    check_this_week, weekly_series,
)
from ui import components as c
from ui import charts


def render(df_s: pd.DataFrame, df_i: pd.DataFrame, df_t: pd.DataFrame, today: date) -> None:
    week_start, _ = week_range(today)

    c.title("Επισκόπηση", f"Τρέχουσα εβδομάδα · από {day_name(week_start)} {week_start:%d/%m}")

    if df_s.empty and df_i.empty and df_t.empty:
        c.empty(
            "Δεν έχουν φορτωθεί δεδομένα ακόμη",
            "Άνοιξε την «Ενημέρωση δεδομένων» στο κάτω μέρος για να τραβήξεις τα πρώτα email."
        )
        return

    _headline(df_s, today)
    _secondary(df_i, df_t, today, week_start)
    _trend(df_s, today)


# ══════════════════════════════════════════════════════════════════════════════
def _headline(df_s: pd.DataFrame, today: date) -> None:
    """
    Χθες και εβδομάδα-ως-τώρα.

    Δείχνουμε ΧΘΕΣ, όχι σήμερα: η αναφορά της ημέρας έρχεται το βράδυ, οπότε το
    «σήμερα» είναι σχεδόν πάντα άδειο μέχρι τις 21:00. Ένα μεγάλο μηδενικό στην
    κορυφή κάθε πρωί δεν βοηθάει κανέναν.
    """
    yesterday = today - timedelta(days=1)
    y_now = sales_on(df_s, yesterday)

    # Αν το χθεσινό δεν έχει έρθει ακόμη, γυρνάμε στην τελευταία μέρα με δεδομένα.
    if y_now is None and not df_s.empty:
        latest = df_s["date"].max()
        yesterday = latest.date() if hasattr(latest, "date") else latest
        y_now = sales_on(df_s, yesterday)

    y_ref = last_year(yesterday)
    y_then = sales_on(df_s, y_ref)

    wtd = week_to_date(df_s, today)

    c.grid(
        c.scale(
            f"{day_name(yesterday)} {yesterday:%d/%m}",
            y_now, y_then,
            foot=f"Πέρσι {day_name(y_ref)} {y_ref:%d/%m} — ίδια μέρα εβδομάδας",
            href=c.link("Πωλήσεις"),
        ),
        c.scale(
            f"Εβδομάδα ως τώρα · {wtd['label']}",
            wtd["current"], wtd["previous"],
            foot=f"{wtd['days_elapsed']} ημέρες vs οι ίδιες {wtd['days_elapsed']} πέρσι",
            href=c.link("Πωλήσεις"),
        ),
        cols=2,
    )


# ══════════════════════════════════════════════════════════════════════════════
def _secondary(df_i: pd.DataFrame, df_t: pd.DataFrame, today: date, week_start: date) -> None:
    """Τιμολόγια της εβδομάδας + η επιταγή που πέφτει τώρα."""
    inv_net = invoice_totals(invoices_in_week(df_i, today))["net"]

    check = check_this_week(df_t, today)

    if check is not None:
        cd = check["check_date"]
        cd = cd.date() if hasattr(cd, "date") else cd
        check_card = c.stat(
            "Επιταγή αυτή την εβδομάδα",
            float(check["amount"]),
            accent="var(--ink)",
            foot=f"Πληρωμή {cd:%d/%m/%Y}",
            href=c.link("Τιμολογήσεις"),
        )
    else:
        check_card = c.stat(
            "Επιταγή αυτή την εβδομάδα",
            None,
            accent="var(--prev)",
            foot="Καμία επιταγή δεν πέφτει αυτή την εβδομάδα",
            href=c.link("Τιμολογήσεις"),
        )

    c.grid(
        c.stat(
            "Τιμολόγια — καθαρό",
            inv_net,
            tone="pos" if inv_net >= 0 else "neg",
            accent="var(--brand)",
            foot="Τιμολόγια μείον πιστωτικά, τρέχουσα εβδομάδα",
            href=c.link("Παραστατικά"),
        ),
        check_card,
        cols=2,
    )


# ══════════════════════════════════════════════════════════════════════════════
def _trend(df_s: pd.DataFrame, today: date) -> None:
    """Η χρονιά σε μια ματιά — εβδομάδα προς εβδομάδα, φέτος vs πέρσι."""
    if df_s.empty:
        return

    year = today.isocalendar()[0]
    week = today.isocalendar()[1]

    g_now = weekly_series(df_s, year)
    g_then = weekly_series(df_s, year - 1)

    if g_now.empty:
        return

    weeks = list(range(1, week + 1))

    def series(g, col):
        return [float(g.loc[w, col]) if (not g.empty and w in g.index) else None for w in weeks]

    c.section("Πωλήσεις ανά εβδομάδα")
    charts.year_over_year(
        weeks,
        series(g_now, "net_sales"),
        series(g_then, "net_sales"),
        label_now=str(year),
        label_then=str(year - 1),
    )

    if g_now["customers"].notna().any():
        c.section("Πελάτες ανά εβδομάδα")
        charts.year_over_year(
            weeks,
            series(g_now, "customers"),
            series(g_then, "customers"),
            unit="",
            label_now=str(year),
            label_then=str(year - 1),
            height=230,
        )
