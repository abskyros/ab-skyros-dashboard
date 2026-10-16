"""
views/overview.py — Η πρώτη οθόνη (εταιρικό στυλ).

  ┌──────────────┬──────────────┬──────────────┬──────────────┐
  │ ΣΗΜΕΡΑ       │ ΧΘΕΣ         │ ΕΒΔΟΜΑΔΑ     │ ΤΙΜΟΛΟΓΙΑ    │   4 κάρτες KPI
  │ (στόχος)     │              │ ΩΣ ΤΩΡΑ      │ (καθαρό)     │
  ├──────────────┴──────────────┴──────────────┴──────────────┤
  │ ΕΠΟΜΕΝΗ ΕΠΙΤΑΓΗ (navy)                                     │
  ├────────────────────────────────────────────────────────────┤
  │ ΕΠΟΜΕΝΕΣ ΕΠΙΤΑΓΕΣ (πίνακας)                                │
  └────────────────────────────────────────────────────────────┘

ΓΙΑΤΙ ΤΟ «ΣΗΜΕΡΑ» ΕΙΝΑΙ ΠΡΩΤΟ ΚΑΙ ΜΕΓΑΛΟ:

Η αναφορά της ημέρας έρχεται με email το βράδυ. Άρα το «σήμερα» είναι κενό μέχρι
τις 21:00 — αλλά αυτό ΔΕΝ σημαίνει ότι είναι άχρηστο. Το περσινό νούμερο της
ίδιας μέρας είναι ο στόχος σου: «σήμερα πρέπει να πιάσω 7.400». Είναι το πιο
σημαντικό νούμερο της μέρας → πάνω αριστερά, με χρυσή γραμμή (IBM Carbon:
το σημαντικότερο παίρνει τη μεγαλύτερη αντίθεση και θέση).

Η εβδομάδα είναι ΠΑΝΤΑ η τρέχουσα. Κάθε Δευτέρα μηδενίζει μόνη της.
"""

from datetime import date, timedelta

import pandas as pd

from core.metrics import (
    last_year, two_years_ago, day_name,
    sales_on, week_to_date,
    invoice_totals, invoices_in_week,
    checks_ahead_with_number, cash_runway,
)
from core.sheets import load_setting
from ui import components as c

CASH_SETTING = "cash_on_hand"   # ίδιο κλειδί με «Μήνας»/«Επιταγές» — το ταμείο σου


def render(df_s: pd.DataFrame, df_i: pd.DataFrame, df_t: pd.DataFrame, today: date) -> None:
    if df_s.empty and df_i.empty and df_t.empty:
        c.empty(
            "Δεν έχουν φορτωθεί δεδομένα ακόμη",
            "Πάτα «Ενημέρωση» πάνω δεξιά για να τραβήξεις τα πρώτα email."
        )
        return

    # Ειδοποιήσεις πρώτα — αν κάτι θέλει προσοχή, να το δεις αμέσως.
    _check_supply_alert(df_t, today)
    _freshness(df_s, today)

    c.grid(
        _today_card(df_s, today),
        _yesterday_card(df_s, today),
        *_week_cards(df_s, df_i, today),
        cols=4,
    )

    runway = cash_runway(df_t, today, _cash())
    c.grid(_next_check(df_t, runway, today), cols=1)
    _upcoming(df_t, runway)


