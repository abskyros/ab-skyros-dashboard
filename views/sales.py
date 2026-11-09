"""
views/sales.py — Πωλήσεις.

Δύο όψεις:
  • Περίοδος — ένα διάστημα πωλήσεων κάθε φορά, με τις μέρες του
  • Ετήσια   — ανά μήνα (και ανά διάστημα), με λήψη CSV

ΔΙΑΣΤΗΜΑ = οι πωλήσεις που ΠΛΗΡΩΝΟΥΝ την επόμενη επιταγή (core.metrics.sales_window):
εβδομάδα Δευ–Κυρ ως 06/12/2026 (επιταγή τη Δευτέρα), 07–14/12/2026 (επιταγή 15/12),
και μετά 25→04 / 05→14 / 15→24 (επιταγές 5/15/25). Έτσι φαίνεται αν «βγήκε» η επιταγή.
(Τα Παραστατικά μένουν στις περιόδους ΑΓΟΡΩΝ — άλλο πράγμα.)

Δείχνει ΠΑΝΤΑ όλο το διάστημα — και μελλοντικό: οι μέρες χωρίς φετινά δείχνουν
πέρσι/πρόπερσι.
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.config import SHEET_SALES
from core.metrics import (
    sales_window_from, sales_window_kind, neighbor_periods, month_periods,
    last_year, two_years_ago, day_name, as_dates,
    sales_row, monthly_breakdown,
    find_anomalies, month_name, YOY_OFFSET_DAYS,
)
from core.sheets import check_quality, delete_row
from ui import components as c


def render(df: pd.DataFrame, today: date, df_t: pd.DataFrame | None = None) -> None:
    if df.empty:
        c.empty(
            "Δεν υπάρχουν πωλήσεις ακόμη",
            "Οι πωλήσεις έρχονται αυτόματα κάθε βράδυ. Για άμεση ενημέρωση, πάτα «Ενημέρωση» πάνω δεξιά."
        )
        return

    # Ο φύλακας: ύποπτες μέρες ΠΑΝΩ απ' όλα — αν κάτι διαβάστηκε λάθος,
    # πρέπει να το δεις πριν εμπιστευτείς τα νούμερα της σελίδας.
    _anomalies(df, today)

    period, yearly = st.tabs(["Περίοδος", "Ετήσια"])

    with period:
        _period(df, today, df_t)

    with yearly:
        _yearly(df, today, df_t)

    # Τα εργαλεία διόρθωσης ΚΑΤΩ — τα χρειάζεσαι σπάνια, τα δεδομένα συνέχεια.
    _tools(df, today)


# ══════════════════════════════════════════════════════════════════════════════
# ΑΞΙΟΠΙΣΤΙΑ ΔΕΔΟΜΕΝΩΝ
# ══════════════════════════════════════════════════════════════════════════════
def _anomalies(df: pd.DataFrame, today: date) -> None:
    """
    Αυτόματος έλεγχος κάθε φόρτωσης. Μια μέρα είναι ύποπτη όταν ξεφεύγει
    πολύ από τον τύπο της (Δευτέρα με Δευτέρες) — σημάδι λάθους OCR.
    Δεν διορθώνει τίποτα μόνο του· δείχνει ΠΟΙΑ μέρα να ανοίξεις στη Διόρθωση.
    """
    flagged = find_anomalies(df, today)
    if not flagged:
        return

    c.note(
        f"<b>{len(flagged)} {'ημέρα χρειάζεται' if len(flagged) == 1 else 'ημέρες χρειάζονται'} έλεγχο</b> — "
        f"οι αριθμοί τους αποκλίνουν πολύ από το συνηθισμένο. "
        f"Διόρθωσέ τις στο «Ενημέρωση» πάνω δεξιά → «✏️ Χειροκίνητη καταχώρηση».",
        "warn",
    )

    for a in flagged:
        d = a["date"]
        net = c.eur(a["net_sales"]) if a["net_sales"] is not None else "—"
        base = c.eur(a["baseline"]) if a["baseline"] else "—"
        why = " · ".join(a["reasons"])
        c.html(
            f'<div class="flag-row">'
            f'<div class="flag-date">{day_name(d, short=True)} {d:%d/%m/%Y}</div>'
            f'<div class="flag-nums">{net} <span class="flag-vs">αντί για ~{base}</span></div>'
            f'<div class="flag-why">{why}</div>'
            f'</div>'
        )


# ══════════════════════════════════════════════════════════════════════════════
def _period(df: pd.DataFrame, today: date, df_t: pd.DataFrame | None = None) -> None:
    """
    ΟΛΟ το διάστημα πωλήσεων της μέρας που διάλεξες — οι μέρες που πληρώνουν
    την ίδια επιταγή (εβδομάδα ως 06/12/2026, μετά δεκαήμερο 25→04/05→14/15→24).

    Κάθε μέρα δείχνει φέτος (αν υπάρχει), πέρσι και πρόπερσι. Έτσι βλέπεις και
    τι ΕΡΧΕΤΑΙ: «τι έκανε πέρσι αυτή η περίοδος, μέρα-μέρα;»

    Οι κάρτες:
      • Με φετινά στοιχεία → φέτος vs τις ΙΔΙΕΣ μέρες πέρσι (ίδια λογική με
        period_to_date), + «όλη η περίοδος πέρσι» στην υποσημείωση.
      • Χωρίς φετινά (π.χ. μελλοντική) → τα περσινά σύνολα όλης της περιόδου,
        σε σύγκριση με πρόπερσι.
    """
    col, _ = st.columns([1, 2])
    with col:
        picked = st.date_input("Ημέρα", today, key="sales_day", format="DD/MM/YYYY")
    window = sales_window_from(df_t)        # οι μέρες από τις επιταγές του Excel
    c.period_calendar(*neighbor_periods(picked, window))

    start, end, check_day = window(picked)
    rows = [
        {
            "d": d,
            "now": sales_row(df, d),
            "ly": sales_row(df, last_year(d)),
            "ly2": sales_row(df, two_years_ago(d)),
        }
        for d in (start + timedelta(days=i) for i in range((end - start).days + 1))
    ]
    with_now = [r for r in rows if r["now"]]

    if with_now:
        # Πέρσι = ΙΔΙΕΣ μέρες με φέτος: κόβουμε στην τελευταία μέρα που έχει
        # πραγματικά δεδομένα φέτος, όχι στην Κυριακή.
        last_now = max(r["d"] for r in with_now)
        same = [r for r in rows if r["d"] <= last_now]

        full_ly = _sum(rows, "ly", "net_sales")
        whole = "Όλη η εβδομάδα" if sales_window_kind(start, end) == "Εβδομάδα" else "Όλο το δεκαήμερο"
        foot = f"{whole} πέρσι: {c.eur(full_ly)}" if full_ly is not None else ""

        c.grid(
            c.scale("Καθαρές πωλήσεις", _sum(with_now, "now", "net_sales"),
                    _sum(same, "ly", "net_sales"), foot=foot),
            c.scale("Πελάτες", _sum(with_now, "now", "customers"),
                    _sum(same, "ly", "customers"), fmt=c.num),
            c.scale("Μέσο καλάθι", _avg(with_now, "now", "avg_basket"),
                    _avg(same, "ly", "avg_basket")),
            cols=3,
        )
    else:
        why = ("δεν έχει έρθει ακόμη" if start > today
               else "δεν έχει φετινές πωλήσεις")
        c.note(
            f"Η περίοδος <b>{start:%d/%m} — {end:%d/%m/%Y}</b> {why}. "
            f"Παρακάτω βλέπεις <b>πέρσι</b> και <b>πρόπερσι</b>, μέρα-μέρα.",
            "info",
        )
        c.grid(
            c.scale("Καθαρές πωλήσεις · πέρσι", _sum(rows, "ly", "net_sales"),
                    _sum(rows, "ly2", "net_sales"), now_tag="Πέρσι", then_tag="Πρόπερσι"),
            c.scale("Πελάτες · πέρσι", _sum(rows, "ly", "customers"),
                    _sum(rows, "ly2", "customers"), fmt=c.num,
                    now_tag="Πέρσι", then_tag="Πρόπερσι"),
            c.scale("Μέσο καλάθι · πέρσι", _avg(rows, "ly", "avg_basket"),
                    _avg(rows, "ly2", "avg_basket"), now_tag="Πέρσι", then_tag="Πρόπερσι"),
            cols=3,
        )

    _check_card(rows, check_day, df_t)

    c.section(f"{sales_window_kind(start, end)} · {start:%d/%m} — {end:%d/%m/%Y}"
              f" · πληρώνει την επιταγή {check_day:%d/%m}")
    has_prop = any(r["ly2"] for r in rows)
    c.html(_table_html(rows, has_prop, picked))


def _check_card(rows: list, check_day: date, df_t: pd.DataFrame | None) -> None:
    """
    Η ΕΠΙΤΑΓΗ που πληρώνει αυτό το διάστημα: την καλύψαμε;

    Πωλήσεις ως τώρα (φέτος) απέναντι στο ποσό της επιταγής, με μπάρα κάλυψης.
    Και πού «θα κλείσει» το διάστημα αν οι υπόλοιπες μέρες πάνε όπως πέρσι.
    """
    amount = None
    if df_t is not None and not df_t.empty:
        hit = df_t[as_dates(df_t["check_date"]) == check_day]
        if not hit.empty:
            amount = float(hit["amount"].sum())

    now = _sum(rows, "now", "net_sales") or 0.0
    rest = sum(r["ly"]["net_sales"] for r in rows
               if not r["now"] and r["ly"] and r["ly"].get("net_sales") is not None)
    done = all(r["now"] for r in rows)
    expected = now + rest

    if not amount:
        c.note(f"Αυτό το διάστημα πληρώνει την επιταγή <b>{day_name(check_day)} "
               f"{check_day:%d/%m/%Y}</b> — δεν έχει έρθει ακόμη η τιμολόγησή της. "
               f"Πωλήσεις ως τώρα: <b>{c.eur(now)}</b>"
               + ("" if done else f" · με πέρσι για τις υπόλοιπες μέρες: <b>{c.eur(expected)}</b>"),
               "info")
        return

    diff = now - amount
    state = (f"καλύφθηκε — περισσεύουν {c.eur(diff)}" if diff >= 0
             else f"λείπουν {c.eur(-diff)}")
    foot = f"Πωλήσεις ως τώρα {c.eur(now)} · {state}"
    if not done:
        e_diff = expected - amount
        foot += (f" · με πέρσι για τις υπόλοιπες μέρες κλείνει {c.eur(expected)} "
                 f"({'+' if e_diff >= 0 else '−'}{c.eur(abs(e_diff))})")
    c.html(c.kpi(f"Επιταγή {day_name(check_day, short=True)} {check_day:%d/%m}", amount,
                 badge=f"Κάλυψη {now / amount * 100:.0f}%",
                 progress=min(now / amount, 1.0),
                 foot=foot, accent=True))
    c.spacer(0.4)


def _sum(rows: list, year: str, key: str) -> float | None:
    """Άθροισμα ενός μέτρου (π.χ. net_sales) για μια χρονιά (now/ly/ly2)· None αν δεν υπάρχει τίποτα."""
    vals = [r[year][key] for r in rows if r[year] and r[year].get(key) is not None]
    return float(sum(vals)) if vals else None


def _avg(rows: list, year: str, key: str) -> float | None:
    """Μέσος όρος ενός μέτρου για μια χρονιά· None αν δεν υπάρχει τίποτα."""
    vals = [r[year][key] for r in rows if r[year] and r[year].get(key) is not None]
    return float(sum(vals) / len(vals)) if vals else None


# ══════════════════════════════════════════════════════════════════════════════
def _yearly(df: pd.DataFrame, today: date, df_t: pd.DataFrame | None = None) -> None:
    years = sorted({d.year for d in as_dates(df["date"])}, reverse=True)

    col, _ = st.columns([1, 2])
    with col:
        year = st.selectbox("Έτος", years, key="sales_year")

    cur = df[df["date"].dt.year == year]
    prev = df[df["date"].dt.year == year - 1]

    if cur.empty:
        c.empty(f"Καμία εγγραφή για το {year}")
        return

    total = float(cur["net_sales"].sum())
    prev_total = float(prev["net_sales"].sum()) if not prev.empty else None
    cust = float(cur["customers"].sum()) if cur["customers"].notna().any() else None
    prev_cust = float(prev["customers"].sum()) if not prev.empty and prev["customers"].notna().any() else None

    c.grid(
        c.scale("Σύνολο έτους", total, prev_total, then_tag=str(year - 1)),
        c.stat("Ημερήσιος μέσος όρος", float(cur["net_sales"].mean()),
               accent="var(--brand)", foot=f"{len(cur)} ημέρες με δεδομένα"),
        c.scale("Πελάτες", cust, prev_cust, fmt=c.num, then_tag=str(year - 1)),
        cols=3,
    )

    c.section("Ανά μήνα")
    c.year_months(*_by_month(df, year, today, df_t))

    _download(cur, year)


def _by_month(df: pd.DataFrame, year: int, today: date,
              df_t: pd.DataFrame | None = None) -> tuple[list, list]:
    """
    Οι 12 μήνες, με το έτος που διάλεξες και τα δύο προηγούμενα, και κάτω από
    κάθε μήνα τα διαστήματα πωλήσεων ανά επιταγή (εβδομάδες ως 06/12/2026, μετά
    25→04 / 05→14 / 15→24). Χρονιές χωρίς κανένα στοιχείο δεν εμφανίζονται.

    Στις προηγούμενες χρονιές η περίοδος είναι οι ίδιες μέρες με μετατόπιση
    364/728 ημερών (ο κανόνας της εφαρμογής): Δευτέρα με Δευτέρα.

    Η «καλύτερη περίοδος» μετράει μόνο τελειωμένες — μια που τρέχει ακόμα δεν
    έχει όλες τις μέρες της.

    → (χρονιές, μήνες)
    """
    have = {d.year for d in as_dates(df["date"])}
    years = [y for y in (year, year - 1, year - 2) if y in have]

    # Λεξικό μέρα → πωλήσεις: 12 μήνες × 3-5 περίοδοι × 3 χρονιές θα ήταν εκατοντάδες
    # φιλτραρίσματα του πίνακα σε κάθε φόρτωση της σελίδας.
    daily = dict(zip(as_dates(df["date"]), df["net_sales"].astype(float)))
    totals = {y: {m["month"]: m for m in monthly_breakdown(df, y)} for y in years}

    def period_sum(start: date, end: date, back: int) -> float | None:
        days = (start + timedelta(days=i - back * YOY_OFFSET_DAYS)
                for i in range((end - start).days + 1))
        vals = [daily[d] for d in days if d in daily]
        return float(sum(vals)) if vals else None

    window = sales_window_from(df_t)        # οι μέρες από τις επιταγές του Excel
    months = []
    for m in range(1, 13):
        weeks = [
            {
                "label": f"{sales_window_kind(s, e)} · {s:%d/%m}–{e:%d/%m}",
                "vals": [period_sum(s, e, year - y) for y in years],
                "running": s <= today <= e,
            }
            for s, e in month_periods(year, m, window)
        ]

        # Η καλύτερη περίοδος κάθε χρονιάς (δείκτης γραμμής ανά στήλη).
        best = []
        for col, y in enumerate(years):
            done = [(w["vals"][col], i) for i, w in enumerate(weeks)
                    if w["vals"][col] is not None and not (w["running"] and y == year)]
            best.append(max(done)[1] if done else None)

        cur = totals[years[0]].get(m)
        months.append({
            "name": month_name(m),
            "running": year == today.year and m == today.month,
            "vals": [(totals[y].get(m) or {}).get("total") for y in years],
            "meta": (f"{cur['days']} ημέρες · {c.num(cur['customers'])} πελάτες · "
                     f"ΜΟ {c.eur(cur['avg_day'])}/ημέρα") if cur else "",
            "weeks": weeks,
            "best": best,
        })
    return years, months


def _download(df: pd.DataFrame, year: int) -> None:
    out = df.copy().sort_values("date")
    out["date"] = out["date"].dt.strftime("%d/%m/%Y")
    out = out.rename(columns={
        "date": "ΗΜΕΡΟΜΗΝΙΑ",
        "net_sales": "ΠΩΛΗΣΕΙΣ",
        "customers": "ΠΕΛΑΤΕΣ",
        "avg_basket": "ΜΟ ΚΑΛΑΘΙΟΥ",
    })

    c.spacer(0.6)
    st.download_button(
        f"Λήψη CSV — {year}",
        out.to_csv(index=False).encode("utf-8-sig"),
        f"ab_skyros_polhseis_{year}.csv",
        "text/csv",
        key="sales_csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
def _cell(val, fmt, cls: str) -> str:
    """Ένα κελί τιμής, με την κλάση της χρονιάς (now/then/then2)."""
    return f'<td class="v {cls}">{fmt(val)}</td>'


def _table_html(rows: list, has_prop: bool, picked: date) -> str:
    """
    Ο αναλυτικός πίνακας της περιόδου — ΤΡΙΑ χρόνια δίπλα-δίπλα, μέρα-μέρα.

    Για κάθε μέρα: πωλήσεις / πελάτες / καλάθι, φέτος · πέρσι · πρόπερσι.
    Μέρες χωρίς φετινά: «—» στο φέτος και αχνή ημερομηνία (.noyr). Η μέρα που
    διάλεξες ξεχωρίζει (.picked). Η στήλη «Πρόπερσι» μόνο αν υπάρχει έστω μία
    μέρα με δεδομένα δύο χρόνια πίσω.

    ΠΟΤΕ pandas Styler — χτίζει τεράστιο HTML στη μνήμη και ρίχνει το cloud.
    Καθαρό string, με δική του CSS, που κάνει και σκρολ δεξιά στο κινητό.
    """
    # Πόσες υπο-στήλες ανά μέτρο: 2 (φέτος+πέρσι) ή 3 (+πρόπερσι).
    span = 3 if has_prop else 2

    # ── ΚΕΦΑΛΙΔΑ: δύο σειρές ──
    # 1η: ομάδες (ΠΩΛΗΣΕΙΣ / ΠΕΛΑΤΕΣ / ΚΑΛΑΘΙ)
    # 2η: χρονιές (Φέτος / Πέρσι / Πρόπερσι) κάτω από κάθε ομάδα
    head1 = (
        '<tr class="grp">'
        '<th class="day" rowspan="2">Ημέρα</th>'
        f'<th colspan="{span}">Πωλήσεις</th>'
        f'<th colspan="{span}">Πελάτες</th>'
        f'<th colspan="{span}">Καλάθι</th>'
        '</tr>'
    )

    def yrs() -> str:
        cells = '<th class="now">Φέτος</th><th class="then">Πέρσι</th>'
        if has_prop:
            cells += '<th class="then2">Πρόπερσι</th>'
        return cells

    head2 = f'<tr class="yrs">{yrs()}{yrs()}{yrs()}</tr>'

    # ── ΣΩΜΑ ──
    body = []
    for row in rows:
        d = row["d"]
        now, ly, ly2 = row["now"] or {}, row["ly"], row["ly2"]

        tds = [
            f'<td class="day"><b>{day_name(d, short=True)}</b>'
            f'<span class="dt">{d:%d/%m/%y}</span></td>'
        ]

        # Πωλήσεις
        tds.append(_cell(now.get("net_sales"), c.eur, "now"))
        tds.append(_cell(ly["net_sales"] if ly else None, c.eur, "then"))
        if has_prop:
            tds.append(_cell(ly2["net_sales"] if ly2 else None, c.eur, "then2"))

        # Πελάτες
        tds.append(_cell(now.get("customers"), c.num, "now"))
        tds.append(_cell(ly["customers"] if ly else None, c.num, "then"))
        if has_prop:
            tds.append(_cell(ly2["customers"] if ly2 else None, c.num, "then2"))

        # Καλάθι
        tds.append(_cell(now.get("avg_basket"), c.eur, "now"))
        tds.append(_cell(ly["avg_basket"] if ly else None, c.eur, "then"))
        if has_prop:
            tds.append(_cell(ly2["avg_basket"] if ly2 else None, c.eur, "then2"))

        cls = " ".join(k for k, on in (("noyr", not now), ("picked", d == picked)) if on)
        body.append(f'<tr class="{cls}">{"".join(tds)}</tr>')

    # ── ΣΥΝΟΛΟ (με έντονα): όλο το διάστημα, ανά χρονιά ──
    # Καλάθι συνόλου = πωλήσεις / πελάτες (όχι μέσος όρος των καλαθιών).
    def tot(year: str, key: str):
        return _sum(rows, year, key)

    def basket(year: str):
        n, k = tot(year, "net_sales"), tot(year, "customers")
        return (n / k) if n and k else None

    years = ["now", "ly"] + (["ly2"] if has_prop else [])
    cls = {"now": "now", "ly": "then", "ly2": "then2"}
    foot = ['<td class="day"><b>Σύνολο</b></td>']
    foot += [f'<td class="v {cls[y]}"><b>{c.eur(tot(y, "net_sales"))}</b></td>' for y in years]
    foot += [f'<td class="v {cls[y]}"><b>{c.num(tot(y, "customers"))}</b></td>' for y in years]
    foot += [f'<td class="v {cls[y]}"><b>{c.eur(basket(y))}</b></td>' for y in years]

    return (
        '<div class="tbl3-wrap">'
        '<table class="tbl3">'
        f'<thead>{head1}{head2}</thead>'
        f'<tbody>{"".join(body)}</tbody>'
        f'<tfoot><tr class="total" style="border-top:2px solid currentColor">{"".join(foot)}</tr></tfoot>'
        '</table>'
        '</div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# ΕΡΓΑΛΕΙΑ
# ══════════════════════════════════════════════════════════════════════════════
def _tools(df: pd.DataFrame, today: date) -> None:
    # Η Προσθήκη/Διόρθωση ημέρας ζει πλέον στο «Ενημέρωση → ✏️ Χειροκίνητη
    # καταχώρηση» (views/manual.py), μαζί με παραστατικά και τιμολογήσεις.
    with st.expander("Έλεγχος (διπλά · μέρες που λείπουν)"):
        st.caption("Για προσθήκη ή διόρθωση ημέρας: «Ενημέρωση» πάνω δεξιά → "
                   "«✏️ Χειροκίνητη καταχώρηση».")
        _check()


def _check() -> None:
    st.caption("Ψάχνει διπλές εγγραφές και μέρες που λείπουν.")

    if st.button("Έλεγχος τώρα", key="sales_check", width='stretch'):
        st.session_state["sales_checked"] = True

    if not st.session_state.get("sales_checked"):
        return

    with st.spinner("Έλεγχος…"):
        result = check_quality(SHEET_SALES)

    dups, gaps = result["duplicates"], result["gaps"]

    if not dups and not gaps:
        c.note("Καθαρά. Καμία διπλή εγγραφή, καμία μέρα δεν λείπει.", "ok")
        return

    if dups:
        c.note(f"{len(dups)} ημερομηνίες έχουν καταχωρηθεί πάνω από μία φορά.", "warn")
        for d in dups:
            st.markdown(f"**{d['date']}**")
            for e in d["entries"][1:]:  # η πρώτη μένει
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"Γραμμή {e['row']} — {c.eur(e['value'])}")
                with col2:
                    if st.button("Διαγραφή", key=f"del_s_{e['row']}", width='stretch'):
                        ok, msg = delete_row(SHEET_SALES, e["row"])
                        c.note(msg, "ok" if ok else "bad")
                        if ok:
                            st.rerun()

    if gaps:
        shown = ", ".join(gaps[:15])
        more = f" και άλλες {len(gaps) - 15}" if len(gaps) > 15 else ""
        c.note(f"Λείπουν {len(gaps)} μέρες: {shown}{more}", "bad")

