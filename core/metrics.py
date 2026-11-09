"""
core/metrics.py — Η επιχειρηματική λογική, σε καθαρές συναρτήσεις.

Εδώ ζουν οι κανόνες του μαγαζιού:
  • Η σύγκριση με πέρσι γίνεται στα 364 ημερολογιακά (= ίδια μέρα εβδομάδας).
  • Η εβδομάδα ξεκινά Δευτέρα.
  • Τα έσοδα πριν από μια επιταγή = πωλήσεις από την προηγούμενη επιταγή ως
    την παραμονή της (εβδομαδιαίες ως 07/12/2026, δεκαήμερες 5/15/25 μετά).
  • «Καθαρό» παραστατικών = τιμολόγια − πιστωτικά.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

import pandas as pd

from core.config import (
    YOY_OFFSET_DAYS, CHECK_PERIOD_DAYS, CHECK_MATCH_TOLERANCE,
    CHECK_WEEKLY_LAG_DAYS, CHECK_DECADE_FROM, CHECK_PAY_DAYS,
    DAYS_GR, DAYS_GR_SHORT, MONTHS_GR,
    GREECE_TZ, SALES_REPORT_HOUR,
)


def now_greece() -> datetime:
    """
    Η ΤΡΕΧΟΥΣΑ ΩΡΑ ΕΛΛΑΔΑΣ — σωστή χειμώνα και καλοκαίρι.

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΓΙΑΤΙ ΔΕΝ ΑΡΚΕΙ ΤΟ datetime.now()                                      │
    │                                                                        │
    │ Το GitHub Actions τρέχει σε UTC. Το datetime.now() εκεί δίνει UTC.     │
    │                                                                        │
    │ Και το cron του GitHub ΔΕΝ ξέρει από θερινή ώρα:                       │
    │     Καλοκαίρι: 21:00 Ελλάδας = 18:00 UTC                              │
    │     Χειμώνας:  21:00 Ελλάδας = 19:00 UTC                              │
    │                                                                        │
    │ Ένα σταθερό cron θα ήταν λάθος τη μισή χρονιά.                         │
    │                                                                        │
    │ Λύση: το cron τρέχει ευρέως, και ΕΔΩ ελέγχουμε την πραγματική ώρα.     │
    │ Η Python ξέρει από zoneinfo — το cron όχι.                             │
    └────────────────────────────────────────────────────────────────────────┘
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(GREECE_TZ))
    except Exception:
        # Fallback: αν λείπει το tzdata (σπάνιο σε Linux), υπολογίζουμε
        # χειροκίνητα. Η θερινή ώρα στην ΕΕ: τελευταία Κυριακή Μαρτίου →
        # τελευταία Κυριακή Οκτωβρίου.
        utc = datetime.utcnow()
        offset = 3 if _is_dst_eu(utc) else 2
        return utc + timedelta(hours=offset)


def _is_dst_eu(utc: datetime) -> bool:
    """Θερινή ώρα ΕΕ: τελευταία Κυριακή Μαρτίου 01:00 UTC → τελ. Κυρ. Οκτωβρίου 01:00 UTC."""
    year = utc.year

    def last_sunday(month: int) -> date:
        d = date(year, month, 31)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    start = datetime.combine(last_sunday(3), datetime.min.time()) + timedelta(hours=1)
    end = datetime.combine(last_sunday(10), datetime.min.time()) + timedelta(hours=1)

    return start <= utc < end


def sales_window_open(now: datetime | None = None) -> tuple[bool, str]:
    """
    Είναι ώρα να ψάξουμε για την αναφορά πωλήσεων;

    → (ανοιχτό, μήνυμα)

    Αρχίζουμε να ψάχνουμε στις 15:00 (ώρα Ελλάδας) και συνεχίζουμε κάθε 10 λεπτά
    ώσπου να βρεθεί. Πριν τις 15:00 δεν έχει νόημα να συνδεθούμε στο Gmail — και
    σίγουρα δεν έχει νόημα να κάνουμε OCR.

    Το παράθυρο κλείνει στις 06:00 του επόμενου πρωινού, ώστε να πιάσουμε και
    αναφορές που έρχονται αργά ή μετά τα μεσάνυχτα.

        15:00 → 23:59   ανοιχτό  (h >= SALES_REPORT_HOUR)
        00:00 → 05:59   ανοιχτό  (μετά τα μεσάνυχτα)
        06:00 → 14:59   κλειστό  (πολύ νωρίς)
    """
    now = now or now_greece()
    h = now.hour

    if h >= SALES_REPORT_HOUR:
        return True, f"{h:02d}:{now.minute:02d} — παράθυρο ανοιχτό"

    if h < 6:
        return True, f"{h:02d}:{now.minute:02d} — παράθυρο ανοιχτό (μετά τα μεσάνυχτα)"

    return False, (
        f"{h:02d}:{now.minute:02d} ώρα Ελλάδας — πολύ νωρίς. "
        f"Ψάχνουμε από τις {SALES_REPORT_HOUR}:00 και μετά."
    )


# ══════════════════════════════════════════════════════════════════════════════
# ΗΜΕΡΟΜΗΝΙΕΣ
# ══════════════════════════════════════════════════════════════════════════════
def today_greece() -> date:
    """
    Η ΣΗΜΕΡΙΝΗ ΜΕΡΑ, ΩΡΑ ΕΛΛΑΔΑΣ.

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΤΟ BUG ΠΟΥ ΕΦΤΙΑΞΕ ΑΥΤΗ Η ΣΥΝΑΡΤΗΣΗ                                    │
    │                                                                        │
    │ Το date.today() στο Streamlit Cloud επιστρέφει UTC — όχι ώρα Ελλάδας.  │
    │                                                                        │
    │ Στις 00:47 ώρα Ελλάδας, η UTC είναι 21:47 της ΠΡΟΗΓΟΥΜΕΝΗΣ μέρας.      │
    │                                                                        │
    │ Αποτέλεσμα: μετά τα μεσάνυχτα, η εφαρμογή νόμιζε ότι είναι ακόμα χθες. │
    │                                                                        │
    │   Ρολόι Windows:      00:47, 15/07                                    │
    │   Κεφαλίδα εφαρμογής: Τρίτη 14/07     ← ΛΑΘΟΣ                          │
    │                                                                        │
    │ Και άρα:                                                              │
    │   • Το «Σήμερα» έδειχνε τη χθεσινή μέρα                                │
    │   • Το «Χθες» έδειχνε την προχθεσινή                                   │
    │   • Οι πωλήσεις που ήρθαν στις 21:30 δεν φαίνονταν πουθενά             │
    │                                                                        │
    │ Επί 3 ώρες κάθε νύχτα (21:00-00:00 UTC), η εφαρμογή ήταν μια μέρα      │
    │ πίσω — ακριβώς την ώρα που έρχονται οι πωλήσεις.                       │
    └────────────────────────────────────────────────────────────────────────┘
    """
    return now_greece().date()


# Ώρα που πληρώνονται οι επιταγές (πρωί). Πριν από αυτήν, η σημερινή επιταγή
# μετράει ακόμη ως «μπροστά»· μετά, θεωρείται πληρωμένη.
CHECK_PAY_HOUR = 10


def check_cutoff(today: date) -> pd.Timestamp:
    """
    Η ημερομηνία-όριο για το «ποιες επιταγές είναι ακόμη μπροστά».

    Οι επιταγές πληρώνονται το πρωί (10:00), όχι στην αλλαγή της ημέρας. Άρα:
      • Πριν τις 10:00 → η σημερινή επιταγή μετράει ΑΚΟΜΗ (όριο = σήμερα)
      • Από τις 10:00 και μετά → η σημερινή θεωρείται πληρωμένη (όριο = αύριο)

    Έτσι η γραμμή της επιταγής φεύγει από την πρόβλεψη στις 10:00 το πρωί της
    ημέρας της, όχι τα μεσάνυχτα της προηγούμενης νύχτας.

    ΔΕΝ αλλάζει κανέναν υπολογισμό — μόνο ΠΟΤΕ μια επιταγή θεωρείται περασμένη.
    """
    now = now_greece()

    # Το «today» που περνιέται είναι κανονικά η σημερινή μέρα Ελλάδας. Αν όμως
    # για κάποιο λόγο δεν είναι (π.χ. δοκιμή), βασιζόμαστε στην ώρα μόνο όταν
    # ταιριάζει με τη σημερινή — αλλιώς κρατάμε την κλασική συμπεριφορά.
    if today == now.date() and now.hour < CHECK_PAY_HOUR:
        # Πριν τις 10:00 — κράτα και τη σημερινή (όριο = σήμερα το πρωί).
        return pd.Timestamp(today)

    # Από τις 10:00 και μετά — η σημερινή έφυγε (όριο = αύριο).
    return pd.Timestamp(today) + pd.Timedelta(days=1)