def _check_supply_alert(df_t: pd.DataFrame, today: date) -> None:
    """
    Προειδοποίηση αν κοντεύουν να τελειώσουν οι σταλμένες επιταγές.

    🟠 στις 3 μπροστά · 🔴 στις 2 ή λιγότερες. Πάνω-πάνω, να το δεις αμέσως.
    """
    info = checks_ahead_with_number(df_t, today)
    ahead = info["ahead"]
    level = info["level"]

    # Αν έχουμε άνετο απόθεμα (4+), καμία ειδοποίηση — μη γεμίζουμε την οθόνη.
    if level == "ok":
        return

    last = info["last_numbered"]
    last_str = f"{last:%d/%m}" if last else "—"

    if level == "urgent":
        c.note(
            f"🔴 <b>Μένουν μόνο {ahead} επιταγές με αριθμό μπροστά σου</b> "
            f"(τελευταία: {last_str}). "
            f"<b>Επίσπευσε την αποστολή νέων επιταγών</b> — αλλιώς θα βρεθείς "
            f"χωρίς έτοιμη επιταγή.",
            "bad",
        )
    else:  # warn
        c.note(
            f"🟠 <b>Έχεις {ahead} επιταγές με αριθμό μπροστά σου</b> "
            f"(τελευταία: {last_str}). "
            f"Καλό είναι να ετοιμάσεις και τις επόμενες, ώστε να μη μείνεις "
            f"χωρίς απόθεμα.",
            "warn",
        )


# ══════════════════════════════════════════════════════════════════════════════
# ΚΑΡΤΕΣ KPI
# ══════════════════════════════════════════════════════════════════════════════
def _today_card(df_s: pd.DataFrame, today: date) -> str:
    """
    Σήμερα: πριν έρθει η αναφορά → ο ΣΤΟΧΟΣ (το περσινό της ίδιας μέρας), μεγάλος.
    Όταν έρθει → το σημερινό ποσό, ▲/▼ και μπάρα προόδου έναντι του στόχου.
    """
    today_now = sales_on(df_s, today)
    ref = last_year(today)
    goal = sales_on(df_s, ref)
    # Πρόπερσι (2 χρόνια πίσω) — εμφανίζεται ΜΟΝΟ αν υπάρχει καταχώρηση.
    ref2 = two_years_ago(today)
    goal2 = sales_on(df_s, ref2)

    ref_txt = f"Πέρσι {day_name(ref, short=True)} {ref:%d/%m}"
    if goal2 is not None:
        ref_txt += f" · πρόπερσι {c.eur(goal2)}"

    if today_now is None:
        # Αν οι πωλήσεις δεν ήρθαν ακόμη, ο χρήστης πρέπει να ξέρει ΓΙΑΤΙ.
        # Λέμε πότε έρχονται — αλλιώς μια κενή κάρτα στις 23:30 ανησυχεί.
        if goal is None:
            return c.kpi("Σήμερα · στόχος", None, badge="Σε εξέλιξη", accent=True,
                         foot="Δεν υπάρχει περσινό για αυτή τη μέρα",
                         href=c.link("Πωλήσεις"))
        return c.kpi("Σήμερα · στόχος", goal, badge="Σε εξέλιξη", progress=0, accent=True,
                     foot=f"{ref_txt} · η αναφορά έρχεται το βράδυ",
                     href=c.link("Πωλήσεις"))

    return c.kpi(
        f"Σήμερα · {day_name(today)} {today:%d/%m}",
        today_now,
        then=goal,
        progress=(today_now / goal) if goal else None,
        accent=True,
        foot=f"Στόχος {c.eur(goal)} · {ref_txt}",
        href=c.link("Πωλήσεις"),
    )


def _yesterday_card(df_s: pd.DataFrame, today: date) -> str:
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

    ref = last_year(yesterday)
    then = sales_on(df_s, ref)
    then2 = sales_on(df_s, two_years_ago(yesterday))

    foot = f"Πέρσι {c.eur(then)} ({day_name(ref, short=True)} {ref:%d/%m})"
    if then2 is not None:
        foot += f" · πρόπερσι {c.eur(then2)}"

    label = "Τελευταία μέρα" if stale else "Χθες"
    return c.kpi(f"{label} · {day_name(yesterday)} {yesterday:%d/%m}", y_now,
                 then=then, foot=foot, href=c.link("Πωλήσεις"))


