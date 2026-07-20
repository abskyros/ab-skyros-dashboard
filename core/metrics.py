"""
core/metrics.py — Η επιχειρηματική λογική, σε καθαρές συναρτήσεις.

Εδώ ζουν οι κανόνες του μαγαζιού:
  • Η σύγκριση με πέρσι γίνεται στα 364 ημερολογιακά (= ίδια μέρα εβδομάδας).
  • Η εβδομάδα ξεκινά Δευτέρα.
  • Η επιταγή πληρώνει τις πωλήσεις των 7 ημερών πριν από αυτήν.
  • «Καθαρό» παραστατικών = τιμολόγια − πιστωτικά.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from core.config import (
    YOY_OFFSET_DAYS, CHECK_PERIOD_DAYS, CHECK_MATCH_TOLERANCE,
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

    cur = sales_between(df, start, end) or 0.0
    prev = sales_between(df, ly_start, ly_end)

    label = day_name(start, short=True) if elapsed == 0 else \
        f"{day_name(start, short=True)}–{day_name(end, short=True)}"

    return {
        "current": cur,
        "previous": prev,
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
    mask = (df["date"] >= pd.Timestamp(start)) & \
           (df["date"] <= pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59))
    return df.loc[mask]


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
def check_period(check_date: date) -> tuple[date, date]:
    """
    Ποιες πωλήσεις καλύπτει μια επιταγή.
    Οι 7 ημέρες ΠΡΙΝ την ημερομηνία της (χωρίς την ίδια).
    """
    return check_date - timedelta(days=CHECK_PERIOD_DAYS), check_date - timedelta(days=1)


def check_falls_in_week(check_date: date, week_start: date) -> bool:
    """
    Η επιταγή «πέφτει» στην εβδομάδα ΠΡΙΝ την ημερομηνία της —
    τότε πρέπει να την έχεις υπόψη σου.
    """
    payment_week, _ = week_range(check_date - timedelta(days=7))
    return week_start == payment_week


def next_check(df: pd.DataFrame, today: date) -> pd.Series | None:
    """Η αμέσως επόμενη επιταγή."""
    if df.empty:
        return None
    future = df[df["check_date"] >= pd.Timestamp(today)].sort_values("check_date")
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

    future = df[df["check_date"] >= pd.Timestamp(today)].sort_values("check_date")

    out = []
    for _, r in future.iterrows():
        cd = r["check_date"]
        out.append({
            "date": cd.date() if hasattr(cd, "date") else cd,
            "amount": float(r["amount"]),
            "period": str(r.get("period", "") or ""),
        })
    return out


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
    cash = max(0.0, float(cash or 0))

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


def month_rows(df_t: pd.DataFrame, df_s: pd.DataFrame, year: int, month: int | None) -> list[dict]:
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

    rows = []
    for _, r in sub.iterrows():
        cd = r["check_date"]
        cd = cd.date() if hasattr(cd, "date") else cd

        amount = float(r["amount"])
        expenses = _to_float(r.get("expenses", ""))

        p_start, p_end = check_period(cd)
        period_sales = sales_between(df_s, p_start, p_end)

        ly_cd = last_year(cd)
        ly_start, ly_end = check_period(ly_cd)

        rows.append({
            "_row":        int(r["_row"]) if pd.notna(r.get("_row")) else None,
            "check_date":  cd,
            "period":      str(r.get("period", "") or ""),
            "amount":      amount,
            "sales":       period_sales,
            "expenses":    expenses,
            "expenses_raw": str(r.get("expenses", "") or ""),
            "check_number": str(r.get("check_number", "") or ""),
            "ly_amount":   match_last_year_check(df_t, cd),
            "ly_sales":    sales_between(df_s, ly_start, ly_end),
            "balance":     (period_sales - amount - expenses) if period_sales is not None else None,
        })

    return rows


def _to_float(v) -> float:
    if not v:
        return 0.0
    try:
        return float(str(v).replace("€", "").replace(",", ".").strip())
    except ValueError:
        return 0.0
