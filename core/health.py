"""
core/health.py — ΕΛΕΓΧΟΣ ΥΓΕΙΑΣ των δεδομένων.

ΓΙΑΤΙ ΥΠΑΡΧΕΙ: σχεδόν όλα τα λάθη που βρήκαμε ήταν ΣΙΩΠΗΛΑ — καμία
ειδοποίηση, απλώς λάθος ή ελλιπή νούμερα που έμοιαζαν σωστά:
  • η επιταγή 25/12/2026 γραφόταν στη στήλη F και «δεν εμφανιζόταν»
  • η αναφορά πωλήσεων της 21/10/2026 δεν έφτασε ποτέ στο mailbox
  • ένα Excel (27/07/2026) δεν αθροίζει στην επιταγή, ένα (24/08/2026) λείπει

Εδώ ελέγχουμε ΜΟΝΟ — δεν διορθώνουμε τίποτα. Κάθε εύρημα λέει τι λείπει και
πού να το φτιάξεις. Η Επισκόπηση τα δείχνει σε μια διακριτική ειδοποίηση.

→ check_all(...) = [{"level": "bad"|"warn"|"info", "title": str, "text": str}, ...]
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from core.metrics import (
    as_dates, invoices_between, invoice_totals, next_pay_dates,
    purchase_period,
)

SALES_LOOKBACK_DAYS = 60     # μέρες πωλήσεων που ελέγχουμε (παλιότερα = ιστορικό)
TIMOL_GRACE_DAYS = 8         # μετά το τέλος μιας περιόδου αγορών, σε τόσες μέρες
                             # πρέπει να έχει έρθει το Excel της (συνήθως ~5)
RECONCILE_TOLERANCE = 0.04   # Παραστατικά vs επιταγή: ως 4% (κάρτες ≈ 1,3%)
RECONCILE_DAYS = 180         # συγκρίνουμε τις επιταγές των τελευταίων 6 μηνών


# ══════════════════════════════════════════════════════════════════════════════
# ΚΛΕΙΣΤΕΣ ΜΕΡΕΣ — δεν είναι «λείπει αναφορά»
# ══════════════════════════════════════════════════════════════════════════════
def orthodox_easter(year: int) -> date:
    """Ορθόδοξο Πάσχα (αλγόριθμος Meeus, ιουλιανό → γρηγοριανό)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    return date(year, month, day) + timedelta(days=13)


def closed_days(year: int) -> set[date]:
    """Μέρες που το κατάστημα είναι κλειστό: Πρωτοχρονιά, Πάσχα, Χριστούγεννα."""
    return {date(year, 1, 1), orthodox_easter(year), date(year, 12, 25)}


# ══════════════════════════════════════════════════════════════════════════════
# ΟΙ ΕΛΕΓΧΟΙ
# ══════════════════════════════════════════════════════════════════════════════
def missing_sales_days(df_s: pd.DataFrame, today: date) -> list[date]:
    """
    Μέρες χωρίς αναφορά πωλήσεων στις τελευταίες SALES_LOOKBACK_DAYS.
    Ως ΠΡΟΧΘΕΣ — η χθεσινή μπορεί ακόμα να έρχεται (το «Τελευταία αναφορά»
    της κεφαλίδας καλύπτει ήδη τη χθεσινή).
    """
    have = set(as_dates(df_s["date"])) if not df_s.empty else set()
    end = today - timedelta(days=2)
    start = today - timedelta(days=SALES_LOOKBACK_DAYS)
    closed = closed_days(start.year) | closed_days(end.year)
    out, d = [], start
    while d <= end:
        if d not in have and d not in closed:
            out.append(d)
        d += timedelta(days=1)
    return out


