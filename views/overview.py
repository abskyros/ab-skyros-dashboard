"""
views/overview.py — Η πρώτη οθόνη.

Τέσσερις κάρτες, δύο ερωτήσεις:

  ┌─────────────────────┬─────────────────────┐
  │  ΣΗΜΕΡΑ             │  ΧΘΕΣ               │   Πού πάω;  Πού έφτασα;
  │  ο στόχος           │  το αποτέλεσμα      │
  ├─────────────────────┼─────────────────────┤
  │  ΕΒΔΟΜΑΔΑ ΩΣ ΤΩΡΑ   │  ΕΠΙΤΑΓΗ            │   Πώς πάει;  Τι χρωστάω;
  └─────────────────────┴─────────────────────┘

ΓΙΑΤΙ ΔΥΟ ΚΑΡΤΕΣ ΓΙΑ ΤΙΣ ΠΩΛΗΣΕΙΣ:

Η αναφορά της ημέρας έρχεται με email το βράδυ. Άρα το «σήμερα» είναι 0 μέχρι
τις 21:00 — αλλά αυτό ΔΕΝ σημαίνει ότι είναι άχρηστο. Το περσινό νούμερο της
ίδιας μέρας είναι ο στόχος σου: «σήμερα πρέπει να πιάσω 21.000».

Και το «χθες» δίνει το τελευταίο πραγματικό αποτέλεσμα, με τη σύγκριση.

Στόχος και αποτέλεσμα. Δύο διαφορετικές ερωτήσεις, δύο κάρτες.

Η εβδομάδα είναι ΠΑΝΤΑ η τρέχουσα. Κάθε Δευτέρα μηδενίζει μόνη της — δεν
χρειάζεται να διαλέξεις τίποτα για να δεις τη δουλειά σου.
"""

from datetime import date, timedelta

import pandas as pd

from core.metrics import (
    week_range, last_year, day_name,
    sales_on, sales_row, week_to_date,
    invoice_totals, invoices_in_week,
    check_this_week,
)
from ui import components as c


def render(df_s: pd.DataFrame, df_i: pd.DataFrame, df_t: pd.DataFrame, today: date) -> None:
    week_start, _ = week_range(today)

    c.title("Επισκόπηση", f"Τρέχουσα εβδομάδα · από {day_name(week_start)} {week_start:%d/%m}")

    if df_s.empty and df_i.empty and df_t.empty:
        c.empty(
            "Δεν έχουν φορτωθεί δεδομένα ακόμη",
            "Άνοιξε την «Ενημέρωση δεδομένων» στο κάτω μέρος για να τραβήξεις τα πρώτα email."
        )
        return

    _sales(df_s, today)
    _week_and_check(df_s, df_i, df_t, today)


# ══════════════════════════════════════════════════════════════════════════════
def _sales(df_s: pd.DataFrame, today: date) -> None:
    """Σήμερα (στόχος) και χθες (αποτέλεσμα)."""

    # ── ΣΗΜΕΡΑ ──
    # Συνήθως None μέχρι το βράδυ. Ο στόχος είναι το περσινό της ίδιας μέρας.
    today_now = sales_on(df_s, today)
    today_ref = last_year(today)
    today_goal = sales_on(df_s, today_ref)

    # ── ΧΘΕΣ ──
    yesterday = today - timedelta(days=1)
    y_now = sales_on(df_s, yesterday)

    # Αν το χθεσινό δεν ήρθε ακόμη, πάμε στην τελευταία μέρα που έχουμε.
    # Έτσι η κάρτα δείχνει πάντα ένα πραγματικό νούμερο, όχι κενό.
    stale = False
    if y_now is None and not df_s.empty:
        latest = df_s["date"].max()
        latest = latest.date() if hasattr(latest, "date") else latest
        if latest < yesterday:
            yesterday = latest
            y_now = sales_on(df_s, yesterday)
            stale = True

    y_ref = last_year(yesterday)
    y_then = sales_on(df_s, y_ref)

    y_foot = f"Πέρσι {day_name(y_ref, short=True)} {y_ref:%d/%m}"
    if stale:
        y_foot = f"Τελευταία καταχώρηση · {y_foot}"

    # ── ΤΟ ΥΠΟΣΗΜΕΙΩΜΑ ΤΟΥ «ΣΗΜΕΡΑ» ──
    #
    # Αν οι πωλήσεις δεν ήρθαν ακόμη, ο χρήστης πρέπει να ξέρει ΓΙΑΤΙ.
    # «Σε εξέλιξη» στις 23:30 είναι ανησυχητικό — μήπως χάλασε κάτι;
    #
    # Λέμε πότε έρχονται και πότε ελέγχουμε. Χωρίς αυτό, ο χρήστης κοιτάει μια
    # άδεια κάρτα και δεν ξέρει αν φταίει το σύστημα ή απλώς δεν ήρθε το email.
    if today_now is not None:
        today_foot = f"Στόχος: {day_name(today_ref, short=True)} {today_ref:%d/%m} πέρσι"
    elif today_goal:
        today_foot = (
            f"Στόχος: {day_name(today_ref, short=True)} {today_ref:%d/%m} πέρσι · "
            f"Η αναφορά έρχεται το βράδυ"
        )
    else:
        today_foot = "Δεν υπάρχει περσινό για αυτή τη μέρα"

    c.grid(
        c.target(
            f"Σήμερα · {day_name(today)} {today:%d/%m}",
            today_now,
            today_goal,
            foot=today_foot,
            href=c.link("Πωλήσεις"),
        ),
        c.scale(
            f"Χθες · {day_name(yesterday)} {yesterday:%d/%m}",
            y_now, y_then,
            foot=y_foot,
            href=c.link("Πωλήσεις"),
        ),
        cols=2,
    )

    _freshness(df_s, today)


