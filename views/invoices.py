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
from core.sheets import (
    check_quality, delete_row,
    purge_duplicate_invoices, find_double_charges,
)
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

    _tools(df)

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
def _tools(df: pd.DataFrame) -> None:
    """
    ΔΥΟ ΕΛΕΓΧΟΙ, ΔΥΟ ΔΙΑΦΟΡΕΤΙΚΑ ΠΡΟΒΛΗΜΑΤΑ:

      1. ΔΙΠΛΟΚΑΤΑΧΩΡΗΣΗ — ίδιος αριθμός παραστατικού 2+ φορές.
         Σφάλμα ΔΙΚΟ ΜΑΣ. Σβήνεται με ασφάλεια.

      2. ΔΙΠΛΗ ΧΡΕΩΣΗ — διαφορετικοί αριθμοί, ίδιο ποσό & μέρα.
         Πιθανό σφάλμα ΤΟΥ ΠΡΟΜΗΘΕΥΤΗ. ΔΕΝ σβήνεται — θέλει τηλέφωνο στην ΑΒ.

    Η διάκριση είναι όλη η ουσία. Το πρώτο διορθώνεται με ένα κουμπί. Το δεύτερο
    είναι λεφτά που ίσως πλήρωσες δύο φορές.
    """
    with st.expander("Έλεγχος δεδομένων"):
        dup_tab, charge_tab = st.tabs(["Διπλοκαταχωρήσεις", "⚠️ Διπλές χρεώσεις"])

        with dup_tab:
            _check_duplicates()

        with charge_tab:
            _check_double_charges(df)


# ══════════════════════════════════════════════════════════════════════════════
def _check_duplicates() -> None:
    """Ίδιος αριθμός παραστατικού πάνω από μία φορά → δικό μας λάθος."""
    st.caption(
        "Ψάχνει παραστατικά με τον **ίδιο αριθμό** καταχωρημένα πάνω από μία φορά. "
        "Αυτά είναι διπλοκαταχωρήσεις και σβήνονται με ασφάλεια."
    )

    if st.button("Έλεγχος τώρα", key="inv_check", width="stretch"):
        st.session_state["inv_checked"] = True

    if not st.session_state.get("inv_checked"):
        return

    with st.spinner("Έλεγχος…"):
        result = check_quality(SHEET_INV)

    dups = result["duplicates"]
    gaps = result["gaps"]
    legacy = result.get("no_number", 0)

    if legacy:
        c.note(
            f"<b>{legacy} παλιές εγγραφές</b> δεν έχουν αριθμό παραστατικού "
            f"(καταχωρήθηκαν πριν προστεθεί η στήλη).<br><br>"
            f"Αυτές <b>δεν ελέγχονται και δεν σβήνονται</b> — χωρίς αριθμό δεν "
            f"ξέρουμε αν είναι διπλές. Θα αντικατασταθούν σταδιακά καθώς έρχονται "
            f"νέα email.",
            "info",
        )

    if not dups:
        c.note("Καμία διπλοκαταχώρηση. Κάθε αριθμός παραστατικού εμφανίζεται μία φορά.", "ok")
    else:
        extra = sum(len(d["entries"]) - 1 for d in dups)

        c.note(
            f"<b>{len(dups)} παραστατικά</b> καταχωρήθηκαν πάνω από μία φορά "
            f"— <b>{extra} περιττές γραμμές</b>.<br><br>"
            f"Ίδιος αριθμός παραστατικού = το ίδιο τιμολόγιο. Σβήνεται με ασφάλεια.",
            "warn",
        )

        if st.button(f"Καθάρισε τις {extra} περιττές γραμμές",
                     key="inv_purge", width="stretch", type="primary"):
            with st.spinner(f"Διαγραφή {extra} γραμμών…"):
                killed, kept, skipped = purge_duplicate_invoices()

            msg = f"Σβήστηκαν {killed} γραμμές. Έμειναν {kept} μοναδικά παραστατικά."
            if skipped:
                msg += f" ({skipped} παλιές χωρίς αριθμό δεν πειράχτηκαν.)"

            c.note(msg, "ok")
            st.session_state["inv_checked"] = False
            st.rerun()

        with st.expander("Δες τα αναλυτικά", expanded=False):
            for d in dups[:25]:
                rows = ", ".join(f"γρ. {e['row']}" for e in d["entries"])
                num = d.get("number", "")
                st.markdown(
                    f"**#{num}** · {d['date']} · {c.eur(d['value'])} "
                    f"— {len(d['entries'])} φορές ({rows})"
                )
            if len(dups) > 25:
                st.caption(f"…και άλλα {len(dups) - 25}")

    if gaps:
        shown = ", ".join(gaps[:15])
        more = f" και άλλες {len(gaps) - 15}" if len(gaps) > 15 else ""
        c.note(f"Λείπουν {len(gaps)} εργάσιμες μέρες: {shown}{more}", "bad")


# ══════════════════════════════════════════════════════════════════════════════
def _check_double_charges(df: pd.DataFrame) -> None:
    """
    Διαφορετικοί αριθμοί, ίδιο ποσό & μέρα → πιθανή διπλή χρέωση.

    ΔΕΝ ΣΒΗΝΕΤΑΙ ΠΟΤΕ. Δύο τιμολόγια των 213,51 € την ίδια μέρα μπορεί να είναι:
      • Δύο πραγματικές παραδόσεις (φυσιολογικό)
      • Το ίδιο τιμολόγιο κομμένο δύο φορές (σου χρέωσαν διπλά)

    Μόνο εσύ ξέρεις ποιο από τα δύο. Το εργαλείο απλώς τα δείχνει.
    """
    st.caption(
        "Ψάχνει παραστατικά με **διαφορετικό αριθμό** αλλά ίδιο ποσό την ίδια μέρα. "
        "Μπορεί να είναι δύο κανονικές παραδόσεις — ή διπλή χρέωση."
    )

    if st.button("Έλεγχος τώρα", key="chg_check", width="stretch"):
        st.session_state["chg_checked"] = True

    if not st.session_state.get("chg_checked"):
        return

    with st.spinner("Έλεγχος…"):
        found = find_double_charges(df)

    if not found:
        c.note("Καμία ύποπτη χρέωση.", "ok")
        return

    total = sum(f["value"] * (f["count"] - 1) for f in found)

    c.note(
        f"<b>{len(found)} περιπτώσεις</b> με ίδιο ποσό, ίδια μέρα, "
        f"αλλά <b>διαφορετικούς αριθμούς</b>.<br><br>"
        f"Αν είναι διπλές χρεώσεις, μιλάμε για <b>{c.eur(total)}</b>.<br><br>"
        f"<b>Δεν σβήνονται.</b> Μπορεί να είναι δύο πραγματικές παραδόσεις. "
        f"Έλεγξε τα δελτία αποστολής — αν είναι λάθος, τηλεφώνησε στην ΑΒ.",
        "warn",
    )

    for f in found[:30]:
        nums = " · ".join(f"#{n}" for n in f["numbers"])
        st.markdown(
            f"**{f['date']}** — {f['type'][:30]} · **{c.eur(f['value'])}** × {f['count']}  \
"
            f"<span style='color:#64748B;font-size:.8rem'>{nums}</span>",
            unsafe_allow_html=True,
        )

    if len(found) > 30:
        st.caption(f"…και άλλες {len(found) - 30}")