def missing_timologiseis(df_t: pd.DataFrame, today: date) -> list[dict]:
    """
    Επιταγές που ΕΠΡΕΠΕ να έχουν ήρθει: η περίοδος αγορών τους τελείωσε πριν
    από TIMOL_GRACE_DAYS+ μέρες, αλλά δεν υπάρχει τιμολόγηση με αυτή την ημερομηνία.
    Κοιτάμε τις επιταγές από 30 μέρες πίσω ως 90 μπροστά.
    """
    have = set(as_dates(df_t["check_date"])) if not df_t.empty else set()
    out = []
    for cd in next_pay_dates(today - timedelta(days=30), today + timedelta(days=90)):
        a, b = purchase_period(cd)
        if b + timedelta(days=TIMOL_GRACE_DAYS) <= today and cd not in have:
            out.append({"check": cd, "start": a, "end": b})
    return out


def broken_rows(raw: dict) -> dict:
    """
    Γραμμές του Sheet με ΚΕΝΗ στήλη A αλλά δεδομένα σε άλλες στήλες — το
    σύμπτωμα του «γράφτηκε στη στήλη F». Η εφαρμογή τις αγνοεί σιωπηλά.
    raw: {"sales": [[...]], "invoices": [...], "timologiseis": [...]} (με κεφαλίδα)
    → {φύλλο: [αριθμοί γραμμών]}
    """
    out = {}
    for sheet, rows in (raw or {}).items():
        bad = [i for i, r in enumerate(rows[1:], start=2)
               if r and not str(r[0]).strip() and any(str(x).strip() for x in r[1:])]
        if bad:
            out[sheet] = bad
    return out


def reconcile(df_t: pd.DataFrame, df_i: pd.DataFrame, today: date) -> list[dict]:
    """
    Παραστατικά της περιόδου (καθαρό) vs η επιταγή που την πληρώνει.
    Η επιταγή = παραστατικά μείον χρεώσεις κάρτας (≈1,3%). Μεγάλη απόκλιση
    σημαίνει: λείπουν παραστατικά, υπάρχουν διπλά, ή η επιταγή είναι λάθος.
    Μόνο για επιταγές με γνωστή περίοδο και παραστατικά που έχουν συγχρονιστεί.
    """
    if df_t.empty or df_i.empty:
        return []
    first_inv = min(as_dates(df_i["date"]))
    recent = df_t.sort_values("check_date", ascending=False)
    since = today - timedelta(days=RECONCILE_DAYS)
    out = []
    for _, r in recent.iterrows():
        cd = pd.Timestamp(r["check_date"]).date()
        a, b = purchase_period(cd, str(r.get("period", "")))
        if b >= today - timedelta(days=1) or a < first_inv:
            continue                     # περίοδος σε εξέλιξη ή πριν τα δεδομένα
        if b < since:
            break
        net = invoice_totals(invoices_between(df_i, a, b))["net"]
        amount = float(r["amount"])
        if net <= 0:
            out.append({"check": cd, "start": a, "end": b, "amount": amount, "net": net, "diff": None})
            continue
        diff = (amount - net) / net
        if abs(diff) > RECONCILE_TOLERANCE:
            out.append({"check": cd, "start": a, "end": b, "amount": amount, "net": net, "diff": diff})
    return out


def agores_gaps(df_t: pd.DataFrame, df_agores: pd.DataFrame | None, today: date) -> list[date]:
    """
    Επιταγές των τελευταίων 13 μηνών ΧΩΡΙΣ αγορές ανά ημέρα (το Excel λείπει ή
    δεν αθροίζει) — η πρόβλεψη για τα αντίστοιχα δεκαήμερα πέφτει σε «κατά προσέγγιση».
    """
    if df_t.empty or df_agores is None:
        return []
    have = set(as_dates(df_agores["check_date"].dropna())) if not df_agores.empty else set()
    since = today - timedelta(days=400)
    return sorted(d for d in as_dates(df_t["check_date"]) if since <= d <= today and d not in have)


