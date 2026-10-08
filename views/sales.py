"""
views/sales.py — Πωλήσεις.

Δύο όψεις:
  • Εβδομαδιαία — μια εβδομάδα κάθε φορά, με τις μέρες της
  • Ετήσια      — ανά μήνα, με λήψη CSV

Οι μελλοντικές μέρες δείχνουν τα ΠΕΡΣΙΝΑ στοιχεία της ίδιας μέρας. Χρήσιμο για
προγραμματισμό βάρδιας: «τι έκανε πέρσι το Σάββατο πριν το Πάσχα;»
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.config import SHEET_SALES
from core.metrics import (
    week_range, last_year, two_years_ago, day_name, as_dates,
    sales_on, sales_row, monthly_breakdown, weekly_series,
    find_anomalies,
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
            "Οι πωλήσεις έρχονται αυτόματα κάθε βράδυ. Για άμεση ενημέρωση, δες το κάτω μέρος της σελίδας."
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
    col, _ = st.columns([1, 2])
    with col:
        picked = st.date_input("Ημέρα", today, key="sales_day", format="DD/MM/YYYY")

    if picked > today:
        _future(df, picked)
        return

    start, end = week_range(picked)
    dts = as_dates(df["date"])

    week = df[(dts >= start) & (dts <= end)].sort_values("date")
    ly_start, ly_end = last_year(start), last_year(end)
    ly_week = df[(dts >= ly_start) & (dts <= ly_end)]

    if week.empty:
        c.empty(
            f"Καμία πώληση από {start:%d/%m} έως {end:%d/%m}",
            "Αν η εβδομάδα έχει περάσει, τρέξε τον έλεγχο δεδομένων παραπάνω."
        )
        return

    now_total = float(week["net_sales"].sum())
    now_cust = float(week["customers"].sum()) if week["customers"].notna().any() else None
    now_basket = float(week["avg_basket"].mean()) if week["avg_basket"].notna().any() else None

    then_total = float(ly_week["net_sales"].sum()) if not ly_week.empty else None
    then_cust = float(ly_week["customers"].sum()) if not ly_week.empty and ly_week["customers"].notna().any() else None
    then_basket = float(ly_week["avg_basket"].mean()) if not ly_week.empty and ly_week["avg_basket"].notna().any() else None

    c.grid(
        c.scale("Καθαρές πωλήσεις", now_total, then_total),
        c.scale("Πελάτες", now_cust, then_cust, fmt=c.num),
        c.scale("Μέσο καλάθι", now_basket, then_basket),
        cols=3,
    )

    c.section(f"Ημέρες · {start:%d/%m} — {end:%d/%m/%Y}")
    _table(df, week)


def _future(df: pd.DataFrame, picked: date) -> None:
    """
    Μελλοντική μέρα → δείχνουμε τι έγινε την ίδια μέρα πέρσι.
    Έτσι ξέρεις πόσο κόσμο να βάλεις.
    """
    ref = last_year(picked)
    ly = sales_row(df, ref)

    c.note(
        f"Η <b>{day_name(picked)} {picked:%d/%m/%Y}</b> δεν έχει έρθει ακόμη. "
        f"Παρακάτω τα στοιχεία της <b>{day_name(ref)} {ref:%d/%m/%Y}</b> — της ίδιας μέρας πέρσι.",
        "info",
    )

    if not ly:
        c.empty("Δεν υπάρχουν περσινά στοιχεία για αυτή τη μέρα")
        return

    c.grid(
        c.stat("Καθαρές πωλήσεις", ly["net_sales"], accent="var(--prev)"),
        c.stat("Πελάτες", ly["customers"], fmt=c.num, accent="var(--prev)"),
        c.stat("Μέσο καλάθι", ly["avg_basket"], accent="var(--prev)"),
        cols=3,
    )


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

    months = monthly_breakdown(df, year)
    prev_months = {m["month"]: m["total"] for m in monthly_breakdown(df, year - 1)}

    if months:
        c.section("Ανά μήνα")
        c.html("".join(
            c.row(
                m["name"],
                m["total"],
                f"{m['days']} ημέρες · {c.num(m['customers'])} πελάτες · ΜΟ {c.eur(m['avg_day'])}/ημέρα",
            )
            for m in months
        ))

    _download(cur, year)


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
def _table(df: pd.DataFrame, week: pd.DataFrame) -> None:
    """
    Ο αναλυτικός πίνακας της εβδομάδας — ΤΡΙΑ χρόνια δίπλα-δίπλα.

    Για κάθε μέρα: πωλήσεις / πελάτες / καλάθι, και για τις τρεις χρονιές
    (φέτος · πέρσι · πρόπερσι), με χρώμα ανά χρονιά ώστε να ξεχωρίζουν:
      • Φέτος    — χρυσό (το κανονικό)
      • Πέρσι    — γκρι
      • Πρόπερσι — ξεθωριασμένο χρυσό

    Η στήλη «Πρόπερσι» εμφανίζεται ΜΟΝΟ αν υπάρχει έστω μία μέρα με δεδομένα
    δύο χρόνια πίσω — αλλιώς δεν γεμίζουμε τον πίνακα με κενά.

    ΠΟΤΕ pandas Styler — χτίζει τεράστιο HTML στη μνήμη και ρίχνει το cloud.
    Φτιάχνουμε δικό μας HTML (ελαφρύ) με δική του CSS, που κάνει και σκρολ
    δεξιά στο κινητό.
    """
    t = week.sort_values("date", ascending=False).copy()

    # Μαζεύουμε φέτος/πέρσι/πρόπερσι για κάθε μέρα.
    rows = []
    has_prop = False
    for _, r in t.iterrows():
        d = r["date"].date() if hasattr(r["date"], "date") else r["date"]
        ly = sales_row(df, last_year(d))
        ly2 = sales_row(df, two_years_ago(d))
        if ly2:
            has_prop = True
        rows.append({
            "d": d,
            "now": {"net": r.get("net_sales"), "cust": r.get("customers"), "bskt": r.get("avg_basket")},
            "ly":  ly,
            "ly2": ly2,
        })

    c.html(_table_html(rows, has_prop))


def _cell(val, fmt, cls: str) -> str:
    """Ένα κελί τιμής, με την κλάση της χρονιάς (now/then/then2)."""
    return f'<td class="v {cls}">{fmt(val)}</td>'


def _table_html(rows: list, has_prop: bool) -> str:
    """Χτίζει το HTML του τρι-ετούς πίνακα. Καθαρό string — κανένα Styler."""
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
        now, ly, ly2 = row["now"], row["ly"], row["ly2"]

        tds = [
            f'<td class="day"><b>{day_name(d, short=True)}</b>'
            f'<span class="dt">{d:%d/%m/%y}</span></td>'
        ]

        # Πωλήσεις
        tds.append(_cell(now["net"], c.eur, "now"))
        tds.append(_cell(ly["net_sales"] if ly else None, c.eur, "then"))
        if has_prop:
            tds.append(_cell(ly2["net_sales"] if ly2 else None, c.eur, "then2"))

        # Πελάτες
        tds.append(_cell(now["cust"], c.num, "now"))
        tds.append(_cell(ly["customers"] if ly else None, c.num, "then"))
        if has_prop:
            tds.append(_cell(ly2["customers"] if ly2 else None, c.num, "then2"))

        # Καλάθι
        tds.append(_cell(now["bskt"], c.eur, "now"))
        tds.append(_cell(ly["avg_basket"] if ly else None, c.eur, "then"))
        if has_prop:
            tds.append(_cell(ly2["avg_basket"] if ly2 else None, c.eur, "then2"))

        body.append(f'<tr>{"".join(tds)}</tr>')

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