def week_range(d: date) -> tuple[date, date]:
    """Δευτέρα → Κυριακή της εβδομάδας που περιέχει τη d."""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def last_year(d: date) -> date:
    """
    Η αντίστοιχη μέρα πέρσι.

    ΠΡΟΣΟΧΗ: 364 μέρες, ΟΧΙ «ίδια ημερομηνία».
    Το Σάββατο συγκρίνεται με Σάββατο. Σε λιανική, η 17/3 πέρσι μπορεί να ήταν
    Τρίτη — άχρηστη σύγκριση.
    """
    return d - timedelta(days=YOY_OFFSET_DAYS)


def two_years_ago(d: date) -> date:
    """
    Η αντίστοιχη μέρα ΠΡΟΠΕΡΣΙ — 2×364 = 728 μέρες πίσω.

    Ίδια λογική με το last_year: κρατάμε την ίδια μέρα της εβδομάδας, ώστε
    Σάββατο να συγκρίνεται με Σάββατο.
    """
    return d - timedelta(days=2 * YOY_OFFSET_DAYS)


def day_name(d: date, short: bool = False) -> str:
    return (DAYS_GR_SHORT if short else DAYS_GR)[d.weekday()]


def month_name(m: int) -> str:
    return MONTHS_GR[m - 1]


def as_dates(series: pd.Series) -> pd.Series:
    """Timestamp → date, ασφαλώς."""
    if series.empty:
        return pd.Series([], dtype=object)
    return series.map(lambda x: x.date() if hasattr(x, "date") else x)


# ══════════════════════════════════════════════════════════════════════════════
# ΜΕΤΑΒΟΛΕΣ
# ══════════════════════════════════════════════════════════════════════════════
def pct_change(current, previous) -> float | None:
    """→ ποσοστιαία μεταβολή, ή None αν δεν υπάρχει βάση σύγκρισης."""
    if previous is None or previous == 0 or pd.isna(previous):
        return None
    if current is None or pd.isna(current):
        return None
    return (float(current) - float(previous)) / float(previous) * 100


# ══════════════════════════════════════════════════════════════════════════════
# ΠΩΛΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
def sales_on(df: pd.DataFrame, d: date) -> float | None:
    """Καθαρές πωλήσεις μιας ημέρας. None αν δεν υπάρχει εγγραφή."""
    if df.empty:
        return None
    hit = df[as_dates(df["date"]) == d]
    return float(hit["net_sales"].sum()) if not hit.empty else None


def sales_between(df: pd.DataFrame, start: date, end: date) -> float | None:
    """Άθροισμα πωλήσεων σε διάστημα (και τα δύο άκρα μέσα)."""
    if df.empty or start is None:
        return None
    dts = as_dates(df["date"])
    hit = df[(dts >= start) & (dts <= end)]
    return float(hit["net_sales"].sum()) if not hit.empty else None


