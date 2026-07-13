"""
views/invoices.py — Παραστατικά.

Το νούμερο που μετράει είναι το ΚΑΘΑΡΟ: τιμολόγια μείον πιστωτικά.
Τα δύο σκέλη φαίνονται ξεχωριστά, γιατί ένα μεγάλο πιστωτικό είναι από μόνο του
είδηση — δεν πρέπει να κρύβεται μέσα σε ένα άθροισμα.
"""

from datetime import date

import pandas as pd
import streamlit as st

from core.config import SHEET_INV
from core.metrics import (
    week_range, invoice_totals, invoices_in_week, invoices_monthly,
)
from core.sheets import check_quality, delete_row, purge_duplicate_invoices
from ui import components as c
from ui import charts


def render(df: pd.DataFrame, today: date) -> None:
    c.title("Παραστατικά", "Τιμολόγια και πιστωτικά")

    if df.empty:
        c.empty(
            "Δεν υπάρχουν παραστατικά ακόμη",
            "Τα παραστατικά έρχονται αυτόματα κάθε 2 ώρες. Για άμεση ενημέρωση, δες το κάτω μέρος."
        )
        return

    _tools()

    weekly, yearly = st.tabs(["Εβδομαδιαία", "Ετήσια"])

    with weekly:
        _weekly(df, today)

    with yearly:
        _yearly(df, today)


# ══════════════════════════════════════════════════════════════════════════════
def _weekly(df: pd.DataFrame, today: date) -> None:
    col, _ = st.columns([1, 2])
    with col:
        picked = st.date_input("Ημέρα", today, key="inv_day", format="DD/MM/YYYY")

    start, end = week_range(picked)
    week = invoices_in_week(df, picked)

    if week.empty:
        c.empty(f"Κανένα παραστατικό από {start:%d/%m} έως {end:%d/%m/%Y}")
        return

    t = invoice_totals(week)

    ly_start, ly_end = week_range(picked)
    prev_week = invoices_in_week(df, picked - pd.Timedelta(days=7).to_pytimedelta())
    prev_net = invoice_totals(prev_week)["net"] if not prev_week.empty else None

    c.grid(
        c.stat("Τιμολόγια", t["invoices"], accent="var(--brand)",
               foot=f"{len(week[~week['type'].str.upper().str.contains('ΠΙΣΤΩΤΙΚΟ', na=False)])} παραστατικά"),
        c.stat("Πιστωτικά", -t["credits"] if t["credits"] else 0, tone="neg", accent="var(--neg)",
               foot=f"{len(week[week['type'].str.upper().str.contains('ΠΙΣΤΩΤΙΚΟ', na=False)])} παραστατικά"),
        c.scale("Καθαρό", t["net"], prev_net,
                now_tag="Τώρα", then_tag="Προηγ.",
                foot=f"{start:%d/%m} — {end:%d/%m} vs προηγούμενη εβδομάδα"),
        cols=3,
    )

    c.section("Αναλυτικά")
    _table(week)


# ══════════════════════════════════════════════════════════════════════════════
def _yearly(df: pd.DataFrame, today: date) -> None:
    years = sorted(df["date"].dt.year.unique(), reverse=True)

    col, _ = st.columns([1, 2])
    with col:
        year = st.selectbox("Έτος", years, key="inv_year")

    cur = df[df["date"].dt.year == year]
    prev = df[df["date"].dt.year == year - 1]

    if cur.empty:
        c.empty(f"Κανένα παραστατικό για το {year}")
        return

    t = invoice_totals(cur)
    prev_net = invoice_totals(prev)["net"] if not prev.empty else None

    c.grid(
        c.stat("Τιμολόγια", t["invoices"], accent="var(--brand)"),
        c.stat("Πιστωτικά", -t["credits"] if t["credits"] else 0, tone="neg", accent="var(--neg)"),
        c.scale("Καθαρό έτους", t["net"], prev_net, then_tag=str(year - 1)),
        cols=3,
    )

    months = invoices_monthly(df, year)
    prev_months = {m["month"]: m["net"] for m in invoices_monthly(df, year - 1)}

    if months:
        c.section("Ανά μήνα — καθαρό")
        charts.paired_bars(
            [m["name"][:3] for m in months],
            [m["net"] for m in months],
            [prev_months.get(m["month"], 0) for m in months],
            label_now=str(year),
            label_then=str(year - 1),
        )

        c.html("".join(
            c.row(
                m["name"],
                m["net"],
                f"Τιμολόγια {c.eur(m['invoices'])} · Πιστωτικά {c.eur(m['credits'])}",
            )
            for m in months
        ))

    _download(cur, year)