def _week_cards(df_s: pd.DataFrame, df_i: pd.DataFrame, today: date) -> tuple[str, str]:
    """→ (κάρτα «Εβδομάδα ως τώρα», κάρτα «Τιμολόγια — καθαρό»)."""

    wtd = week_to_date(df_s, today)

    foot = f"{wtd['label']} · πέρσι {c.eur(wtd['previous'])}"
    if wtd.get("two_previous") is not None:
        foot += f" · πρόπερσι {c.eur(wtd['two_previous'])}"

    wk_card = c.kpi("Εβδομάδα ως τώρα", wtd["current"], then=wtd["previous"],
                    foot=foot, href=c.link("Πωλήσεις"))

    # Τα τιμολόγια είναι δευτερεύοντα — χωρίς σύγκριση.
    inv_net = invoice_totals(invoices_in_week(df_i, today))["net"]
    inv_card = c.kpi("Τιμολόγια · καθαρό", inv_net, badge="Εβδομάδα",
                     foot="Τιμολόγια μείον πιστωτικά", href=c.link("Παραστατικά"))
    return wk_card, inv_card


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
            f"Η χθεσινή αναφορά δεν έχει έρθει ακόμη — το σύστημα την ψάχνει "
            f"αυτόματα κάθε 10 λεπτά από τις 15:00. Αν βιάζεσαι, πάτα "
            f"<b>Ενημέρωση</b> πάνω δεξιά.",
            "warn",
        )
        return

    c.note(
        f"⚠️ <b>Οι πωλήσεις είναι {gap} μέρες πίσω.</b><br><br>"
        f"Τελευταία καταχώρηση: <b>{day_name(latest)} {latest:%d/%m/%Y}</b><br><br>"
        f"Κάτι δεν πάει καλά με τον αυτόματο συγχρονισμό. Πάτα "
        f"<b>Ενημέρωση</b> πάνω δεξιά — αν αποτύχει, θα σου πει γιατί.",
        "bad",
    )


# ══════════════════════════════════════════════════════════════════════════════
# ΓΡΑΦΗΜΑ & ΕΠΙΤΑΓΕΣ
# ══════════════════════════════════════════════════════════════════════════════
def _cash() -> float:
    """Το διαθέσιμο ταμείο, όπως το έχεις ορίσει στον «Μήνα» (για την κάλυψη)."""
    try:
        return float(load_setting(CASH_SETTING, "0"))
    except (ValueError, TypeError):
        return 0.0


def _numbers(df_t: pd.DataFrame) -> dict:
    """Ημερομηνία επιταγής → αριθμός επιταγής (κενό αν δεν έχει μπει)."""
    out = {}
    for _, r in df_t.iterrows():
        cd = r["check_date"]
        cd = cd.date() if hasattr(cd, "date") else cd
        num = str(r.get("check_number", "") or "").strip()
        out[cd] = "" if num.lower() == "nan" else num
    return out


def _next_check(df_t: pd.DataFrame, runway: dict, today: date) -> str:
    """Η επόμενη επιταγή — navy κάρτα (η μόνη με προθεσμία)."""
    if not runway["checks"]:
        return c.kpi("Επόμενη επιταγή", None, foot="Καμία επιταγή μπροστά",
                     href=c.link("Τιμολογήσεις"))

    ch = runway["checks"][0]
    days = (ch["date"] - today).days
    days_txt = ("σήμερα" if days == 0 else "αύριο" if days == 1
                else f"σε {days} ημέρες" if days > 0 else "ληγμένη")
    return c.next_check(ch["date"], days_txt, ch["amount"],
                        _numbers(df_t).get(ch["date"], ""), ch["fraction"])


def _upcoming(df_t: pd.DataFrame, runway: dict) -> None:
    """Οι επόμενες 4 επιταγές με την κάλυψή τους από το ταμείο."""
    if not runway["checks"]:
        return
    nums = _numbers(df_t)
    rows = [
        {"date": ch["date"], "amount": ch["amount"], "number": nums.get(ch["date"], ""),
         "status": ch["status"], "fraction": ch["fraction"]}
        for ch in runway["checks"][:4]
    ]
    c.checks_table(rows, href=c.link("Μήνας"))