def sales_row(df: pd.DataFrame, d: date) -> dict | None:
    """Όλα τα στοιχεία μιας ημέρας: πωλήσεις, πελάτες, καλάθι."""
    if df.empty:
        return None
    hit = df[as_dates(df["date"]) == d]
    if hit.empty:
        return None

    r = hit.iloc[0]
    return {
        "net_sales":  float(r["net_sales"]),
        "customers":  int(r["customers"]) if pd.notna(r["customers"]) else None,
        "avg_basket": float(r["avg_basket"]) if pd.notna(r["avg_basket"]) else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ΕΝΤΟΠΙΣΜΟΣ ΛΑΘΩΝ OCR
#
# Η ιδέα: κάθε Δευτέρα μοιάζει με τις προηγούμενες Δευτέρες. Αν μια μέρα
# ξεφεύγει πολύ από τον τυπικό της εαυτό, μάλλον το OCR διάβασε λάθος ψηφίο
# (π.χ. 23.743 → 2.374 ή 237.439).
#
# ΔΕΝ διορθώνει τίποτα μόνο του. Σημαίνει «κοίτα αυτή τη μέρα» — η διόρθωση
# γίνεται από την εφαρμογή (Πωλήσεις → Διόρθωση) ή ξαναδιαβάζοντας το mail.
# ══════════════════════════════════════════════════════════════════════════════
ANOMALY_DEVIATION = 45.0   # % απόκλιση από την τυπική ίδια μέρα → ύποπτο
ANOMALY_LOOKBACK  = 60     # ελέγχονται οι τελευταίες τόσες ημέρες
ANOMALY_SAMPLES   = 12     # έως τόσες προηγούμενες όμοιες μέρες ως βάση
ANOMALY_MIN_BASE  = 4      # λιγότερες → δεν υπάρχει αξιόπιστη βάση, δεν κρίνουμε


def find_anomalies(df: pd.DataFrame, today: date) -> list[dict]:
    """
    → λίστα ύποπτων ημερών, νεότερη πρώτη:
        {date, net_sales, customers, baseline, deviation, reasons}

    Βάση σύγκρισης: η ΔΙΑΜΕΣΟΣ των (έως 12) προηγούμενων ημερών ΤΗΣ ΙΔΙΑΣ
    εβδομάδας (Δευτέρα με Δευτέρες). Η διάμεσος αντέχει σε μεμονωμένες
    ακραίες τιμές — ένα λάθος δεν μολύνει την κρίση για τις επόμενες μέρες.

    Τρία σημάδια:
      1. Πωλήσεις που αποκλίνουν >45% από την τυπική ίδια μέρα
      2. Μηδενικές πωλήσεις σε μέρα που το μαγαζί δούλεψε (έχει πελάτες)
      3. Καλάθι που δεν συμφωνεί με πωλήσεις ÷ πελάτες (ολίσθηση ψηφίου)

    ΦΙΛΤΡΟ ΣΕΖΟΝΙΚΟΤΗΤΑΣ: πριν σημειωθεί μέρα για το σημάδι 1, ελέγχεται
    και η ίδια μέρα ΠΕΡΣΙ. Αν συμφωνεί με εκείνη, η αποκλίση είναι σεζόν
    (π.χ. Ιούλιος στο νησί) — όχι λάθος. Έτσι δεν σημειώνονται ψευδώς οι
    υψηλές μέρες της τουριστικής περιόδου.
    """
    if df.empty:
        return []

    since = today - timedelta(days=ANOMALY_LOOKBACK)
    dts = as_dates(df["date"])
    hist = df[dts < today].sort_values("date")          # όλο το παρελθόν, χωρίς σήμερα
    recent = df[(dts >= since) & (dts < today)]         # μόνο αυτές κρίνονται

    out = []
    for _, row in recent.iterrows():
        d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
        net = float(row["net_sales"]) if pd.notna(row["net_sales"]) else None
        cust = int(row["customers"]) if pd.notna(row["customers"]) else None
        basket = float(row["avg_basket"]) if pd.notna(row["avg_basket"]) else None

        # Η βάση: προηγούμενες μέρες με το ίδιο weekday
        same = hist[hist["date"].dt.weekday == d.weekday()]
        base = float(same["net_sales"].tail(ANOMALY_SAMPLES).median()) \
            if len(same) >= ANOMALY_MIN_BASE else None

        reasons, deviation = [], None

        if net is not None and net <= 0 and cust and cust > 0:
            reasons.append("μηδενικές πωλήσεις με κανονικούς πελάτες")

        if net is not None and base:
            deviation = (net - base) / base * 100
            if abs(deviation) > ANOMALY_DEVIATION:
                # ΣΕΖΟΝΙΚΟΤΗΤΑ: η τυπική μέρα μετριέται από τις ΠΡΟΣΦΑΤΕΣ
                # εβδομάδες — αλλά τον Ιούλιο η Σκύρος γεμίζει τουρίστες και
                # κάθε μέρα είναι πολύ πάνω από τον Ιούνιο ΧΩΡΙΣ να είναι λάθος.
                # Συγκρίνουμε λοιπόν και με την ΙΔΙΑ μέρα ΠΕΡΣΙ: αν συμφωνεί
                # με εκείνη, είναι σεζόν — όχι λάθος OCR.
                ly = sales_on(hist, last_year(d))
                ly_dev = ((net - ly) / ly * 100) if ly else None
                if ly_dev is None or abs(ly_dev) > ANOMALY_DEVIATION:
                    reasons.append(
                        f"{'πάνω' if deviation > 0 else 'κάτω'} {abs(deviation):.0f}% "
                        f"από την τυπική {day_name(d)}"
                    )

        if net and cust and basket and cust > 0:
            implied = net / cust
            if abs(basket - implied) / implied > 0.03:
                reasons.append("το καλάθι δεν βγαίνει από πωλήσεις ÷ πελάτες")

        if reasons:
            out.append({
                "date": d, "net_sales": net, "customers": cust,
                "baseline": base, "deviation": deviation, "reasons": reasons,
            })

    return sorted(out, key=lambda a: a["date"], reverse=True)


def week_to_date(df: pd.DataFrame, today: date) -> dict:
    """
    Η εβδομάδα ΩΣ ΤΩΡΑ vs οι ΙΔΙΕΣ μέρες πέρσι.

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΤΟ BUG ΠΟΥ ΕΦΤΙΑΞΕ ΑΥΤΟ                                                │
    │                                                                        │
    │ Η αναφορά πωλήσεων έρχεται το βράδυ. Άρα την Τρίτη το πρωί, το Sheet   │
    │ έχει ΜΟΝΟ τη Δευτέρα.                                                  │
    │                                                                        │
    │ Ο παλιός κώδικας συνέκρινε:                                            │
    │     φέτος  Δευ→Τρι  = 1.000 €  (μόνο η Δευτέρα υπάρχει)               │
    │     πέρσι  Δευ→Τρι  = 2.000 €  (και οι δύο μέρες υπάρχουν)            │
    │     → «-50%»  ενώ στην πραγματικότητα είναι ΙΣΟΠΑΛΙΑ.                  │
    │                                                                        │
    │ ΛΥΣΗ: κόβουμε ΚΑΙ ΤΑ ΔΥΟ στην τελευταία μέρα που έχει ΠΡΑΓΜΑΤΙΚΑ       │
    │ δεδομένα φέτος. Μόλις μπει η Τρίτη το βράδυ, η σύγκριση επεκτείνεται   │
    │ μόνη της σε Δευ–Τρι και για τα δύο χρόνια.                            │
    │                                                                        │
    │ Καλύτερα να δείχνεις λιγότερα και σωστά, παρά περισσότερα και λάθος.   │
    └────────────────────────────────────────────────────────────────────────┘
    """
    start, _ = week_range(today)
    return _to_date(df, today, start)


def period_to_date(df: pd.DataFrame, today: date, df_t: pd.DataFrame | None = None) -> dict:
    """
    Το ΔΙΑΣΤΗΜΑ ΠΩΛΗΣΕΩΝ ως τώρα vs οι ίδιες μέρες πέρσι — ίδια λογική με το
    week_to_date, αλλά η αρχή είναι η αρχή του διαστήματος που πληρώνει την
    επόμενη επιταγή (εβδομάδα ως 06/12/2026, μετά 25→04 / 05→14 / 15→24).
    """
    start = sales_window_from(df_t)(today)[0]
    return _to_date(df, today, start)


def _to_date(df: pd.DataFrame, today: date, start: date) -> dict:
    """Από start ως την τελευταία μέρα με φετινά, vs ίδιες μέρες πέρσι/πρόπερσι."""
    # ── ΩΣ ΠΟΥ ΕΧΟΥΜΕ ΠΡΑΓΜΑΤΙΚΑ ΔΕΔΟΜΕΝΑ ΦΕΤΟΣ; ──
    #
    # Η τελευταία μέρα ΜΕΣΑ στην τρέχουσα εβδομάδα με καταχωρημένες πωλήσεις.
    # Αν δεν έχει έρθει τίποτα ακόμη (Δευτέρα πρωί), πέφτουμε πίσω στο «today»
    # ώστε η κάρτα να μη σπάσει — απλώς θα δείξει 0 και για τα δύο.
    end = today
    if not df.empty:
        d = as_dates(df["date"])
        in_week = df[(d >= start) & (d <= today)]
        if not in_week.empty:
            last = in_week["date"].max()
            end = last.date() if hasattr(last, "date") else last
        else:
            # Καμία μέρα της εβδομάδας δεν έχει έρθει ακόμη.
            end = start

    elapsed = (end - start).days

    ly_start = last_year(start)
    ly_end = last_year(end)          # ΙΔΙΟ κόψιμο και πέρσι — αυτό είναι το κλειδί

    # Πρόπερσι: ΙΔΙΟ κόψιμο, 2 χρόνια πίσω. Επιστρέφει None αν δεν υπάρχουν
    # δεδομένα τόσο παλιά — τότε η κάρτα δεν δείχνει τρίτη μπάρα.
    ly2_start = two_years_ago(start)
    ly2_end = two_years_ago(end)

    cur = sales_between(df, start, end) or 0.0
    prev = sales_between(df, ly_start, ly_end)
    prev2 = sales_between(df, ly2_start, ly2_end)

    label = day_name(start, short=True) if elapsed == 0 else \
        f"{day_name(start, short=True)}–{day_name(end, short=True)}"

    return {
        "current": cur,
        "previous": prev,
        "two_previous": prev2,
        "pct": pct_change(cur, prev),
        "days_elapsed": elapsed + 1,
        "label": label,
        "start": start,
        "end": end,
    }


def weekly_series(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Σύνολα ανά εβδομάδα ISO για ένα έτος → index=isoweek."""
    if df.empty:
        return pd.DataFrame(columns=["net_sales", "customers"])

    d = df.copy()
    d["_d"] = as_dates(d["date"])
    d["_iso_year"] = d["_d"].map(lambda x: x.isocalendar()[0])
    d["_iso_week"] = d["_d"].map(lambda x: x.isocalendar()[1])

    sub = d[d["_iso_year"] == year]
    if sub.empty:
        return pd.DataFrame(columns=["net_sales", "customers"])

    return sub.groupby("_iso_week").agg(
        net_sales=("net_sales", "sum"),
        customers=("customers", "sum"),
    )


def monthly_breakdown(df: pd.DataFrame, year: int) -> list[dict]:
    """Ανάλυση ανά μήνα για ένα έτος."""
    if df.empty:
        return []

    d = df[df["date"].dt.year == year]
    out = []

    for m in range(1, 13):
        sub = d[d["date"].dt.month == m]
        if sub.empty:
            continue
        out.append({
            "month": m,
            "name": month_name(m),
            "total": float(sub["net_sales"].sum()),
            "days": len(sub),
            "customers": int(sub["customers"].sum()) if sub["customers"].notna().any() else 0,
            "avg_day": float(sub["net_sales"].mean()),
        })

    return out


def month_weeks(year: int, month: int) -> list[tuple[date, date]]:
    """
    Οι ΟΛΟΚΛΗΡΕΣ εβδομάδες (Δευτέρα → Κυριακή) ενός μήνα: 4 ή 5.

    Μια εβδομάδα που μοιράζεται ανάμεσα σε δύο μήνες πάει εκεί που έχει τις
    περισσότερες μέρες — δηλαδή στον μήνα της ΠΕΜΠΤΗΣ της. Έτσι κάθε εβδομάδα
    έχει 7 μέρες και συγκρίνεται δίκαια με τις άλλες. Το άθροισμά τους ΔΕΝ
    βγάζει ακριβώς το σύνολο του μήνα.
    """
    first = date(year, month, 1)
    thursday = first + timedelta(days=(3 - first.weekday()) % 7)

    out = []
    while thursday.month == month:
        monday = thursday - timedelta(days=3)
        out.append((monday, monday + timedelta(days=6)))
        thursday += timedelta(days=7)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ΠΑΡΑΣΤΑΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
def _is_credit(types: pd.Series) -> pd.Series:
    return types.str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)


def invoice_totals(df: pd.DataFrame) -> dict:
    """→ {invoices, credits, net} — το καθαρό είναι τιμολόγια μείον πιστωτικά."""
    if df.empty:
        return {"invoices": 0.0, "credits": 0.0, "net": 0.0}

    credit = _is_credit(df["type"])
    inv = float(df[~credit]["value"].sum())
    crd = float(df[credit]["value"].sum())

    return {"invoices": inv, "credits": crd, "net": inv - crd}


def invoices_in_week(df: pd.DataFrame, d: date) -> pd.DataFrame:
    if df.empty:
        return df

    start, end = week_range(d)
    return invoices_between(df, start, end)


def invoices_between(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Τα παραστατικά από start ως end (μαζί και οι δύο μέρες)."""
    if df.empty:
        return df
    mask = (df["date"] >= pd.Timestamp(start)) & \
           (df["date"] <= pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59))
    return df.loc[mask]


def decade_range(d: date) -> tuple[date, date]:
    """
    Το δεκαήμερο τιμολόγησης που περιέχει τη μέρα d:
    1–10, 11–20 ή 21–τέλος μήνα (28/29/30/31).
    """
    if d.day <= 10:
        return date(d.year, d.month, 1), date(d.year, d.month, 10)
    if d.day <= 20:
        return date(d.year, d.month, 11), date(d.year, d.month, 20)
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 21), date(d.year, d.month, last)


# Η αλλαγή στις ΑΓΟΡΕΣ (όχι στις επιταγές):
#   ως 11/10/2026  → εβδομάδες Δευ–Κυρ (επιταγή Δευτέρα, 57 μέρες μετά)
#   12–20/10/2026  → ενδιάμεση περίοδος 9 ημερών (επιταγή 15/12/2026)
#   από 21/10/2026 → δεκαήμερα 1–10 / 11–20 / 21–τέλος (επιταγή 5/15/25)
_WEEKLY_LAST_END = date(2026, 10, 11)
_TRANSITION = (date(2026, 10, 12), date(2026, 10, 20))
_TRANSITION_CHECK = date(2026, 12, 15)


