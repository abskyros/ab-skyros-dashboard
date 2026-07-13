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
from core.backfill import (
    plan as backfill_plan,
    apply as backfill_apply,
    repair_week, apply_repair,
    diagnose, audit, snapshot,
)
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
        verify_tab, dup_tab, charge_tab, deep_tab = st.tabs([
            "✅ Επαλήθευση",
            "Διπλοκαταχωρήσεις",
            "⚠️ Διπλές χρεώσεις",
            "🔍 Βαθύς έλεγχος",
        ])

        with verify_tab:
            _verify(df)

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
        1. ΣΑΡΩΣΗ        → διαβάζει όλα τα email, χτίζει το σχέδιο
        2. ΠΡΟΕΠΙΣΚΟΠΗΣΗ → δείχνει ΑΚΡΙΒΩΣ τι θα γίνει + αντίγραφο ασφαλείας
        3. ΕΚΤΕΛΕΣΗ      → μόνο αφού το δεις και το εγκρίνεις

    Τίποτα δεν αγγίζεται στα βήματα 1-2.

    ΕΠΑΝΑΛΗΨΙΜΟ: αν το Google κόψει τη σύνδεση στη μέση (rate limit), ξανατρέχεις
    και συνεχίζει από εκεί που έμεινε. Το γέμισμα είναι idempotent.
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
            pct = min(0.85, scanned / 400)
            bar.progress(pct, text=f"{scanned} email · {found} παραστατικά")

        records, errors, scanned = fetch_all_invoices(pw, on_progress=tick)

        if errors:
            bar.empty()
            c.note(errors[0], "bad")
            return

        bar.progress(0.9, text="Σύγκριση με το Sheet…")
        p = backfill_plan(records, emails_scanned=scanned)

        bar.empty()
        st.session_state["deep_plan"] = p
        st.session_state["deep_done"] = None

    # ── ΑΠΟΤΕΛΕΣΜΑ ΠΡΟΗΓΟΥΜΕΝΗΣ ΕΚΤΕΛΕΣΗΣ ──
    done = st.session_state.get("deep_done")
    if done:
        _report(done)
        return

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
        lines.append(f"⊘ <b>{len(p.skip)}</b> γραμμές <b>δεν πειράζονται</b> (δεν βρέθηκαν στα email)")
    if p.already:
        lines.append(f"· {p.already} είχαν ήδη αριθμό")

    c.note("<br>".join(lines), "warn" if p.delete else "info")

    # Χρόνος — το Google επιτρέπει 60 write/λεπτό, άρα κάνουμε παύσεις.
    steps = (len(p.fill) + 499) // 500 + len(p.delete) // 20 + (1 if p.add else 0)
    if steps > 3:
        st.caption(f"Εκτιμώμενος χρόνος: ~{max(1, steps * 2 // 60 + 1)} λεπτά "
                   f"(κάνουμε παύσεις για να μη μας κόψει το Google).")

    if p.skip:
        _diagnosis(p)

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
            f"Κατέβασα το αντίγραφο. Καταλαβαίνω ότι θα σβηστούν {len(p.delete)} γραμμές.",
            key="deep_confirm",
        )
    else:
        confirmed = True

    # ── ΒΗΜΑ 3: ΕΚΤΕΛΕΣΗ ──
    st.divider()

    if st.button("Εκτέλεση", key="deep_apply", width="stretch",
                 type="primary", disabled=not confirmed):

        bar = st.progress(0.0, text="Έναρξη…")

        def progress(stage, cur, total):
            bar.progress(min(1.0, cur / max(total, 1)),
                         text=f"{stage} — {cur}/{total}")

        result = backfill_apply(p, on_progress=progress)
        bar.empty()

        # ΚΡΙΣΙΜΟ: ΟΧΙ st.rerun() εδώ.
        #
        # Το checkbox «deep_confirm» υπάρχει ήδη στη σελίδα. Το st.rerun() μέσα
        # στο callback ενός κουμπιού, ενώ το widget είναι ζωντανό, ρίχνει
        # StreamlitAPIException.
        #
        # Αντ' αυτού δείχνουμε το αποτέλεσμα ΕΠΙΤΟΠΟΥ και σβήνουμε το σχέδιο.
        # Στο επόμενο φυσιολογικό rerun (όταν ο χρήστης πατήσει κάτι), η σελίδα
        # θα δείξει μόνο την αναφορά.
        st.session_state["deep_done"] = result
        st.session_state.pop("deep_plan", None)

        _report(result)