# ══════════════════════════════════════════════════════════════════════════════
def check_all(df_s: pd.DataFrame, df_i: pd.DataFrame, df_t: pd.DataFrame,
              today: date, raw: dict | None = None,
              df_agores: pd.DataFrame | None = None,
              jobs: dict | None = None) -> list[dict]:
    """Όλοι οι έλεγχοι → λίστα ευρημάτων (τα σοβαρά πρώτα). Κενή = όλα καλά."""
    out = []

    def fmt(ds: list[date], n: int = 8) -> str:
        s = ", ".join(f"{d:%d/%m/%Y}" for d in ds[:n])
        return s + (f" και άλλες {len(ds) - n}" if len(ds) > n else "")

    bad = broken_rows(raw or {})
    for sheet, rows in bad.items():
        out.append({"level": "bad", "title": f"Σπασμένες γραμμές στο φύλλο «{sheet}»",
                    "text": f"{len(rows)} γραμμές έχουν κενή στήλη A (π.χ. γραμμή {rows[0]}) "
                            f"και η εφαρμογή τις αγνοεί. Άνοιξε το Sheet και διόρθωσέ τις."})

    miss_t = missing_timologiseis(df_t, today)
    for m in miss_t:
        out.append({"level": "bad", "title": f"Λείπει η τιμολόγηση για την επιταγή {m['check']:%d/%m/%Y}",
                    "text": f"Οι αγορές {m['start']:%d/%m}–{m['end']:%d/%m/%Y} τελείωσαν, αλλά δεν "
                            f"ήρθε (ή δεν διαβάστηκε) το Excel. Έλεγξε το email ή πάτα "
                            f"Ενημέρωση → Τιμολογήσεις."})

    miss_s = missing_sales_days(df_s, today)
    if miss_s:
        out.append({"level": "warn", "title": f"Λείπουν πωλήσεις για {len(miss_s)} "
                                              f"{'μέρα' if len(miss_s) == 1 else 'μέρες'}",
                    "text": f"{fmt(miss_s)}. Πιθανόν η αναφορά να μην έφτασε στο ftoulisgm@gmail.com — "
                            f"προώθησέ την και κάνε «Βαθιά σάρωση», ή πρόσθεσέ τη στη "
                            f"«Χειροκίνητη καταχώρηση»."})

    def eur(v: float) -> str:
        """1234.5 → «1.234,50 €» — μόνο ο αριθμός, όχι όλο το κείμενο."""
        return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    for r in reconcile(df_t, df_i, today):
        if r["diff"] is None:
            txt = (f"Δεν υπάρχουν παραστατικά για τις αγορές {r['start']:%d/%m}–{r['end']:%d/%m/%Y}, "
                   f"ενώ η επιταγή είναι {eur(r['amount'])}.")
        else:
            pct = f"{r['diff'] * 100:+.1f}%".replace(".", ",")
            txt = (f"Παραστατικά {r['start']:%d/%m}–{r['end']:%d/%m}: {eur(r['net'])} · "
                   f"επιταγή {eur(r['amount'])} ({pct}). Συνήθως διαφέρουν ~1–2% "
                   f"(χρεώσεις κάρτας). Μπορεί να λείπουν ή να είναι διπλά παραστατικά.")
        out.append({"level": "warn", "title": f"Η επιταγή {r['check']:%d/%m/%Y} δεν συμφωνεί με τα Παραστατικά",
                    "text": txt})

    for name, run in (jobs or {}).items():
        if run and run.get("status") == "completed" and run.get("conclusion") == "failure":
            out.append({"level": "warn", "title": f"Απέτυχε ο αυτόματος συγχρονισμός «{name}»",
                        "text": "Η τελευταία εκτέλεση στο GitHub απέτυχε. Αν ξαναγίνει, "
                                "άνοιξε το GitHub → Actions για λεπτομέρειες."})

    gaps = agores_gaps(df_t, df_agores, today)
    if gaps:
        out.append({"level": "info", "title": f"{len(gaps)} επιταγές χωρίς αγορές ανά ημέρα",
                    "text": f"{fmt(gaps)}: το Excel λείπει ή δεν αθροίζει στην επιταγή. Η πρόβλεψη "
                            f"για τα αντίστοιχα δεκαήμερα της επόμενης χρονιάς βγαίνει "
                            f"«κατά προσέγγιση»."})

    order = {"bad": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda x: order[x["level"]])
