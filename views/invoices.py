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
from core.backfill import plan as backfill_plan, apply as backfill_apply, snapshot
from core.mail import fetch_all_invoices
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
        dup_tab, charge_tab, deep_tab = st.tabs([
            "Διπλοκαταχωρήσεις",
            "⚠️ Διπλές χρεώσεις",
            "🔍 Βαθύς έλεγχος",
        ])

        with dup_tab:
            _check_duplicates()

        with charge_tab:
            _check_double_charges(df)

        with deep_tab:
            _deep_check()


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


# ══════════════════════════════════════════════════════════════════════════════
# ΒΑΘΥΣ ΕΛΕΓΧΟΣ
# ══════════════════════════════════════════════════════════════════════════════
def _deep_check() -> None:
    """
    Ανακατασκευή αριθμών από τα email — για τα ΠΑΛΙΑ παραστατικά.

    Τρία βήματα, με ρητή έγκριση ανάμεσα:
        1. ΣΑΡΩΣΗ    → διαβάζει όλα τα email, χτίζει το σχέδιο
        2. ΠΡΟΕΠΙΣΚΟΠΗΣΗ → δείχνει ΑΚΡΙΒΩΣ τι θα γίνει + αντίγραφο ασφαλείας
        3. ΕΚΤΕΛΕΣΗ  → μόνο αφού το δεις και το εγκρίνεις

    Τίποτα δεν αγγίζεται στα βήματα 1-2.
    """
    st.caption(
        "Ξαναδιαβάζει **όλα** τα email παραστατικών και βρίσκει τον πραγματικό "
        "αριθμό κάθε παλιάς εγγραφής. Μετά σβήνει όσες αποδεικνύονται διπλές."
    )

    c.note(
        "<b>Πώς δουλεύει:</b><br>"
        "Αν μια μέρα έχει <b>3 τιμολόγια</b> των 213,51 € στα email, αλλά "
        "<b>5 γραμμές</b> στο Sheet, τότε οι 2 επιπλέον είναι αποδεδειγμένα διπλές.<br><br>"
        "Γραμμές που δεν βρίσκονται σε κανένα email <b>δεν πειράζονται</b> — "
        "δεν ξέρουμε τι είναι, άρα δεν αποφασίζουμε.",
        "info",
    )

    pw = _password()
    if not pw:
        c.note("Λείπει το EMAIL_PASS από τα secrets.", "bad")
        return

    # ── ΒΗΜΑ 1: ΣΑΡΩΣΗ ──
    if st.button("Ξεκίνα σάρωση", key="deep_scan", width="stretch"):
        bar = st.progress(0.0, text="Σύνδεση στο Gmail…")

        def tick(scanned, found):
            # Δεν ξέρουμε πόσα email υπάρχουν — δείχνουμε πρόοδο, όχι ποσοστό.
            pct = min(0.85, scanned / 400)
            bar.progress(pct, text=f"{scanned} email · {found} παραστατικά")

        records, errors, scanned = fetch_all_invoices(pw, on_progress=tick)

        if errors:
            bar.empty()
            c.note(errors[0], "bad")
            return

        bar.progress(0.9, text="Σύγκριση με το Sheet…")
        p = backfill_plan(records, emails_scanned=scanned)

        bar.progress(1.0, text="Έτοιμο")
        bar.empty()

        st.session_state["deep_plan"] = p

    p = st.session_state.get("deep_plan")
    if p is None:
        return

    # ── ΒΗΜΑ 2: ΠΡΟΕΠΙΣΚΟΠΗΣΗ ──
    st.divider()
    c.section("Τι βρέθηκε")

    a, b, d = st.columns(3)
    a.metric("Email", f"{p.emails_scanned:,}".replace(",", "."))
    b.metric("Παραστατικά στα email", f"{p.records_found:,}".replace(",", "."))
    d.metric("Γραμμές στο Sheet", f"{p.sheet_rows:,}".replace(",", "."))

    if not p.touched:
        c.note("Όλα εντάξει. Καμία αλλαγή δεν χρειάζεται.", "ok")
        return

    c.section("Τι θα γίνει")

    lines = []
    if p.fill:
        lines.append(f"✓ <b>{len(p.fill)}</b> γραμμές θα πάρουν τον αριθμό τους")
    if p.delete:
        lines.append(
            f"🗑 <b>{len(p.delete)}</b> γραμμές θα <b>σβηστούν</b> "
            f"(αποδεδειγμένα διπλές — αξίας {c.eur(p.deleted_value)})"
        )
    if p.add:
        lines.append(f"+ <b>{len(p.add)}</b> παραστατικά λείπουν και θα προστεθούν")
    if p.skip:
        lines.append(
            f"⊘ <b>{len(p.skip)}</b> γραμμές <b>δεν πειράζονται</b> "
            f"(δεν βρέθηκαν στα email)"
        )
    if p.already:
        lines.append(f"· {p.already} είχαν ήδη αριθμό")

    c.note("<br>".join(lines), "warn" if p.delete else "info")

    if p.skip:
        with st.expander(f"Δες τις {len(p.skip)} γραμμές που δεν πειράζονται"):
            st.caption(
                "Αυτές δεν βρέθηκαν σε κανένα email. Ίσως το email σβήστηκε, "
                "ίσως καταχωρήθηκαν με το χέρι. Μένουν ως έχουν."
            )
            for x in p.skip[:40]:
                st.markdown(
                    f"γρ. {x['row']} · {x['date']} · {x['type'][:28]} · {c.eur(x['value'])}"
                )
            if len(p.skip) > 40:
                st.caption(f"…και άλλες {len(p.skip) - 40}")

    # ── ΑΝΤΙΓΡΑΦΟ ΑΣΦΑΛΕΙΑΣ ──
    if p.delete:
        st.divider()
        c.section("Πριν προχωρήσεις")

        c.note(
            "<b>Κατέβασε αντίγραφο ασφαλείας.</b><br>"
            "Αν κάτι πάει στραβά, ξαναγράφεις το φύλλο από αυτό το αρχείο.",
            "bad",
        )

        st.download_button(
            "Λήψη αντιγράφου (CSV)",
            snapshot().encode("utf-8-sig"),
            "invoices_backup.csv",
            "text/csv",
            key="deep_backup",
            width="stretch",
        )

        confirmed = st.checkbox(
            f"Κατέβασα το αντίγραφο. Καταλαβαίνω ότι θα σβηστούν "
            f"{len(p.delete)} γραμμές.",
            key="deep_confirm",
        )
    else:
        confirmed = True

    # ── ΒΗΜΑ 3: ΕΚΤΕΛΕΣΗ ──
    st.divider()

    if st.button(
        "Εκτέλεση",
        key="deep_apply",
        width="stretch",
        type="primary",
        disabled=not confirmed,
    ):
        with st.spinner("Ενημέρωση Sheet…"):
            done = backfill_apply(p)

        if done["errors"]:
            for e in done["errors"]:
                c.note(e, "bad")

        c.note(
            f"Ολοκληρώθηκε.<br>"
            f"• {done['filled']} γραμμές πήραν αριθμό<br>"
            f"• {done['deleted']} διπλές σβήστηκαν<br>"
            f"• {done['added']} προστέθηκαν",
            "ok",
        )

        st.session_state.pop("deep_plan", None)
        st.session_state["deep_confirm"] = False


def _password() -> str:
    try:
        return st.secrets.get("EMAIL_PASS", "")
    except Exception:
        return ""