def _report(done: dict) -> None:
    """Το αποτέλεσμα της εκτέλεσης — με ΕΙΛΙΚΡΙΝΗ αριθμητική."""
    st.divider()

    if done.get("complete"):
        c.note(
            f"<b>Ολοκληρώθηκε.</b><br>"
            f"• {done['filled']} γραμμές πήραν αριθμό<br>"
            f"• {done['deleted']} διπλές σβήστηκαν<br>"
            f"• {done['added']} προστέθηκαν<br><br>"
            f"Πάτα <b>«Νέα σάρωση»</b> για να ελέγξεις αν έμεινε κάτι.",
            "ok",
        )
    else:
        # ΔΕΝ λέμε «ολοκληρώθηκε» όταν δεν ολοκληρώθηκε.
        c.note(
            f"<b>Δεν ολοκληρώθηκε.</b><br>"
            f"Πέρασαν: {done['filled']} γεμίσματα · {done['deleted']} διαγραφές · "
            f"{done['added']} προσθήκες<br><br>"
            f"<b>Ξανατρέξε τη σάρωση</b> — θα συνεχίσει από εκεί που έμεινε. "
            f"Τίποτα δεν χάθηκε.",
            "warn",
        )

        for e in done.get("errors", []):
            if "Quota exceeded" in e or "429" in e:
                c.note(
                    "Το Google έκοψε τη σύνδεση (όριο 60 εγγραφών/λεπτό). "
                    "Περίμενε ένα λεπτό και ξαναπάτα «Ξεκίνα σάρωση».",
                    "bad",
                )
                break
            c.note(e, "bad")

    if st.button("Νέα σάρωση", key="deep_reset", width="stretch"):
        st.session_state.pop("deep_done", None)
        st.session_state.pop("deep_plan", None)


def _password() -> str:
    try:
        return st.secrets.get("EMAIL_PASS", "")
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
def _diagnosis(p) -> None:
    """
    ΓΙΑΤΙ δεν βρέθηκαν αυτές οι γραμμές;

    Μια λίστα με 2.968 γραμμές δεν βοηθάει κανέναν. Η αιτία βοηθάει.
    """
    with st.expander(f"Γιατί {len(p.skip)} γραμμές δεν βρέθηκαν;", expanded=True):

        with st.spinner("Ανάλυση…"):
            d = diagnose(p, p.records)

        if d["email_from"]:
            st.caption(
                f"Τα email καλύπτουν από **{d['email_from']}** έως **{d['email_to']}**."
            )

        old_rows = d["out_of_range"]
        wrong = d["amount_mismatch"]
        unknown = d["unknown_day"]

        # ── 1. ΕΚΤΟΣ ΕΜΒΕΛΕΙΑΣ ──
        if old_rows:
            c.note(
                f"<b>{len(old_rows)} γραμμές είναι παλιότερες από το παλιότερο email.</b><br><br>"
                f"Το Gmail δεν κρατάει τα πάντα για πάντα. Δεν υπάρχει τρόπος να "
                f"βρούμε τους αριθμούς τους.<br><br>"
                f"<b>Μένουν ως έχουν.</b> Δεν είναι απαραίτητα λάθος — απλώς δεν "
                f"μπορούμε να τις ελέγξουμε.",
                "info",
            )

        # ── 2. ΤΟ ΠΟΣΟ ΔΕΝ ΤΑΙΡΙΑΖΕΙ — ΤΟ ΚΑΜΠΑΝΑΚΙ ──
        if wrong:
            scaled = [x for x in wrong if x.get("hint")]

            if scaled:
                c.note(
                    f"<b>⚠️ {len(scaled)} γραμμές έχουν ΛΑΘΟΣ ΠΟΣΟ.</b><br><br>"
                    f"Η μέρα και ο τύπος υπάρχουν στα email — αλλά το ποσό στο Sheet "
                    f"είναι <b>100× λάθος</b>.<br><br>"
                    f"Αυτό είναι το σφάλμα του παλιού <code>daily_sync.py</code>, που "
                    f"έγραφε <b>ευρώ αντί για λεπτά</b>. Οι γραμμές αυτές δείχνουν "
                    f"λάθος νούμερα στα βιβλία σου.",
                    "bad",
                )

                st.caption("Δείγμα:")
                for x in scaled[:8]:
                    exp = x["expected"][0] / 100 if x["expected"] else 0
                    st.markdown(
                        f"γρ. **{x['row']}** · {x['date']} · "
                        f"Sheet: **{c.eur(x['value'])}** → "
                        f"Email: **{c.eur(exp)}**  `{x['hint']}`"
                    )
                if len(scaled) > 8:
                    st.caption(f"…και άλλες {len(scaled) - 8}")

            other = [x for x in wrong if not x.get("hint")]
            if other:
                c.note(
                    f"<b>{len(other)} γραμμές έχουν ποσό που δεν υπάρχει στα email.</b><br><br>"
                    f"Η μέρα και ο τύπος ταιριάζουν, το ποσό όχι — και δεν είναι "
                    f"σφάλμα ×100. Ίσως διορθώθηκε χειροκίνητα, ίσως το email έχει "
                    f"διαφορετική έκδοση.",
                    "warn",
                )
                with st.expander(f"Δες τις {len(other)}"):
                    for x in other[:30]:
                        exp = ", ".join(c.eur(v / 100) for v in x["expected"])
                        st.markdown(
                            f"γρ. {x['row']} · {x['date']} · "
                            f"Sheet: {c.eur(x['value'])} · Email έχει: {exp}"
                        )

        # ── 3. ΑΓΝΩΣΤΗ ΜΕΡΑ ──
        if unknown:
            c.note(
                f"<b>{len(unknown)} γραμμές έχουν μέρα/τύπο που δεν υπάρχει σε κανένα email.</b><br><br>"
                f"Χειροκίνητη καταχώρηση; Σβησμένο email; Δεν ξέρουμε — άρα δεν "
                f"τις πειράζουμε.",
                "warn",
            )
            with st.expander(f"Δες τις {min(len(unknown), 30)} πρώτες"):
                for x in unknown[:30]:
                    st.markdown(
                        f"γρ. {x['row']} · {x['date']} · {x['type'][:30]} · {c.eur(x['value'])}"
                    )


