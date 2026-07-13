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

    Η αναφορά βγαίνει μετά τις 21:00. Πριν από αυτό, δεν έχει νόημα να
    συνδεθούμε στο Gmail — και σίγουρα δεν έχει νόημα να κάνουμε OCR.

    Το παράθυρο κλείνει στις 06:00, ώστε να πιάσουμε και αναφορές που έρχονται
    μετά τα μεσάνυχτα.
    """
    now = now or now_greece()
    h = now.hour

    if h >= SALES_REPORT_HOUR:
        return True, f"{h:02d}:{now.minute:02d} — παράθυρο ανοιχτό"

    if h < 6:
        return True, f"{h:02d}:{now.minute:02d} — παράθυρο ανοιχτό (μετά τα μεσάνυχτα)"

    return False, (
        f"{h:02d}:{now.minute:02d} ώρα Ελλάδας — πολύ νωρίς. "
        f"Η αναφορά βγαίνει μετά τις {SALES_REPORT_HOUR}:00."
    )


# ══════════════════════════════════════════════════════════════════════════════
# ΗΜΕΡΟΜΗΝΙΕΣ
# ══════════════════════════════════════════════════════════════════════════════
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
    Η εβδομάδα ΩΣ ΤΩΡΑ (Δευτέρα → σήμερα) vs οι αντίστοιχες μέρες πέρσι.

    Συγκρίνουμε Δευ–Τετ με Δευ–Τετ πέρσι, όχι Δευ–Τετ με ολόκληρη εβδομάδα.
    Αλλιώς κάθε Δευτέρα θα φαινόμασταν 85% κάτω.
    """
    start, _ = week_range(today)
    elapsed = (today - start).days

    ly_start = last_year(start)
    ly_end = ly_start + timedelta(days=elapsed)

    cur = sales_between(df, start, today) or 0.0
    prev = sales_between(df, ly_start, ly_end)

    label = day_name(start, short=True) if elapsed == 0 else \
        f"{day_name(start, short=True)}–{day_name(today, short=True)}"

    return {
        "current": cur,
        "previous": prev,
        "pct": pct_change(cur, prev),
        "days_elapsed": elapsed + 1,
        "label": label,
        "start": start,
        "end": today,
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
