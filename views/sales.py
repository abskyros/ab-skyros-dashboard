"""
views/sales.py — Πωλήσεις.

Δύο όψεις:
  • Εβδομαδιαία — μια εβδομάδα κάθε φορά, με τις μέρες της
  • Ετήσια      — ανά μήνα, με λήψη CSV

Η εβδομαδιαία δείχνει ΠΑΝΤΑ όλη την εβδομάδα (Δευ → Κυρ) — και μελλοντική: οι
μέρες χωρίς φετινά δείχνουν πέρσι/πρόπερσι. Χρήσιμο για προγραμματισμό βάρδιας:
«τι έκανε πέρσι το Σάββατο πριν το Πάσχα;»
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.config import SHEET_SALES
from core.metrics import (
    week_range, last_year, two_years_ago, day_name, as_dates,
    sales_on, sales_row, monthly_breakdown, weekly_series,
    find_anomalies, month_name, month_weeks, YOY_OFFSET_DAYS,
)
from core.sheets import (
    load_sales, merge_sales, update_sales,
    check_quality, delete_row,
)
from ui import components as c


def render(df: pd.DataFrame, today: date) -> None:
    if df.empty:
        c.empty(
            "Δεν υπάρχουν πωλήσεις ακόμη",
            "Οι πωλήσεις έρχονται αυτόματα κάθε βράδυ. Για άμεση ενημέρωση, πάτα «Ενημέρωση» πάνω δεξιά."
        )
        return

    # Ο φύλακας: ύποπτες μέρες ΠΑΝΩ απ' όλα — αν κάτι διαβάστηκε λάθος,
    # πρέπει να το δεις πριν εμπιστευτείς τα νούμερα της σελίδας.
    _anomalies(df, today)

    weekly, yearly = st.tabs(["Εβδομαδιαία", "Ετήσια"])

    with weekly:
        _weekly(df, today)

    with yearly:
        _yearly(df, today)

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
        f"Διόρθωσέ τις κάτω στο «Διόρθωση · Προσθήκη · Έλεγχος».",
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
def _weekly(df: pd.DataFrame, today: date) -> None:
    """
    ΟΛΗ η εβδομάδα (Δευτέρα → Κυριακή) της μέρας που διάλεξες — παλιά,
    τρέχουσα ή μελλοντική.

    Κάθε μέρα δείχνει φέτος (αν υπάρχει), πέρσι και πρόπερσι. Έτσι βλέπεις και
    τι ΕΡΧΕΤΑΙ: «τι έκανε πέρσι αυτή η εβδομάδα, μέρα-μέρα;»

    Οι κάρτες:
      • Με φετινά στοιχεία → φέτος vs τις ΙΔΙΕΣ μέρες πέρσι (ίδια λογική με
        week_to_date), + «όλη η εβδομάδα πέρσι» στην υποσημείωση.
      • Χωρίς φετινά (π.χ. μελλοντική) → τα περσινά σύνολα όλης της εβδομάδας,
        σε σύγκριση με πρόπερσι.
    """
    col, _ = st.columns([1, 2])
    with col:
        picked = st.date_input("Ημέρα", today, key="sales_day", format="DD/MM/YYYY")

    start, end = week_range(picked)
    rows = [
        {
            "d": d,
            "now": sales_row(df, d),
            "ly": sales_row(df, last_year(d)),
            "ly2": sales_row(df, two_years_ago(d)),
        }
        for d in (start + timedelta(days=i) for i in range(7))
    ]
    with_now = [r for r in rows if r["now"]]

    if with_now:
        # Πέρσι = ΙΔΙΕΣ μέρες με φέτος: κόβουμε στην τελευταία μέρα που έχει
        # πραγματικά δεδομένα φέτος, όχι στην Κυριακή.
        last_now = max(r["d"] for r in with_now)
        same = [r for r in rows if r["d"] <= last_now]

        full_ly = _sum(rows, "ly", "net_sales")
        foot = f"Όλη η εβδομάδα πέρσι: {c.eur(full_ly)}" if full_ly is not None else ""

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
            f"Η εβδομάδα <b>{start:%d/%m} — {end:%d/%m/%Y}</b> {why}. "
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

    c.section(f"Ημέρες · {start:%d/%m} — {end:%d/%m/%Y}")
    has_prop = any(r["ly2"] for r in rows)
    c.html(_table_html(rows, has_prop, picked))


def _sum(rows: list, year: str, key: str) -> float | None:
    """Άθροισμα ενός μέτρου (π.χ. net_sales) για μια χρονιά (now/ly/ly2)· None αν δεν υπάρχει τίποτα."""
    vals = [r[year][key] for r in rows if r[year] and r[year].get(key) is not None]
    return float(sum(vals)) if vals else None


def _avg(rows: list, year: str, key: str) -> float | None:
    """Μέσος όρος ενός μέτρου για μια χρονιά· None αν δεν υπάρχει τίποτα."""
    vals = [r[year][key] for r in rows if r[year] and r[year].get(key) is not None]
    return float(sum(vals) / len(vals)) if vals else None


# ══════════════════════════════════════════════════════════════════════════════
def _yearly(df: pd.DataFrame, today: date) -> None:
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
    c.year_months(*_by_month(df, year, today))

    _download(cur, year)


def _by_month(df: pd.DataFrame, year: int, today: date) -> tuple[list, list]:
    """
    Οι 12 μήνες, με το έτος που διάλεξες και τα δύο προηγούμενα, και κάτω από
    κάθε μήνα οι εβδομάδες του. Χρονιές χωρίς κανένα στοιχείο δεν εμφανίζονται.

    Στις προηγούμενες χρονιές η εβδομάδα είναι η ίδια με μετατόπιση 364/728
    ημερών (ο κανόνας της εφαρμογής): Δευτέρα με Δευτέρα.

    Η «καλύτερη εβδομάδα» μετράει μόνο τελειωμένες εβδομάδες — μια που τρέχει
    ακόμα δεν έχει όλες τις μέρες της.

    → (χρονιές, μήνες)
    """
    have = {d.year for d in as_dates(df["date"])}
    years = [y for y in (year, year - 1, year - 2) if y in have]

    # Λεξικό μέρα → πωλήσεις: 12 μήνες × 5 εβδομάδες × 3 χρονιές θα ήταν εκατοντάδες
    # φιλτραρίσματα του πίνακα σε κάθε φόρτωση της σελίδας.
    daily = dict(zip(as_dates(df["date"]), df["net_sales"].astype(float)))
    totals = {y: {m["month"]: m for m in monthly_breakdown(df, y)} for y in years}

    def week_sum(monday: date, back: int) -> float | None:
        days = (monday + timedelta(days=i - back * YOY_OFFSET_DAYS) for i in range(7))
        vals = [daily[d] for d in days if d in daily]
        return float(sum(vals)) if vals else None

    months = []
    for m in range(1, 13):
        weeks = [
            {
                "label": f"{i}η εβδομάδα · {mon:%d/%m}–{sun:%d/%m}",
                "vals": [week_sum(mon, year - y) for y in years],
                "running": mon <= today <= sun,
            }
            for i, (mon, sun) in enumerate(month_weeks(year, m), start=1)
        ]

        # Η καλύτερη εβδομάδα κάθε χρονιάς (δείκτης γραμμής ανά στήλη).
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
    Ο αναλυτικός πίνακας της εβδομάδας — ΤΡΙΑ χρόνια δίπλα-δίπλα, Δευ → Κυρ.

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

    return (
        '<div class="tbl3-wrap">'
        '<table class="tbl3">'
        f'<thead>{head1}{head2}</thead>'
        f'<tbody>{"".join(body)}</tbody>'
        '</table>'
        '</div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# ΕΡΓΑΛΕΙΑ
# ══════════════════════════════════════════════════════════════════════════════
def _tools(df: pd.DataFrame, today: date) -> None:
    with st.expander("Διόρθωση · Προσθήκη · Έλεγχος"):
        fix, add, check = st.tabs(["Διόρθωση", "Προσθήκη", "Έλεγχος"])

        with fix:
            _fix(df, today)
        with add:
            _add(df, today)
        with check:
            _check()


def _fix(df: pd.DataFrame, today: date) -> None:
    st.caption("Άλλαξε τα στοιχεία μιας ημέρας που έχει ήδη καταχωρηθεί.")

    picked = st.date_input("Ημέρα", today, key="fix_day", format="DD/MM/YYYY")
    current = sales_row(df, picked)

    if not current:
        c.note(f"Η {picked:%d/%m/%Y} δεν υπάρχει. Χρησιμοποίησε την «Προσθήκη».", "warn")
        return

    a, b, d = st.columns(3)
    with a:
        net = st.number_input("Πωλήσεις (€)", value=float(current["net_sales"]),
                              step=100.0, format="%.2f", key="fix_net")
    with b:
        cust = st.number_input("Πελάτες", value=int(current["customers"] or 0),
                               step=1, key="fix_cust")
    with d:
        basket = st.number_input("Μέσο καλάθι (€)", value=float(current["avg_basket"] or 0),
                                 step=0.5, format="%.2f", key="fix_basket")

    if st.button("Αποθήκευση", key="fix_save", width='stretch'):
        ok, msg = update_sales(picked, net, cust or None, basket or None)
        c.note(msg, "ok" if ok else "bad")
        if ok:
            st.rerun()


def _add(df: pd.DataFrame, today: date) -> None:
    st.caption("Καταχώρησε μια μέρα με το χέρι, όταν το αυτόματο δεν την έπιασε.")

    picked = st.date_input("Ημέρα", today - timedelta(days=1), key="add_day", format="DD/MM/YYYY")

    if sales_row(df, picked):
        c.note(f"Η {picked:%d/%m/%Y} υπάρχει ήδη. Χρησιμοποίησε τη «Διόρθωση».", "warn")
        return

    a, b, d = st.columns(3)
    with a:
        net = st.number_input("Πωλήσεις (€)", min_value=0.0, step=100.0, format="%.2f", key="add_net")
    with b:
        cust = st.number_input("Πελάτες", min_value=0, step=1, key="add_cust")
    with d:
        auto = (net / cust) if (net and cust) else 0.0
        basket = st.number_input("Μέσο καλάθι (€)", min_value=0.0, value=round(auto, 2),
                                 step=0.5, format="%.2f", key="add_basket")

    if st.button("Καταχώρηση", key="add_save", width='stretch', disabled=not net):
        n = merge_sales([{
            "date": picked,
            "net_sales": net,
            "customers": cust or None,
            "avg_basket": basket or None,
        }])
        if n:
            c.note(f"Η {picked:%d/%m/%Y} καταχωρήθηκε.", "ok")
            st.rerun()
        else:
            c.note("Δεν καταχωρήθηκε — η ημέρα υπάρχει ήδη.", "warn")


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