# ══════════════════════════════════════════════════════════════════════════════
# ΕΠΑΛΗΘΕΥΣΗ — ΤΟ SHEET ΣΥΜΦΩΝΕΙ ΜΕ ΤΑ EMAIL;
# ══════════════════════════════════════════════════════════════════════════════
def _verify(df: pd.DataFrame) -> None:
    """
    Βάζει το Sheet δίπλα στα email, για μία εβδομάδα.

    ΓΙΑΤΙ ΥΠΑΡΧΕΙ:
    Τα email είναι η ΠΗΓΗ. Το Sheet είναι αντίγραφο. Αν διαφέρουν, το Sheet
    έχει σκουπίδια — και τα σύνολά σου είναι λάθος.

    Αυτό το εργαλείο δεν μαντεύει: κατεβάζει τα email αυτής της εβδομάδας,
    τα αθροίζει, και συγκρίνει. Μετά δείχνει ΑΚΡΙΒΩΣ ποιες γραμμές περισσεύουν.
    """
    st.caption(
        "Συγκρίνει το Sheet με τα **πραγματικά email** μιας εβδομάδας. "
        "Αν τα σύνολα διαφέρουν, δείχνει ποιες γραμμές φταίνε."
    )

    pw = _password()
    if not pw:
        c.note("Λείπει το EMAIL_PASS από τα secrets.", "bad")
        return

    col, _ = st.columns([1, 2])
    with col:
        picked = st.date_input("Εβδομάδα", date.today(), key="vf_day", format="DD/MM/YYYY")

    start, end = week_range(picked)
    st.caption(f"Περίοδος: **{start:%d/%m/%Y}** — **{end:%d/%m/%Y}**")

    if not st.button("Σύγκριση με τα email", key="vf_run", width="stretch"):
        return

    # Κατεβάζουμε ΜΟΝΟ τα email αυτής της περιόδου (+ λίγο περιθώριο,
    # γιατί το email μπορεί να έρθει μέρες αργότερα).
    with st.spinner("Διάβασμα email…"):
        records, errors, scanned = fetch_all_invoices(
            pw, since=start - pd.Timedelta(days=21).to_pytimedelta()
        )

    if errors:
        c.note(errors[0], "bad")
        return

    a = audit(df, records, start, end)

    e, sh = a["email"], a["sheet"]

    # ── ΤΑ ΣΥΝΟΛΑ, ΔΙΠΛΑ-ΔΙΠΛΑ ──
    c.section("Σύγκριση")

    same = abs(e["net"] - sh["net"]) < 0.01

    c.html(
        '<div class="grid g2">'
        + c.stat("Email (η αλήθεια)", e["net"], accent="var(--pos)",
                 foot=f"{e['count']} παραστατικά · "
                      f"Τιμ. {c.eur(e['invoices'])} · Πιστ. {c.eur(e['credits'])}")
        + c.stat("Sheet", sh["net"],
                 tone="" if same else "neg",
                 accent="var(--pos)" if same else "var(--neg)",
                 foot=f"{sh['count']} γραμμές · "
                      f"Τιμ. {c.eur(sh['invoices'])} · Πιστ. {c.eur(sh['credits'])}")
        + '</div>'
    )

    if same and not a["extra"] and not a["missing"]:
        c.note("Το Sheet συμφωνεί απόλυτα με τα email.", "ok")
        return

    diff = sh["net"] - e["net"]

    c.note(
        f"<b>Διαφορά: {c.eur(diff)}</b><br><br>"
        f"Το Sheet έχει <b>{sh['count']}</b> γραμμές, τα email <b>{e['count']}</b> "
        f"παραστατικά.<br>"
        f"Τα email είναι η πηγή — άρα το Sheet έχει σκουπίδια.",
        "bad",
    )

    # ── ΟΙ ΓΡΑΜΜΕΣ ΠΟΥ ΠΕΡΙΣΣΕΥΟΥΝ ──
    if a["extra"]:
        c.section(f"{len(a['extra'])} γραμμές περισσεύουν")

        by_why = {}
        for x in a["extra"]:
            by_why.setdefault(x["why"], []).append(x)

        for why, rows in sorted(by_why.items(), key=lambda kv: -len(kv[1])):
            total = sum(r["value"] for r in rows)
            st.markdown(f"**{len(rows)}** — {why} · σύνολο **{c.eur(total)}**")

        with st.expander("Δες τις πρώτες 30"):
            for x in a["extra"][:30]:
                st.markdown(
                    f"γρ. **{x['row']}** · {x['date']} · {x['type'][:26]} · "
                    f"**{c.eur(x['value'])}** · "
                    f"<span style='color:#94A3B8'>{x['number'] or '—'} · {x['why']}</span>",
                    unsafe_allow_html=True,
                )

        # ── ΕΠΙΣΚΕΥΗ ──
        st.divider()
        c.section("Επισκευή")

        st.caption(
            "Γεμίζει τους αριθμούς από τα email, και μετά σβήνει ό,τι απομείνει "
            "χωρίς αριθμό — αυτά είναι αποδεδειγμένα διπλά."
        )

        with st.spinner("Υπολογισμός…"):
            rep = repair_week(records, start, end)

        if not rep["fill"] and not rep["delete"]:
            c.note("Δεν βρέθηκε τίποτα να επισκευαστεί.", "info")
        else:
            lines = []
            if rep["fill"]:
                lines.append(f"✓ <b>{len(rep['fill'])}</b> γραμμές θα πάρουν τον αριθμό τους")
            if rep["delete"]:
                lines.append(
                    f"🗑 <b>{len(rep['delete'])}</b> γραμμές θα <b>σβηστούν</b> "
                    f"(αξίας {c.eur(rep['value'])})"
                )
            if rep["keep"]:
                lines.append(
                    f"⊘ <b>{len(rep['keep'])}</b> γραμμές <b>δεν πειράζονται</b> "
                    f"(δεν υπάρχουν στα email αυτής της εβδομάδας)"
                )

            c.note("<br>".join(lines), "warn" if rep["delete"] else "info")

            st.caption(
                "**Η λογική:** αν η 10/07 έχει 11 τιμολόγια στα email αλλά 30 γραμμές "
                "στο Sheet, οι 11 πρώτες παίρνουν τους αριθμούς — οι 19 υπόλοιπες "
                "δεν έχουν αριθμό να πάρουν, άρα είναι διπλές."
            )

            if rep["delete"]:
                st.download_button(
                    "Λήψη αντιγράφου ασφαλείας (CSV)",
                    snapshot().encode("utf-8-sig"),
                    f"invoices_backup_{start:%Y%m%d}.csv",
                    "text/csv",
                    key="vf_backup",
                    width="stretch",
                )

                confirmed = st.checkbox(
                    f"Κατέβασα το αντίγραφο. Σβήσε τις {len(rep['delete'])} γραμμές.",
                    key="vf_confirm",
                )
            else:
                confirmed = True

            if st.button("Επισκευή εβδομάδας", key="vf_repair",
                         width="stretch", type="primary", disabled=not confirmed):

                with st.spinner("Επισκευή…"):
                    done = apply_repair(rep)

                if done["complete"]:
                    c.note(
                        f"<b>Ολοκληρώθηκε.</b><br>"
                        f"• {done['filled']} γραμμές πήραν αριθμό<br>"
                        f"• {done['deleted']} διπλές σβήστηκαν<br><br>"
                        f"Πάτα ξανά <b>«Σύγκριση με τα email»</b> για επαλήθευση.",
                        "ok",
                    )
                else:
                    c.note(
                        f"<b>Δεν ολοκληρώθηκε.</b><br>"
                        f"Πέρασαν: {done['filled']} γεμίσματα, {done['deleted']} διαγραφές.<br>"
                        f"Ξαναδοκίμασε — θα συνεχίσει από εκεί που έμεινε.",
                        "warn",
                    )
                    for e in done["errors"]:
                        c.note(e, "bad")

    # ── ΟΣΑ ΛΕΙΠΟΥΝ ──
    if a["missing"]:
        c.section(f"{len(a['missing'])} παραστατικά λείπουν από το Sheet")
        for x in a["missing"][:20]:
            st.markdown(
                f"{x['date']} · {x['type'][:26]} · **{c.eur(x['value'])}** · #{x['number']}"
            )
        c.note("Τρέξε την «Ενημέρωση δεδομένων» για να προστεθούν.", "info")


