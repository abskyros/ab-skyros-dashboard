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
from core.sheets import check_quality, delete_row
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
    Έλεγχος — ΧΩΡΙΣ αυτόματη διαγραφή.

    Ο λόγος είναι στο core/sheets.py: χωρίς αριθμό παραστατικού δεν μπορούμε να
    ξεχωρίσουμε «το ίδιο τιμολόγιο μπήκε 2 φορές» από «δύο διαφορετικά τιμολόγια
    ίδιου ποσού την ίδια μέρα». Το δεύτερο είναι φυσιολογικό — και μια αυτόματη
    διαγραφή θα έσβηνε πραγματικά χρήματα από τα βιβλία.
    """
    with st.expander("Έλεγχος δεδομένων"):
        st.caption("Ψάχνει εγγραφές που μοιάζουν ίδιες και μέρες που λείπουν.")

        if st.button("Έλεγχος τώρα", key="inv_check", width="stretch"):
            st.session_state["inv_checked"] = True

        if not st.session_state.get("inv_checked"):
            return

        with st.spinner("Έλεγχος…"):
            result = check_quality(SHEET_INV)

        dups, gaps = result["duplicates"], result["gaps"]

        if not dups and not gaps:
            c.note("Καθαρά. Καμία ύποπτη εγγραφή, καμία μέρα δεν λείπει.", "ok")
            return

        if dups:
            extra = sum(len(d["entries"]) - 1 for d in dups)

            c.note(
                f"<b>{len(dups)} ομάδες</b> με ίδια ημερομηνία, τύπο και ποσό "
                f"— <b>{extra} επιπλέον γραμμές</b>.<br><br>"
                f"<b>Δεν σβήνονται αυτόματα.</b> Χωρίς τον αριθμό παραστατικού "
                f"δεν ξέρουμε αν είναι:<br>"
                f"• το ίδιο τιμολόγιο καταχωρημένο δύο φορές, ή<br>"
                f"• δύο διαφορετικά τιμολόγια του ίδιου ποσού την ίδια μέρα "
                f"(απολύτως φυσιολογικό).<br><br>"
                f"Μια λάθος διαγραφή αφαιρεί πραγματικά χρήματα από τα βιβλία.",
                "warn",
            )

            with st.expander(f"Δες τις {min(len(dups), 25)} πρώτες", expanded=False):
                for d in dups[:25]:
                    rows = ", ".join(f"γρ. {e['row']}" for e in d["entries"])
                    st.markdown(
                        f"**{d['date']}** · {d['type']} · {c.eur(d['value'])} "
                        f"— {len(d['entries'])} φορές ({rows})"
                    )
                if len(dups) > 25:
                    st.caption(f"…και άλλες {len(dups) - 25} ομάδες")

        if gaps:
            shown = ", ".join(gaps[:15])
            more = f" και άλλες {len(gaps) - 15}" if len(gaps) > 15 else ""
            c.note(
                f"Λείπουν {len(gaps)} εργάσιμες μέρες: {shown}{more}<br><br>"
                f"Τρέξε την «Ενημέρωση δεδομένων» στο κάτω μέρος της σελίδας.",
                "bad",
            )
