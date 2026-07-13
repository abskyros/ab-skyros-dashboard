"""
views/timologiseis.py — Τιμολογήσεις (επιταγές).

Η βασική οθόνη είναι ανά έτος: πόσα πλήρωσες σε επιταγές και πόσα πούλησες την
ίδια χρονιά, δίπλα-δίπλα. Πατάς ένα έτος και ανοίγει η λίστα με τις επιταγές του.

Το drill-down περνάει από το URL (?ty=2026) και όχι από session_state, ώστε ο
σύνδεσμος να μοιράζεται και να δουλεύει το back του browser.
"""

from datetime import date

import pandas as pd
import streamlit as st

from core.config import SHEET_TIMOL
from core.metrics import as_dates, next_check
from core.sheets import check_quality, delete_row
from ui import components as c


def render(df_t: pd.DataFrame, df_s: pd.DataFrame, today: date, open_year: str | None) -> None:
    c.title("Τιμολογήσεις", "Πληρωμές με επιταγή")

    if df_t.empty:
        c.empty(
            "Δεν υπάρχουν τιμολογήσεις ακόμη",
            "Οι τιμολογήσεις έρχονται αυτόματα κάθε 2 ώρες."
        )
        return

    _next(df_t, today)
    _by_year(df_t, df_s, open_year)
    _tools()


# ══════════════════════════════════════════════════════════════════════════════
def _next(df: pd.DataFrame, today: date) -> None:
    nxt = next_check(df, today)
    if nxt is None:
        return

    cd = nxt["check_date"]
    cd = cd.date() if hasattr(cd, "date") else cd

    days = (cd - today).days
    tag = "Πληρώνεται σήμερα" if days == 0 else (
        "Επόμενη επιταγή — αύριο" if days == 1 else f"Επόμενη επιταγή — σε {days} ημέρες"
    )

    c.check_card(cd, float(nxt["amount"]), str(nxt.get("period", "")), tag=tag)


# ══════════════════════════════════════════════════════════════════════════════
def _by_year(df_t: pd.DataFrame, df_s: pd.DataFrame, open_year: str | None) -> None:
    t = df_t.copy()
    t["year"] = t["check_date"].dt.year

    by_year = (
        t.groupby("year")
        .agg(total=("amount", "sum"), count=("amount", "size"))
        .reset_index()
        .sort_values("year", ascending=False)
    )

    sales_by_year = {}
    if not df_s.empty:
        s = df_s.copy()
        s["year"] = s["date"].dt.year
        sales_by_year = s.groupby("year")["net_sales"].sum().to_dict()

    c.section("Ανά έτος")
    c.html(
        '<div style="display:flex;justify-content:flex-end;gap:.6rem;margin-bottom:.5rem;'
        'font-size:.64rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--dim)">'
        '<span style="min-width:120px;text-align:center">Επιταγές</span>'
        '<span style="min-width:120px;text-align:center">Πωλήσεις</span>'
        '</div>'
    )

    for _, r in by_year.iterrows():
        year = int(r["year"])
        is_open = str(year) == str(open_year)

        href = c.link("Τιμολογήσεις") if is_open else c.link("Τιμολογήσεις", ty=year)

        c.html(c.year_row(
            year,
            float(r["total"]),
            sales_by_year.get(year),
            int(r["count"]),
            href=href,
            open_=is_open,
        ))

        if is_open:
            _drill(t[t["year"] == year])


def _drill(year_df: pd.DataFrame) -> None:
    """Οι επιταγές μιας χρονιάς, νεότερη πρώτα."""
    rows = [
        (
            f"{(cd.date() if hasattr(cd, 'date') else cd):%d/%m/%Y}",
            str(r.get("period", "") or ""),
            float(r["amount"]),
        )
        for cd, r in (
            (row["check_date"], row)
            for _, row in year_df.sort_values("check_date", ascending=False).iterrows()
        )
    ]

    c.sub_list(("Ημ. επιταγής", "Περίοδος", "Ποσό"), rows)


# ══════════════════════════════════════════════════════════════════════════════
def _tools() -> None:
    c.spacer(0.8)

    with st.expander("Έλεγχος δεδομένων"):
        st.caption("Ψάχνει διπλές ημερομηνίες επιταγής και εβδομάδες που λείπουν.")

        if st.button("Έλεγχος τώρα", key="timol_check", width='stretch'):
            st.session_state["timol_checked"] = True

        if not st.session_state.get("timol_checked"):
            return

        with st.spinner("Έλεγχος…"):
            result = check_quality(SHEET_TIMOL)

        dups, gaps = result["duplicates"], result["gaps"]

        if not dups and not gaps:
            c.note("Καθαρά. Καμία διπλή επιταγή, καμία εβδομάδα δεν λείπει.", "ok")
            return

        if dups:
            c.note(f"{len(dups)} ημερομηνίες επιταγής υπάρχουν πάνω από μία φορά. Κράτα μία.", "warn")
            for d in dups:
                st.markdown(f"**{d['date']}**")
                for e in d["entries"]:
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"Γραμμή {e['row']} — {c.eur(e['value'])}")
                    with col2:
                        if st.button("Διαγραφή", key=f"del_t_{e['row']}", width='stretch'):
                            ok, msg = delete_row(SHEET_TIMOL, e["row"])
                            c.note(msg, "ok" if ok else "bad")
                            if ok:
                                st.rerun()

        if gaps:
            lines = "<br>".join(
                f"Μεταξύ <b>{g['after']}</b> και <b>{g['before']}</b> — "
                f"{g['gap_days']} ημέρες, περίπου {g['approx_missing']} εβδομάδες λείπουν"
                for g in gaps[:12]
            )
            c.note(f"Πιθανά κενά:<br><br>{lines}", "bad")