def _download(df: pd.DataFrame, year: int) -> None:
    out = df.copy().sort_values("date")
    out["date"] = out["date"].dt.strftime("%d/%m/%Y")
    out = out.rename(columns={"date": "ΗΜΕΡΟΜΗΝΙΑ", "type": "ΤΥΠΟΣ", "value": "ΑΞΙΑ"})

    c.spacer(0.6)
    st.download_button(
        f"Λήψη CSV — {year}",
        out.to_csv(index=False).encode("utf-8-sig"),
        f"ab_skyros_parastatika_{year}.csv",
        "text/csv",
        key="inv_csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
def _table(week: pd.DataFrame) -> None:
    """Μορφοποίηση ΠΡΙΝ το dataframe — ποτέ .style.format() (τρώει τη μνήμη)."""
    t = week.sort_values("date", ascending=False)

    out = pd.DataFrame({
        "ΗΜΕΡΟΜΗΝΙΑ": t["date"].dt.strftime("%d/%m/%Y"),
        "ΤΥΠΟΣ":      t["type"],
        "ΑΞΙΑ":       t["value"].map(c.eur),
    })

    st.dataframe(out, width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
def _tools() -> None:
    """
    Έλεγχος και καθαρισμός.

    Το παλιό «Διαγραφή» ανά γραμμή ήταν άχρηστο με 496 διπλά — δεν θα πατούσε
    κανείς 496 κουμπιά. Τώρα ένα κουμπί τα καθαρίζει όλα, κρατώντας πάντα την
    πρώτη εμφάνιση κάθε παραστατικού.
    """
    with st.expander("Έλεγχος & καθαρισμός δεδομένων"):
        st.caption(
            "Ψάχνει πανομοιότυπες εγγραφές (ίδια ημερομηνία, τύπος και αξία) "
            "και μέρες που λείπουν."
        )

        if st.button("Έλεγχος τώρα", key="inv_check", width="stretch"):
            st.session_state["inv_checked"] = True

        if not st.session_state.get("inv_checked"):
            return

        with st.spinner("Έλεγχος…"):
            result = check_quality(SHEET_INV)

        dups, gaps = result["duplicates"], result["gaps"]

        if not dups and not gaps:
            c.note("Καθαρά. Καμία διπλή εγγραφή, καμία μέρα δεν λείπει.", "ok")
            return

        if dups:
            extra = sum(len(d["entries"]) - 1 for d in dups)

            c.note(
                f"<b>{len(dups)} παραστατικά</b> υπάρχουν πάνω από μία φορά — "
                f"συνολικά <b>{extra} περιττές γραμμές</b>.<br><br>"
                f"Αυτό συμβαίνει όταν η ΑΒ στείλει το ίδιο Excel σε πολλά email. "
                f"Τα διπλά διπλομετρούν τα σύνολα, οπότε πρέπει να φύγουν.",
                "warn",
            )

            st.caption("Κρατιέται πάντα η πρώτη εμφάνιση κάθε παραστατικού.")

            if st.button(
                f"Καθάρισε τα {extra} διπλά",
                key="inv_purge",
                width="stretch",
                type="primary",
            ):
                with st.spinner(f"Διαγραφή {extra} γραμμών…"):
                    killed, kept = purge_duplicate_invoices()

                if killed:
                    c.note(
                        f"Σβήστηκαν {killed} διπλές γραμμές. "
                        f"Έμειναν {kept} μοναδικά παραστατικά.",
                        "ok",
                    )
                    st.session_state["inv_checked"] = False
                    st.rerun()
                else:
                    c.note("Δεν βρέθηκε τίποτα να σβηστεί.", "info")

            with st.expander(f"Δες τα {len(dups)} πρώτα", expanded=False):
                for d in dups[:20]:
                    lines = ", ".join(f"γρ. {e['row']}" for e in d["entries"])
                    st.markdown(
                        f"**{d['date']}** · {d['type']} · {c.eur(d['value'])} "
                        f"— {len(d['entries'])} φορές ({lines})"
                    )
                if len(dups) > 20:
                    st.caption(f"…και άλλα {len(dups) - 20}")

        if gaps:
            shown = ", ".join(gaps[:15])
            more = f" και άλλες {len(gaps) - 15}" if len(gaps) > 15 else ""
            c.note(
                f"Λείπουν {len(gaps)} εργάσιμες μέρες: {shown}{more}<br><br>"
                f"Τρέξε την «Ενημέρωση δεδομένων» στο κάτω μέρος της σελίδας.",
                "bad",
            )