def billing_period(d: date) -> tuple[date, date]:
    """Η περίοδος τιμολόγησης της ΑΒ που περιέχει τη μέρα d (βλ. πάνω)."""
    if d <= _WEEKLY_LAST_END:
        return week_range(d)
    if d <= _TRANSITION[1]:
        return _TRANSITION
    return decade_range(d)


def period_kind(start: date, end: date) -> str:
    """«Εβδομάδα», «Ενδιάμεση» ή «Δεκαήμερο» — για ετικέτες."""
    if end <= _WEEKLY_LAST_END:
        return "Εβδομάδα"
    if (start, end) == _TRANSITION:
        return "Ενδιάμεση"
    return "Δεκαήμερο"


def neighbor_periods(d: date, fn=None) -> tuple[tuple, tuple, tuple]:
    """
    → (προηγούμενο, τρέχον, επόμενο) διάστημα γύρω από τη d.
    fn: ο κανόνας (billing_period = αγορές, default · sales_window = πωλήσεις).
    """
    fn = fn or billing_period
    cur = fn(d)[:2]
    prev = fn(cur[0] - timedelta(days=1))[:2]
    nxt = fn(cur[1] + timedelta(days=1))[:2]
    return prev, cur, nxt


def month_periods(year: int, month: int, fn=None) -> list[tuple[date, date]]:
    """
    Τα διαστήματα ενός μήνα, με τη σειρά (fn: billing_period ή sales_window).

    Ένα διάστημα που μοιράζεται ανάμεσα σε δύο μήνες πάει στον μήνα της ΜΕΣΑΙΑΣ
    του μέρας — για εβδομάδα αυτό είναι η Πέμπτη (ίδιος κανόνας με month_weeks).
    """
    fn = fn or billing_period
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    out, d = [], first - timedelta(days=12)
    while d <= last + timedelta(days=12):
        p = fn(d)[:2]
        mid = p[0] + timedelta(days=(p[1] - p[0]).days // 2)
        if mid.month == month and mid.year == year and p not in out:
            out.append(p)
        d = p[1] + timedelta(days=1)
    return out


# ── ΔΙΑΣΤΗΜΑΤΑ ΠΩΛΗΣΕΩΝ (ανά ΠΛΗΡΩΜΗ επιταγής) ──
#
# Οι πωλήσεις «πληρώνουν» την επόμενη επιταγή: οι μέρες από την προηγούμενη
# επιταγή ως την παραμονή της. Ακολουθούν τις ΗΜΕΡΟΜΗΝΙΕΣ ΠΛΗΡΩΜΗΣ, όχι τις
# περιόδους αγορών (αυτές είναι στα Παραστατικά):
#   ως 06/12/2026   → εβδομάδα Δευ–Κυρ, επιταγή τη Δευτέρα μετά
#   07–14/12/2026   → επιταγή 15/12/2026 (η πρώτη δεκαήμερη)
#   μετά            → 25→04 (επιταγή 5), 05→14 (επιταγή 15), 15→24 (επιταγή 25)
_LAST_WEEKLY_CHECK = date(2026, 12, 7)
_FIRST_DECADE_CHECK = date(2026, 12, 15)


def sales_window(d: date) -> tuple[date, date, date]:
    """→ (από, ως, επιταγή που πληρώνουν) για το διάστημα πωλήσεων της d."""
    if d < _LAST_WEEKLY_CHECK:
        s, e = week_range(d)
        return s, e, e + timedelta(days=1)
    if d < _FIRST_DECADE_CHECK:
        return _LAST_WEEKLY_CHECK, _FIRST_DECADE_CHECK - timedelta(days=1), _FIRST_DECADE_CHECK
    y, m = d.year, d.month
    if 5 <= d.day <= 14:
        return date(y, m, 5), date(y, m, 14), date(y, m, 15)
    if 15 <= d.day <= 24:
        return date(y, m, 15), date(y, m, 24), date(y, m, 25)
    if d.day >= 25:
        ny, nm = _shift_months(y, m, 1)
        return date(y, m, 25), date(ny, nm, 4), date(ny, nm, 5)
    py, pm = _shift_months(y, m, -1)
    return date(py, pm, 25), date(y, m, 4), date(y, m, 5)


def sales_window_kind(start: date, end: date) -> str:
    """«Εβδομάδα» (ως 7 μέρες) ή «Δεκαήμερο» (8–11 μέρες, επιταγές 5/15/25)."""
    return "Εβδομάδα" if (end - start).days + 1 <= 7 else "Δεκαήμερο"


# Το μεγαλύτερο νόμιμο κενό ανάμεσα σε δύο επιταγές: 25 → 05 του επόμενου
# μήνα = 11 μέρες. Μεγαλύτερο κενό = λείπει μια τιμολόγηση στη μέση → τότε
# ΔΕΝ ενώνουμε δύο διαστήματα σε ένα, πέφτουμε στον κανόνα.
_MAX_CHECK_GAP = 11


def sales_window_from(df_t: pd.DataFrame | None):
    """
    Ο κανόνας «διάστημα πωλήσεων» με ΠΗΓΗ ΤΑ EXCEL ΤΗΣ ΑΒ.

    → συνάρτηση d → (από, ως, επιταγή), όπως η sales_window.

    Όπου υπάρχουν πραγματικές επιταγές (από τα Excel τιμολόγησης), το διάστημα
    είναι: από την ΠΡΟΗΓΟΥΜΕΝΗ επιταγή ως την ΠΑΡΑΜΟΝΗ της επόμενης — όποιες κι
    αν είναι οι ημερομηνίες (Δευτέρα, 5/15/25, ή μια αλλαγή της ΑΒ στο μέλλον).
    Ο σταθερός κανόνας (sales_window) μένει μόνο για τις επιταγές που δεν
    έχουν σταλεί ακόμη, ή αν λείπει μια τιμολόγηση στη μέση.
    """
    import bisect

    real = sorted(set(as_dates(df_t["check_date"]))) if df_t is not None and not df_t.empty else []

    def fn(d: date) -> tuple[date, date, date]:
        i = bisect.bisect_right(real, d)
        if 0 < i < len(real):
            prev, nxt = real[i - 1], real[i]
            if (nxt - prev).days <= _MAX_CHECK_GAP:
                return prev, nxt - timedelta(days=1), nxt
        return sales_window(d)

    return fn


def billing_check_date(start: date, end: date) -> date:
    """Ποια επιταγή πληρώνει την περίοδο τιμολόγησης start..end."""
    if end <= _WEEKLY_LAST_END:
        return end + timedelta(days=CHECK_WEEKLY_LAG_DAYS)
    if (start, end) == _TRANSITION:
        return _TRANSITION_CHECK
    return decade_check_date(start) or end + timedelta(days=CHECK_WEEKLY_LAG_DAYS)


def decade_check_date(start: date) -> date | None:
    """
    Ποια επιταγή πληρώνει το δεκαήμερο που ξεκινά στο start:
    1–10 → 5, 11–20 → 15, 21–τέλος → 25, δύο μήνες μετά.
    None για τα δεκαήμερα πριν την αλλαγή (τότε πλήρωναν εβδομαδιαίες).
    """
    y, m = _shift_months(start.year, start.month, 2)
    day = {1: 5, 11: 15, 21: 25}.get(start.day)
    if day is None:
        return None
    cd = date(y, m, day)
    return cd if cd >= _DECADE_FROM else None


def invoices_monthly(df: pd.DataFrame, year: int) -> list[dict]:
    if df.empty:
        return []

    d = df[df["date"].dt.year == year]
    out = []

    for m in range(1, 13):
        sub = d[d["date"].dt.month == m]
        if sub.empty:
            continue
        t = invoice_totals(sub)
        out.append({"month": m, "name": month_name(m), **t})

    return out


# ══════════════════════════════════════════════════════════════════════════════
# ΤΙΜΟΛΟΓΗΣΕΙΣ / ΕΠΙΤΑΓΕΣ
# ══════════════════════════════════════════════════════════════════════════════
_DECADE_FROM = date.fromisoformat(CHECK_DECADE_FROM)
_PERIOD_DATES_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*-\s*(\d{1,2})\.(\d{1,2})\.(\d{4})")


def check_period(check_date: date, prev_check: date | None = None) -> tuple[date, date]:
    """
    Ποιες πωλήσεις «μαζεύεις» για μια επιταγή: από την ΠΡΟΗΓΟΥΜΕΝΗ επιταγή ως
    την παραμονή αυτής. Εβδομαδιαίες → 7 μέρες, δεκαήμερες → 10 (ή 8–11).
    Χωρίς προηγούμενη → οι 7 μέρες πριν.
    """
    end = check_date - timedelta(days=1)
    if prev_check and prev_check < check_date:
        return prev_check, end
    return check_date - timedelta(days=CHECK_PERIOD_DAYS), end


def parse_period(text) -> tuple[date, date] | None:
    """«21.10.2026 -31.10.2026» → (21/10/2026, 31/10/2026). Λάθος/κενό → None."""
    m = _PERIOD_DATES_RE.search(str(text or ""))
    if not m:
        return None
    try:
        a = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        b = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
    except ValueError:
        return None
    if not (0 <= (b - a).days <= 20):   # π.χ. τυπογραφικό «30.03.206»
        return None
    return a, b


def _shift_months(y: int, m: int, k: int) -> tuple[int, int]:
    i = y * 12 + (m - 1) + k
    return i // 12, i % 12 + 1


def purchase_period(check_date: date, period_text: str = "") -> tuple[date, date]:
    """
    Ποιες ΑΓΟΡΕΣ πληρώνει μια επιταγή.
    Πρώτα από το Excel (στήλη period)· αν λείπει, από τον κανόνα:
      • δεκαήμερη (5/15/25, από 15/12/2026): το δεκαήμερο δύο μήνες πριν
      • εβδομαδιαία: Δευ–Κυρ που τελείωσε 57 μέρες πριν
    """
    p = parse_period(period_text)
    if p:
        return p
    if check_date >= _DECADE_FROM and check_date.day in CHECK_PAY_DAYS:
        y, m = _shift_months(check_date.year, check_date.month, -2)
        if check_date.day == 5:
            return date(y, m, 1), date(y, m, 10)
        if check_date.day == 15:
            return date(y, m, 11), date(y, m, 20)
        return date(y, m, 21), date(y, m, calendar.monthrange(y, m)[1])
    end = check_date - timedelta(days=CHECK_WEEKLY_LAG_DAYS)
    return end - timedelta(days=6), end


def next_pay_dates(after: date, until: date) -> list[date]:
    """
    Οι ημερομηνίες επιταγών ΜΕΤΑ το `after` ως το `until`: 5, 15, 25 κάθε
    μήνα (από 15/12/2026)· πριν από αυτό, κάθε Δευτέρα.
    """
    out = []
    last_weekly = _DECADE_FROM - timedelta(days=8)   # 07/12/2026
    d = after + timedelta(days=1)
    while d <= until:
        if d >= _DECADE_FROM:
            if d.day in CHECK_PAY_DAYS:
                out.append(d)
        elif d <= last_weekly and d.weekday() == 0:
            out.append(d)
        d += timedelta(days=1)
    return out


def daily_purchases(df: pd.DataFrame) -> dict:
    """
    Κάθε πραγματική επιταγή «σπασμένη» σε ποσό ανά ημέρα αγορών:
    επιταγή ÷ μέρες της περιόδου της. → {ημέρα: ποσό}

    Έτσι μια παλιά εβδομαδιαία επιταγή μοιράζεται σωστά σε δύο δεκαήμερα
    (π.χ. 3 μέρες στο ένα, 4 στο άλλο).
    """
    out: dict = {}
    if df.empty:
        return out
    for cd, amt, per in zip(as_dates(df["check_date"]), df["amount"],
                            df.get("period", pd.Series([""] * len(df), index=df.index))):
        if cd is None or pd.isna(cd) or pd.isna(amt):
            continue
        a, b = purchase_period(cd, per)
        days = (b - a).days + 1
        per_day = float(amt) / days
        for i in range(days):
            day = a + timedelta(days=i)
            out[day] = out.get(day, 0.0) + per_day
    return out


def estimate_ly_check(daily: dict, start: date, end: date) -> float | None:
    """
    Πόσο ήταν ΠΕΡΣΙ (−364) οι αγορές των ημερών start..end.
    Αν λείπουν κάποιες μέρες, αναλογική αναγωγή· κάτω από τις μισές → None.
    """
    days = (end - start).days + 1
    vals = [daily.get(last_year(start + timedelta(days=i))) for i in range(days)]
    have = [v for v in vals if v is not None]
    if not have or len(have) < days / 2:
        return None
    return sum(have) * days / len(have)


def check_falls_in_week(check_date: date, week_start: date) -> bool:
    """
    Η επιταγή «πέφτει» στην εβδομάδα ΠΡΙΝ την ημερομηνία της —
    τότε πρέπει να την έχεις υπόψη σου.
    """
    payment_week, _ = week_range(check_date - timedelta(days=7))
    return week_start == payment_week


def checks_ahead_with_number(df: pd.DataFrame, today: date) -> dict:
    """
    📮 ΠΟΣΕΣ ΕΠΙΤΑΓΕΣ ΕΧΟΥΜΕ ΑΚΟΜΑ ΜΠΡΟΣΤΑ — με βάση τους αριθμούς.

    Οι επιταγές έχουν διαδοχικούς αριθμούς. Όσες ΜΕΛΛΟΝΤΙΚΕΣ επιταγές έχουν ήδη
    αριθμό, τόσες έχεις «στείλει» και είναι εξασφαλισμένες. Όταν λίγες μένουν με
    αριθμό, πρέπει να στείλεις νέες — αλλιώς θα βρεθείς χωρίς επιταγή έτοιμη.

    → {
        "ahead": int,          # πόσες μελλοντικές επιταγές έχουν αριθμό
        "last_numbered": date, # η πιο μακρινή επιταγή με αριθμό
        "level": str,          # "ok" | "warn" (≤3) | "urgent" (≤2)
      }
    """
    empty = {"ahead": 0, "last_numbered": None, "level": "urgent"}
    if df.empty or "check_number" not in df.columns:
        return empty

    future = df[df["check_date"] >= check_cutoff(today)].copy()
    if future.empty:
        return empty

    # Πόσες μελλοντικές έχουν συμπληρωμένο αριθμό;
    has_num = future[
        future["check_number"].astype(str).str.strip().replace("nan", "") != ""
    ]
    ahead = len(has_num)

    last_numbered = None
    if not has_num.empty:
        ld = has_num["check_date"].max()
        last_numbered = ld.date() if hasattr(ld, "date") else ld

    if ahead <= 2:
        level = "urgent"
    elif ahead <= 3:
        level = "warn"
    else:
        level = "ok"

    return {"ahead": ahead, "last_numbered": last_numbered, "level": level}


def next_check(df: pd.DataFrame, today: date) -> pd.Series | None:
    """Η αμέσως επόμενη επιταγή."""
    if df.empty:
        return None
    future = df[df["check_date"] >= check_cutoff(today)].sort_values("check_date")
    return future.iloc[0] if not future.empty else None


def upcoming_checks(df: pd.DataFrame, today: date) -> list[dict]:
    """
    Όλες οι επιταγές από ΣΗΜΕΡΑ και μετά, με σειρά πληρωμής (νωρίτερη πρώτη).

    → [{"date": date, "amount": float, "period": str}, ...]

    Οι ληγμένες (πριν από σήμερα) ΔΕΝ μπαίνουν — η δεξαμενή δείχνει τι έχεις
    μπροστά σου, όχι τι πλήρωσες ήδη.
    """
    if df.empty:
        return []

    future = df[df["check_date"] >= check_cutoff(today)].sort_values("check_date")

    out = []
    for _, r in future.iterrows():
        cd = r["check_date"]
        out.append({
            "date": cd.date() if hasattr(cd, "date") else cd,
            "amount": float(r["amount"]),
            "period": str(r.get("period", "") or ""),
        })
    return out


def last_sent_check(df: pd.DataFrame, edits: dict | None = None) -> date | None:
    """
    Ως ποια επιταγή έχουν σταλεί τα πακέτα: η ΠΙΟ ΠΡΟΣΦΑΤΗ επιταγή με voucher.

    Αυτή και ΟΛΕΣ οι προηγούμενές της θεωρούνται σταλμένες, ακόμα κι αν δεν έχουν
    δικό τους voucher: ένα πακέτο πηγαίνει 4-5 επιταγές (το voucher μπαίνει στην
    τελευταία), και τα παλιά πακέτα δεν καταχωρήθηκαν ποτέ.

    edits: {ημερομηνία επιταγής → voucher} που μόλις γράφτηκαν — το df φορτώθηκε
    πριν την αποθήκευση και δεν τα ξέρει ακόμα.
    """
    vouchers = {}
    if not df.empty and "voucher" in df.columns:
        for d, v in zip(as_dates(df["check_date"]), df["voucher"]):
            vouchers[d] = str(v or "").strip()
    vouchers.update(edits or {})

    filled = [d for d, v in vouchers.items() if v and v.lower() != "nan"]
    return max(filled) if filled else None


def cash_runway(df: pd.DataFrame, today: date, cash: float) -> dict:
    """
    🛢️ Η ΔΕΞΑΜΕΝΗ — πόσο μακριά φτάνει το ταμείο στις επόμενες επιταγές.

    Παίρνει το διαθέσιμο ταμείο και το «χύνει» στις επιταγές με τη σειρά που
    λήγουν. Κάθε επιταγή γεμίζει όσο φτάνουν τα λεφτά· μόλις στερέψουν, οι
    υπόλοιπες μένουν άδειες.

    → {
        "cash": float,                    # το ταμείο που δόθηκε
        "total_due": float,               # σύνολο όλων των επόμενων επιταγών
        "fully_covered": int,             # πόσες επιταγές καλύπτονται 100%
        "checks": [                       # μία εγγραφή ανά επιταγή, με σειρά
            {
              "date", "amount", "period",
              "covered": float,           # πόσα λεφτά «έπεσαν» πάνω της
              "fraction": float,          # 0.0–1.0 κάλυψη
              "status": "full"|"partial"|"empty",
            }, ...
        ],
        "leftover_after_full": float,     # τι μένει για να κλείσει η μισή επιταγή
        "surplus": float,                 # αν το ταμείο ξεπερνά ΟΛΕΣ τις επιταγές
      }
    """
    checks = upcoming_checks(df, today)
    # Το ταμείο μπορεί να είναι ΑΡΝΗΤΙΚΟ (δάνειο). Τότε δεν καλύπτεται καμία
    # επιταγή — αλλά κρατάμε την πραγματική τιμή για να τη δείξουμε.
    cash = float(cash or 0)

    total_due = sum(c["amount"] for c in checks)
    remaining = cash
    fully = 0
    rows = []

    for c in checks:
        amt = c["amount"]
        covered = max(0.0, min(amt, remaining))
        remaining -= amt  # μπορεί να γίνει αρνητικό — δεν πειράζει, το κόβουμε πιο κάτω
        frac = (covered / amt) if amt > 0 else 1.0

        if frac >= 0.999:
            status = "full"
            fully += 1
        elif frac > 0:
            status = "partial"
        else:
            status = "empty"

        rows.append({
            **c,
            "covered": covered,
            "fraction": frac,
            "status": status,
        })

    # Τι μένει από το ταμείο για να κλείσει η πρώτη μισο-γεμάτη επιταγή;
    partial = next((r for r in rows if r["status"] == "partial"), None)
    leftover = (partial["amount"] - partial["covered"]) if partial else 0.0

    # Πλεόνασμα: αν το ταμείο ξεπερνά όλες τις επιταγές
    surplus = max(0.0, cash - total_due)

    return {
        "cash": cash,
        "total_due": total_due,
        "fully_covered": fully,
        "checks": rows,
        "leftover_after_full": leftover,
        "surplus": surplus,
    }


def _expand_fixed(fixed: list, start: date, end: date) -> list:
    """
    Απλώνει τα μηνιαία πάγια έξοδα σε συγκεκριμένες ημερομηνίες, από start ως end.

    fixed : [{"name": str, "amount": float, "day": int}, ...]
            day = ημέρα του μήνα (1-31). Αν ο μήνας δεν έχει τόση μέρα (π.χ. 31
            στον Φλεβάρη), πέφτει στην τελευταία μέρα του μήνα.

    → [{"date": date, "name": str, "amount": float}, ...]  ταξινομημένα
    """
    import calendar

    out = []
    # Ξεκινάμε από τον μήνα του start και προχωράμε μήνα-μήνα ως το end.
    y, mo = start.year, start.month
    while date(y, mo, 1) <= end:
        last_dom = calendar.monthrange(y, mo)[1]
        for f in fixed:
            amt = float(f.get("amount", 0) or 0)
            if amt <= 0:
                continue
            day = int(f.get("day", 1) or 1)
            day = min(max(day, 1), last_dom)   # κράτα το μέσα στα όρια του μήνα
            d = date(y, mo, day)
            if start <= d <= end:
                out.append({"date": d, "name": str(f.get("name", "")), "amount": amt})
        # επόμενος μήνας
        mo += 1
        if mo > 12:
            mo = 1
            y += 1

    out.sort(key=lambda x: x["date"])
    return out


def ly_period(start: date, end: date) -> tuple[date, date]:
    """
    Η ΠΕΡΣΙΝΗ περίοδος αγορών που αντιστοιχεί σε start..end.

    Δεκαήμερο → το ΙΔΙΟ ημερολογιακό δεκαήμερο πέρσι (01–10/11/2026 → 01–10/11/2025,
    21–28/02/2027 → 21–29/02/2026 αν ήταν δίσεκτο). Η τιμολόγηση είναι πλέον
    ημερολογιακή, άρα συγκρίνουμε ημερολογιακά — ΟΧΙ −364.
    Οτιδήποτε άλλο (εβδομάδα) → ίδιες μέρες εβδομάδας πέρσι (−364).
    """
    if start.day in (1, 11, 21) and decade_range(start) == (start, end):
        return decade_range(date(start.year - 1, start.month, start.day))
    return last_year(start), last_year(end)


def agores_coverage(df_agores: pd.DataFrame, df_checks: pd.DataFrame) -> list[tuple[date, date]]:
    """
    Ποιες περίοδοι αγορών είναι ΠΛΗΡΩΣ γνωστές από Excel: για κάθε επιταγή που
    έχει γραμμές στο «agores», η περίοδος που πληρώνει (από το Excel/κανόνα).
    Μια μέρα χωρίς αγορές (Κυριακή) ΜΕΣΑ σε γνωστή περίοδο σημαίνει 0, όχι «λείπει».
    """
    if df_agores is None or df_agores.empty:
        return []
    periods = {}
    if not df_checks.empty:
        for cd, per in zip(as_dates(df_checks["check_date"]), df_checks["period"].astype(str)):
            periods[cd] = per
    out = []
    for cd in sorted(set(as_dates(df_agores["check_date"].dropna()))):
        out.append(purchase_period(cd, periods.get(cd, "")))
    return out


def estimate_from_agores(daily: dict, coverage: list, start: date, end: date) -> tuple | None:
    """
    → (ποσό, περσινό_από, περσινό_ως) ή None αν η περσινή περίοδος δεν είναι
    ΟΛΗ καλυμμένη από Excel (τότε η πρόβλεψη πέφτει στον παλιό τρόπο).
    Ποσό = άθροισμα των ΠΡΑΓΜΑΤΙΚΩΝ περσινών αγορών των ίδιων ημερών.
    """
    la, lb = ly_period(start, end)
    d = la
    while d <= lb:
        if not any(a <= d <= b for a, b in coverage):
            return None
        d += timedelta(days=1)
    total = sum(v for k, v in daily.items() if la <= k <= lb)
    return round(total, 2), la, lb


def _eur_txt(v: float) -> str:
    """1234.5 → «1.234,50 €» (για τις ετικέτες της πρόβλεψης)."""
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _ly_day(d: date) -> date | None:
    """Η ίδια ημερολογιακή μέρα πέρσι (29/02 → None: δεν υπήρχε)."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return None


def invoices_daily_net(df_inv: pd.DataFrame | None) -> dict:
    """Παραστατικά → {ημέρα: τιμολόγια − πιστωτικά}."""
    if df_inv is None or df_inv.empty:
        return {}
    sign = (~_is_credit(df_inv["type"])).map({True: 1.0, False: -1.0})
    vals = df_inv["value"].astype(float) * sign
    return vals.groupby(as_dates(df_inv["date"])).sum().to_dict()


def invoice_to_check_ratio(real_daily: dict, inv_daily: dict, coverage: list,
                           upto: date, days: int = 90) -> float:
    """
    Πόσο από το «καθαρό» των Παραστατικών καταλήγει στην επιταγή.

    Η επιταγή = παραστατικά ΜΕΙΟΝ χρεώσεις κάρτας κλπ (π.χ. 21–31/10/2026:
    98.219,90 → 96.985,32, δηλαδή ×0,987). Το μετράμε στις τελευταίες `days`
    μέρες που έχουν ΚΑΙ Excel ΚΑΙ παραστατικά. Όρια 0,90–1,05 για ασφάλεια.
    """
    covered = [(a, b) for a, b in coverage if b < upto]
    if not covered or not inv_daily:
        return 1.0
    end = max(b for _, b in covered)
    start = end - timedelta(days=days)
    rng = [d for d in (start + timedelta(days=i) for i in range(days + 1))
           if any(a <= d <= b for a, b in covered)]
    chk = sum(real_daily.get(d, 0.0) for d in rng)
    inv = sum(inv_daily.get(d, 0.0) for d in rng)
    if inv <= 0:
        return 1.0
    return min(max(chk / inv, 0.90), 1.05)


def project_checks_to_year_end(df_checks: pd.DataFrame, today: date,
                                last_real: date, until: date | None = None,
                                df_agores: pd.DataFrame | None = None,
                                df_invoices: pd.DataFrame | None = None) -> list[dict]:
    """
    Προβλεπόμενες επιταγές από την τελευταία πραγματική ως το `until` (αν
    λείπει: ως το τέλος του έτους). Περνάει κανονικά στη νέα χρονιά.

    Όπου ΔΕΝ έχουμε πραγματική επιταγή (μετά την τελευταία που ξέρουμε), «γεμίζουμε»
    με την ΠΕΡΣΙΝΗ επιταγή της αντίστοιχης εβδομάδας — ακριβώς όπως κάνουμε με τις
    πωλήσεις. Έτσι βλέπουμε ΟΛΗ τη χρονιά μπροστά, με μέτρο σύγκρισης το πέρσι.

    Ημερομηνίες: 5/15/25 (δεκαήμερες)· ποσό: οι ΠΕΡΣΙΝΕΣ αγορές των ίδιων
    ημερών, από τις παλιές επιταγές «σπασμένες» ανά μέρα (daily_purchases).

    → [{"date": date, "amount": float, "period": str, "estimated": True}, ...]
    """
    if df_checks.empty:
        return []

    out = []
    year_end = until or date(today.year, 12, 31)
    daily = daily_purchases(df_checks)          # ο παλιός τρόπος (εφεδρεία)

    # Ο ΣΩΣΤΟΣ τρόπος: οι πραγματικές περσινές αγορές ανά ημέρα, από τα Excel.
    real_daily, coverage = {}, []
    if df_agores is not None and not df_agores.empty:
        real_daily = df_agores.groupby(as_dates(df_agores["date"]))["amount"].sum().to_dict()
        coverage = agores_coverage(df_agores, df_checks)

    # Οι ΦΕΤΙΝΕΣ αγορές που ήδη ξέρουμε (Παραστατικά), για τις μέρες που πέρασαν.
    inv_daily = invoices_daily_net(df_invoices)
    ratio = invoice_to_check_ratio(real_daily, inv_daily, coverage, today) if inv_daily else 1.0

    for d in next_pay_dates(last_real, year_end):
        a, b = purchase_period(d)

        # ── ΜΕΡΕΣ ΠΟΥ ΠΕΡΑΣΑΝ: φετινά Παραστατικά (× ratio = μείον κάρτες) ──
        known_end = min(b, today - timedelta(days=1)) if inv_daily else a - timedelta(days=1)
        known = 0.0
        if known_end >= a:
            known = sum(inv_daily.get(a + timedelta(days=i), 0.0)
                        for i in range((known_end - a).days + 1)) * ratio
        f_start = max(a, known_end + timedelta(days=1))

        # ── ΜΕΡΕΣ ΠΟΥ ΕΡΧΟΝΤΑΙ: οι περσινές αγορές των ίδιων ημερών ──
        future, ly_txt = 0.0, ""
        if f_start <= b:
            if f_start == a:
                est = estimate_from_agores(real_daily, coverage, a, b) if coverage else None
                if est:
                    future, la, lb = est
                    ly_txt = f"αγορές {la:%d/%m}–{lb:%d/%m/%Y}"
            else:
                # Κομμάτι δεκαημέρου: ίδιες ημερολογιακές μέρες πέρσι.
                days = [f_start + timedelta(days=i) for i in range((b - f_start).days + 1)]
                ly = [_ly_day(x) for x in days]
                ly = [x for x in ly if x]
                if ly and all(any(p <= x <= q for p, q in coverage) for x in ly):
                    future = sum(real_daily.get(x, 0.0) for x in ly)
                    ly_txt = f"πέρσι {ly[0]:%d/%m}–{ly[-1]:%d/%m/%Y}"
            if not ly_txt:
                future = estimate_ly_check(daily, f_start, b) or 0.0
                ly_txt = "κατά προσέγγιση — λείπουν Excel"

        amount = round(known + future, 2)
        if known_end >= a:
            basis = f"φετινά {a:%d/%m}–{known_end:%d/%m} {_eur_txt(known)}"
            if f_start <= b:
                basis += f" + {ly_txt}"
        else:
            basis = ly_txt
        if amount and amount > 0:
            out.append({"date": d, "amount": amount, "basis": basis,
                        "period": f"{a:%d.%m} – {b:%d.%m}", "estimated": True})

    return out


def cash_forecast(df_checks: pd.DataFrame, df_sales: pd.DataFrame,
                  today: date, cash: float, fixed: list | None = None,
                  project_to_year_end: bool = True, until: date | None = None,
                  df_agores: pd.DataFrame | None = None,
                  df_invoices: pd.DataFrame | None = None) -> dict:
    """
    🔮 ΠΡΟΒΛΕΨΗ ΡΕΥΣΤΟΤΗΤΑΣ — θα βγει ο μήνας;

    Η δεξαμενή (cash_runway) δείχνει «τι φτάνει ΤΩΡΑ». Αυτή δείχνει «τι θα
    φτάνει ΟΤΑΝ ΛΗΞΕΙ κάθε υποχρέωση», λαμβάνοντας υπόψη τις πωλήσεις που θα
    μπουν στο μεταξύ.

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΤΙ ΜΠΑΙΝΕΙ ΣΤΗΝ ΠΡΟΒΛΕΨΗ                                               │
    │                                                                        │
    │ ΕΚΡΟΕΣ:  οι επιταγές (εβδομαδιαίες) + τα πάγια έξοδα (μηνιαία, π.χ.    │
    │          μισθοδοσία, ΦΠΑ, ΙΚΑ). Καθένα αφαιρείται τη μέρα που λήγει.   │
    │ ΕΙΣΡΟΕΣ: οι προβλεπόμενες πωλήσεις = όσα πούλησες ΤΙΣ ΙΔΙΕΣ ΜΕΡΕΣ      │
    │          ΠΕΡΣΙ (πιάνει την εποχικότητα).                              │
    │                                                                        │
    │ Περπατάμε ΜΕΡΑ-ΜΕΡΑ: προσθέτουμε πωλήσεις, αφαιρούμε κάθε υποχρέωση    │
    │ στη σειρά που λήγει. Αν το υπόλοιπο πέσει κάτω από 0 → ΕΛΛΕΙΜΜΑ.       │
    └────────────────────────────────────────────────────────────────────────┘

    fixed : προαιρετική λίστα πάγιων [{"name", "amount", "day"}], που
            επαναλαμβάνονται κάθε μήνα στη μέρα `day`.
    until : ως ποια μέρα δείχνουμε (π.χ. σήμερα + 3 μήνες). Αν λείπει: ως το
            τέλος του έτους (η παλιά συμπεριφορά). Επιταγές και πάγια μετά
            από αυτή τη μέρα δεν μπαίνουν.

    → {
        "cash": float,
        "checks": [                       # μία εγγραφή ανά ΥΠΟΧΡΕΩΣΗ (χρονικά)
            {
              "date", "amount", "period",
              "kind": "check" | "fixed",   # τι είδους εκροή
              "name": str,                 # όνομα (για τα πάγια)
              "sales_until": float,        # πωλήσεις των ημερών της επιταγής
              "sales_from", "sales_to",    # οι μέρες αυτές (μόνο στις επιταγές)
              "sales_actual", "sales_ly",  # πραγματικές φετινές + περσινές
              "balance_before", "balance_after",
              "covered": bool, "shortfall": float,
            }, ...
        ],
        "first_gap": dict | None,
        "all_covered": bool,
        "based_on_year": int,
      }
    """
    checks = upcoming_checks(df_checks, today)
    if until:
        checks = [ch for ch in checks if ch["date"] <= until]
    # ΑΡΝΗΤΙΚΟ επιτρέπεται (π.χ. −50.000 από δάνειο): η πρόβλεψη ξεκινά από
    # εκεί και δείχνει πότε ξαναβγαίνεις θετικός με τις πωλήσεις.
    cash = float(cash or 0)

    # ── ΦΤΙΑΞΕ ΕΝΙΑΙΑ ΛΙΣΤΑ ΕΚΡΟΩΝ (επιταγές + πάγια) ──
    events = []
    for ch in checks:
        events.append({
            "date": ch["date"],
            "amount": ch["amount"],
            "period": ch.get("period", ""),
            "kind": "check",
            "name": "",
            "estimated": False,   # ΠΡΑΓΜΑΤΙΚΗ επιταγή
        })

    # ── ΠΡΟΒΛΕΠΟΜΕΝΕΣ ΕΠΙΤΑΓΕΣ (ως το τέλος του έτους) ──
    #
    # Όπου δεν έχουμε πραγματική επιταγή, γεμίζουμε με την περσινή της ίδιας
    # εβδομάδας — ίδια λογική με τις πωλήσεις. Έτσι βλέπουμε όλη τη χρονιά.
    if project_to_year_end and checks:
        last_real = checks[-1]["date"]
        for pc in project_checks_to_year_end(df_checks, today, last_real, until,
                                             df_agores, df_invoices):
            events.append({
                "date": pc["date"],
                "amount": pc["amount"],
                "period": pc.get("period", ""),
                "basis": pc.get("basis", ""),
                "kind": "check",
                "name": "",
                "estimated": True,    # ΠΡΟΒΛΕΠΟΜΕΝΗ (περσινή)
            })

    # Ο ορίζοντας των πάγιων: αν προβλέπουμε ως το τέλος του έτους, τα πάγια
    # απλώνονται κι αυτά ως εκεί. Αλλιώς, μόνο ως την τελευταία πραγματική.
    if fixed and events:
        check_dates = [e["date"] for e in events if e["kind"] == "check"]
        horizon = until or (max(check_dates) if check_dates else today)
        for fx in _expand_fixed(fixed, today, horizon):
            events.append({
                "date": fx["date"],
                "amount": fx["amount"],
                "period": "",
                "kind": "fixed",
                "name": fx["name"],
                "estimated": False,
            })

    if not events:
        return {
            "cash": cash, "checks": [], "first_gap": None,
            "all_covered": True, "based_on_year": today.year - 1,
        }

    # Ταξινόμηση χρονικά. Αν ίδια μέρα, οι επιταγές πρώτα, μετά τα πάγια.
    events.sort(key=lambda e: (e["date"], 0 if e["kind"] == "check" else 1))

    rows = []
    balance = cash
    first_gap = None

    # ── ΟΙ ΜΕΡΕΣ ΚΑΘΕ ΕΠΙΤΑΓΗΣ ──
    #
    # Κάθε επιταγή «πληρώνεται» από τις πωλήσεις των ημερών ΤΗΣ: από την
    # προηγούμενη επιταγή ως την παραμονή της (εβδομάδα στις εβδομαδιαίες,
    # δεκαήμερο στις δεκαήμερες). ΚΑΙ για την πρώτη: η 09/11/2026 μετράει
    # 02/11–08/11, όχι μόνο από σήμερα. Τα «Διαθέσιμα μετρητά» είναι ΞΕΧΩΡΙΣΤΑ
    # από αυτές τις πωλήσεις (επιλογή του χρήστη) — άρα δεν μετριούνται διπλά.
    #
    # Μέρες που πέρασαν → ΠΡΑΓΜΑΤΙΚΕΣ φετινές πωλήσεις. Μέρες που έρχονται (ή
    # λείπει η αναφορά) → οι ίδιες μέρες ΠΕΡΣΙ (−364).
    daily = dict(zip(as_dates(df_sales["date"]), df_sales["net_sales"].astype(float)))         if not df_sales.empty else {}
    sales_from = None

    for ev in events:
        cd = ev["date"]

        # ── ΠΩΛΗΣΕΙΣ: ΜΟΝΟ ΣΤΙΣ ΕΠΙΤΑΓΕΣ ──
        #
        # Ως την ημέρα μιας επιταγής έχουν μπει στο ταμείο οι πωλήσεις από την
        # ΠΡΟΗΓΟΥΜΕΝΗ επιταγή ως την παραμονή της (7 μέρες στις εβδομαδιαίες,
        # ~10 στις δεκαήμερες). Τις προβλέπουμε από πέρσι (−364).
        #
        # Τα πάγια (μισθοδοσία, ΦΠΑ κλπ) ΔΕΝ προσθέτουν πωλήσεις — απλώς
        # αφαιρούνται. Έτσι κάθε μέρα πωλήσεων μετράει μία φορά.
        win = {}
        if ev["kind"] == "check":
            if sales_from is None:
                sales_from = _previous_check_date(df_checks, cd) or cd - timedelta(days=7)
            wk_end = cd - timedelta(days=1)
            actual = ly = 0.0
            d = sales_from
            while d <= wk_end:
                if d < today and d in daily:
                    actual += daily[d]
                else:
                    ly += daily.get(last_year(d), 0.0)
                d += timedelta(days=1)
            predicted = actual + ly
            win = {"sales_from": sales_from, "sales_to": wk_end,
                   "sales_actual": actual, "sales_ly": ly}
            sales_from = max(sales_from, cd)
        else:
            predicted = 0.0

        balance_before = balance + predicted
        balance_after = balance_before - ev["amount"]
        covered = balance_after >= 0
        shortfall = 0.0 if covered else -balance_after

        row = {
            **ev,
            **win,
            "sales_until": predicted,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "covered": covered,
            "shortfall": shortfall,
        }
        rows.append(row)

        if not covered and first_gap is None:
            first_gap = row

        balance = balance_after

    return {
        "cash": cash,
        "checks": rows,
        "first_gap": first_gap,
        "all_covered": first_gap is None,
        "based_on_year": today.year - 1,
    }


def _previous_check_date(df_checks: pd.DataFrame, cd: date) -> date | None:
    """Η τελευταία επιταγή ΠΡΙΝ την cd (η αρχή των ημερών πωλήσεων της cd)."""
    if df_checks.empty:
        return None
    prev = [d for d in as_dates(df_checks["check_date"]) if d < cd]
    return max(prev) if prev else None


def check_this_week(df: pd.DataFrame, today: date) -> pd.Series | None:
    """Η επιταγή που πληρώνεται αυτή την εβδομάδα, αν υπάρχει."""
    if df.empty:
        return None

    start, _ = week_range(today)
    for _, row in df.iterrows():
        cd = row["check_date"]
        if pd.isna(cd):
            continue
        if check_falls_in_week(cd.date() if hasattr(cd, "date") else cd, start):
            return row
    return None


def match_last_year_check(df: pd.DataFrame, check_date: date) -> float | None:
    """
    Βρίσκει την περσινή αντίστοιχη επιταγή (±3 μέρες γύρω από τις 364).
    Οι επιταγές δεν πέφτουν πάντα ακριβώς την ίδια μέρα.
    """
    if df.empty:
        return None

    target = last_year(check_date)
    dts = as_dates(df["check_date"])
    near = df[dts.map(lambda x: abs((x - target).days) <= CHECK_MATCH_TOLERANCE)]

    return float(near.iloc[0]["amount"]) if not near.empty else None


def month_rows(df_t: pd.DataFrame, df_s: pd.DataFrame, year: int, month: int | None,
               df_agores: pd.DataFrame | None = None) -> list[dict]:
    """
    Χτίζει τις γραμμές της σελίδας «Μήνας».

    Κάθε γραμμή: επιταγή, τι πωλήσεις κάλυψε, τι έξοδα γράφτηκαν,
    και τι μένει. Το «μένει» είναι το νούμερο που μετράει.
    """
    if df_t.empty:
        return []

    dts = as_dates(df_t["check_date"])
    if month is None or month == 0:
        sub = df_t[dts.map(lambda d: d.year == year)]
    else:
        sub = df_t[dts.map(lambda d: d.year == year and d.month == month)]

    # Όλες οι ημερομηνίες επιταγών, για να βρούμε την ΠΡΟΗΓΟΥΜΕΝΗ κάθε μίας.
    all_dates = sorted({d for d in dts if d is not None and not pd.isna(d)})
    daily = daily_purchases(df_t)

    def _prev(d: date) -> date | None:
        earlier = [x for x in all_dates if x < d]
        return earlier[-1] if earlier else None

    # Οι ΠΡΑΓΜΑΤΙΚΕΣ περσινές αγορές ανά ημέρα (Excel → «agores»), ίδιες με την
    # Πρόβλεψη. Όπου λείπουν Excel, ο παλιός τρόπος (μοίρασμα επιταγών).
    real_daily, coverage = {}, []
    if df_agores is not None and not df_agores.empty:
        real_daily = df_agores.groupby(as_dates(df_agores["date"]))["amount"].sum().to_dict()
        coverage = agores_coverage(df_agores, df_t)

    rows = []
    for _, r in sub.iterrows():
        cd = r["check_date"]
        cd = cd.date() if hasattr(cd, "date") else cd

        amount = float(r["amount"])
        expenses = _to_float(r.get("expenses", ""))

        prev = _prev(cd)
        p_start, p_end = check_period(cd, prev)
        period_sales = sales_between(df_s, p_start, p_end)

        # Πέρσι: ίδιες μέρες πωλήσεων (−364) και οι αγορές των ίδιων ημερών.
        ly_start, ly_end = last_year(p_start), last_year(p_end)
        a, b = purchase_period(cd, r.get("period", ""))

        rows.append({
            "_row":        int(r["_row"]) if pd.notna(r.get("_row")) else None,
            "check_date":  cd,
            "period":      str(r.get("period", "") or ""),
            "amount":      amount,
            "sales":       period_sales,
            "expenses":    expenses,
            "expenses_raw": str(r.get("expenses", "") or ""),
            "check_number": str(r.get("check_number", "") or ""),
            "voucher":     str(r.get("voucher", "") or ""),
            "sent_date":   str(r.get("sent_date", "") or ""),
            "ly_amount":   _ly_check_amount(real_daily, coverage, daily, a, b),
            "ly_sales":    sales_between(df_s, ly_start, ly_end),
            "balance":     (period_sales - amount - expenses) if period_sales is not None else None,
        })

    return rows


def _ly_check_amount(real_daily: dict, coverage: list, daily: dict,
                     a: date, b: date) -> float | None:
    """Πέρσι: πραγματικές αγορές (Excel) αν υπάρχουν, αλλιώς ο παλιός τρόπος."""
    est = estimate_from_agores(real_daily, coverage, a, b) if coverage else None
    return est[0] if est else estimate_ly_check(daily, a, b)


def _to_float(v) -> float:
    if not v:
        return 0.0
    try:
        return float(str(v).replace("€", "").replace(",", ".").strip())
    except ValueError:
        return 0.0