def _freshness(df_s: pd.DataFrame, today: date) -> None:
    """
    ΠΟΣΟ ΦΡΕΣΚΑ ΕΙΝΑΙ ΤΑ ΔΕΔΟΜΕΝΑ;

    Μια άδεια κάρτα στις 23:30 δεν λέει τίποτα. Είναι φυσιολογικό ή χάλασε κάτι;

    Αυτή η γραμμή απαντάει:
      • Ποια είναι η τελευταία μέρα που έχουμε
      • Πόσο πίσω είμαστε
      • Τι να κάνεις αν κάτι δεν πάει καλά
    """
    if df_s.empty:
        return

    latest = df_s["date"].max()
    latest = latest.date() if hasattr(latest, "date") else latest

    gap = (today - latest).days

    if gap <= 1:
        # Φυσιολογικό: η σημερινή αναφορά έρχεται το βράδυ.
        return

    if gap == 2:
        c.note(
            f"Η τελευταία καταχωρημένη μέρα είναι η <b>{latest:%d/%m}</b>. "
            f"Η χθεσινή αναφορά δεν έχει έρθει ακόμη — αν είναι μετά τις 21:00, "
            f"δοκίμασε την <b>Ενημέρωση δεδομένων</b> στο κάτω μέρος.",
            "warn",
        )
        return

    c.note(
        f"⚠️ <b>Οι πωλήσεις είναι {gap} μέρες πίσω.</b><br><br>"
        f"Τελευταία καταχώρηση: <b>{day_name(latest)} {latest:%d/%m/%Y}</b><br><br>"
        f"Κάτι δεν πάει καλά με τον αυτόματο συγχρονισμό. Δοκίμασε την "
        f"<b>Ενημέρωση δεδομένων</b> στο κάτω μέρος της σελίδας — αν αποτύχει, "
        f"θα σου πει γιατί.",
        "bad",
    )


# ══════════════════════════════════════════════════════════════════════════════
def _week_and_check(
    df_s: pd.DataFrame, df_i: pd.DataFrame, df_t: pd.DataFrame, today: date
) -> None:
    """Η εβδομάδα ως τώρα, και η επιταγή που πέφτει."""

    wtd = week_to_date(df_s, today)

    check = check_this_week(df_t, today)
    if check is not None:
        cd = check["check_date"]
        cd = cd.date() if hasattr(cd, "date") else cd
        days = (cd - today).days

        when = "σήμερα" if days == 0 else ("αύριο" if days == 1 else f"σε {days} ημέρες")

        check_card = c.stat(
            "Επιταγή αυτή την εβδομάδα",
            float(check["amount"]),
            accent="var(--navy)",
            foot=f"Πληρωμή {when} — {cd:%d/%m/%Y}",
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
        c.scale(
            f"Εβδομάδα ως τώρα · {wtd['label']}",
            wtd["current"], wtd["previous"],
            foot=f"{wtd['days_elapsed']} ημέρες vs οι ίδιες {wtd['days_elapsed']} πέρσι",
            href=c.link("Πωλήσεις"),
        ),
        check_card,
        cols=2,
    )

    # Τα τιμολόγια είναι δευτερεύοντα — μία σειρά, χωρίς σύγκριση.
    inv_net = invoice_totals(invoices_in_week(df_i, today))["net"]

    c.grid(
        c.stat(
            "Τιμολόγια — καθαρό",
            inv_net,
            tone="pos" if inv_net >= 0 else "neg",
            accent="var(--ink)",
            foot="Τιμολόγια μείον πιστωτικά, τρέχουσα εβδομάδα",
            href=c.link("Παραστατικά"),
        ),
        cols=1,
    )
