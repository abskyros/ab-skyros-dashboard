"""
views/invoices.py — Παραστατικά.

Το νούμερο που μετράει είναι το ΚΑΘΑΡΟ: τιμολόγια μείον πιστωτικά.
Τα δύο σκέλη φαίνονται ξεχωριστά, γιατί ένα μεγάλο πιστωτικό είναι από μόνο του
είδηση — δεν πρέπει να κρύβεται μέσα σε ένα άθροισμα.
"""

from datetime import date, timedelta

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
    repair, apply_repair, audit, snapshot,
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
        clean_tab, verify_tab, charge_tab = st.tabs([
            "🧹 Καθαρισμός (όλα τα χρόνια)",
            "✅ Επαλήθευση εβδομάδας",
            "⚠️ Διπλές χρεώσεις",
        ])

        with clean_tab:
            _clean_all()

        with verify_tab:
            _verify(df)

        with charge_tab:
            _check_double_charges(df)


# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# ΕΠΑΛΗΘΕΥΣΗ — ΤΟ SHEET ΣΥΜΦΩΝΕΙ ΜΕ ΤΑ EMAIL;
# ══════════════════════════════════════════════════════════════════════════════
def _verify(df: pd.DataFrame) -> None:
    """
    Βάζει το Sheet δίπλα στα email, για μία εβδομάδα.

    Τα email είναι η ΠΗΓΗ. Το Sheet είναι αντίγραφο. Αν διαφέρουν, το Sheet έχει
    σκουπίδια — και τα σύνολά σου είναι λάθος.

    Χρήσιμο ΜΕΤΑ τον καθαρισμό: επιβεβαιώνει ότι όλα πήγαν καλά.
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

    # Κατεβάζουμε τα email της περιόδου, με περιθώριο 3 εβδομάδων πίσω —
    # το email μπορεί να έρθει μέρες μετά την ημερομηνία του παραστατικού.
    with st.spinner("Διάβασμα email…"):
        records, errors, scanned = fetch_all_invoices(
            pw, since=start - timedelta(days=21)
        )

    if errors:
        c.note(errors[0], "bad")
        return

    a = audit(df, records, start, end)
    e, sh = a["email"], a["sheet"]

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
        f"παραστατικά.<br><br>"
        f"Τρέξε τον <b>🧹 Καθαρισμό</b> για να διορθωθεί.",
        "bad",
    )

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

    if a["missing"]:
        c.section(f"{len(a['missing'])} παραστατικά λείπουν")
        for x in a["missing"][:20]:
            st.markdown(
                f"{x['date']} · {x['type'][:26]} · **{c.eur(x['value'])}** · #{x['number']}"
            )
        c.note("Τρέξε την «Ενημέρωση δεδομένων» για να προστεθούν.", "info")


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
# ΚΑΘΑΡΙΣΜΟΣ — ΟΛΑ ΤΑ ΧΡΟΝΙΑ, ΜΙΑ ΦΟΡΑ
# ══════════════════════════════════════════════════════════════════════════════
def _clean_all() -> None:
    """
    Η ΜΕΓΑΛΗ ΚΑΘΑΡΙΟΤΗΤΑ.

    Τρέχει ΜΙΑ ΦΟΡΑ. Από εδώ και πέρα το data_sync κρατάει το Sheet καθαρό —
    το κλειδί (αριθμός παραστατικού) δεν αφήνει διπλά να μπουν.

    Τρία βήματα, με ρητή έγκριση:
        1. ΣΑΡΩΣΗ  → διαβάζει ΟΛΑ τα email, όλων των ετών
        2. ΣΧΕΔΙΟ  → δείχνει ακριβώς τι θα γίνει. Δεν αγγίζει τίποτα.
        3. ΕΚΤΕΛΕΣΗ → γεμίζει αριθμούς, μετά σβήνει τα διπλά
    """
    st.caption(
        "Διαβάζει **όλα** τα email παραστατικών, γεμίζει τους αριθμούς, "
        "και σβήνει **όλες** τις διπλές καταχωρήσεις — όλων των ετών."
    )

    c.note(
        "<b>Τρέχει μία φορά.</b><br><br>"
        "Από εδώ και πέρα το σύστημα κρατάει το Sheet καθαρό μόνο του: "
        "το κλειδί είναι ο <b>αριθμός παραστατικού</b>, και δεν αφήνει το ίδιο "
        "τιμολόγιο να μπει δύο φορές.<br><br>"
        "<b>Η λογική:</b> αν η 10/07 έχει 11 τιμολόγια στα email αλλά 30 γραμμές "
        "στο Sheet, οι 11 πρώτες παίρνουν τους αριθμούς — οι 19 υπόλοιπες δεν "
        "έχουν αριθμό να πάρουν, άρα είναι διπλές.",
        "info",
    )

    pw = _password()
    if not pw:
        c.note("Λείπει το EMAIL_PASS από τα secrets.", "bad")
        return

    # ── ΑΠΟΤΕΛΕΣΜΑ ΠΡΟΗΓΟΥΜΕΝΗΣ ΕΚΤΕΛΕΣΗΣ ──
    done = st.session_state.get("clean_done")
    if done:
        _clean_report(done)
        return

    # ── ΒΗΜΑ 1: ΣΑΡΩΣΗ ──
    if st.button("Ξεκίνα σάρωση (όλα τα email)", key="cl_scan", width="stretch"):
        bar = st.progress(0.0, text="Σύνδεση στο Gmail…")

        def tick(scanned, found):
            bar.progress(min(0.8, scanned / 500),
                         text=f"{scanned} email · {found} παραστατικά")

        records, errors, scanned = fetch_all_invoices(pw, on_progress=tick)

        if errors:
            bar.empty()
            c.note(errors[0], "bad")
            return

        bar.progress(0.9, text="Σύγκριση με το Sheet…")
        rep = repair(records)          # ΧΩΡΙΣ όρια → όλα τα χρόνια

        bar.empty()

        st.session_state["clean_plan"] = rep
        st.session_state["clean_meta"] = {"emails": scanned, "records": len(records)}

    rep = st.session_state.get("clean_plan")
    if rep is None:
        return

    meta = st.session_state.get("clean_meta", {})

    # ── ΒΗΜΑ 2: ΤΟ ΣΧΕΔΙΟ ──
    st.divider()
    c.section("Τι βρέθηκε")

    a, b, d = st.columns(3)
    a.metric("Email", f"{meta.get('emails', 0):,}".replace(",", "."))
    b.metric("Παραστατικά", f"{meta.get('records', 0):,}".replace(",", "."))
    d.metric("Γραμμές Sheet", f"{rep['scanned']:,}".replace(",", "."))

    if not rep["fill"] and not rep["delete"]:
        c.note(
            "Το Sheet είναι ήδη καθαρό. Καμία αλλαγή δεν χρειάζεται.",
            "ok",
        )
        return

    c.section("Τι θα γίνει")

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
            f"(δεν υπάρχουν σε κανένα email)"
        )

    c.note("<br>".join(lines), "warn" if rep["delete"] else "info")

    after = rep["scanned"] - len(rep["delete"])
    st.caption(
        f"Το Sheet θα πάει από **{rep['scanned']:,}** σε **{after:,}** γραμμές."
        .replace(",", ".")
    )

    # Χρόνος
    steps = (len(rep["fill"]) + 499) // 500 + len(rep["delete"]) // 30 + 1
    if steps > 5:
        st.caption(f"Εκτιμώμενος χρόνος: ~{max(1, steps * 2 // 60 + 1)} λεπτά.")

    # ── ΑΝΤΙΓΡΑΦΟ ──
    if rep["delete"]:
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
            key="cl_backup",
            width="stretch",
        )

        confirmed = st.checkbox(
            f"Κατέβασα το αντίγραφο. Καταλαβαίνω ότι θα σβηστούν "
            f"{len(rep['delete'])} γραμμές.",
            key="cl_confirm",
        )
    else:
        confirmed = True

    # ── ΒΗΜΑ 3: ΕΚΤΕΛΕΣΗ ──
    st.divider()

    if st.button("Καθαρισμός", key="cl_apply", width="stretch",
                 type="primary", disabled=not confirmed):

        bar = st.progress(0.0, text="Έναρξη…")

        def progress(stage, cur, total):
            bar.progress(min(1.0, cur / max(total, 1)),
                         text=f"{stage} — {cur}/{total}")

        result = apply_repair(rep, on_progress=progress)
        bar.empty()

        st.session_state["clean_done"] = result
        st.session_state.pop("clean_plan", None)

        _clean_report(result)


def _clean_report(done: dict) -> None:
    """Το αποτέλεσμα — με ειλικρινή αριθμητική."""
    st.divider()

    if done.get("complete"):
        c.note(
            f"<b>Ολοκληρώθηκε.</b><br>"
            f"• {done['filled']} γραμμές πήραν αριθμό<br>"
            f"• {done['deleted']} διπλές σβήστηκαν<br><br>"
            f"Πάτα <b>«Νέος έλεγχος»</b> για επαλήθευση — αν όλα πήγαν καλά, "
            f"θα πει «το Sheet είναι ήδη καθαρό».",
            "ok",
        )
    else:
        c.note(
            f"<b>Δεν ολοκληρώθηκε.</b><br>"
            f"Πέρασαν: {done['filled']} γεμίσματα · {done['deleted']} διαγραφές<br><br>"
            f"<b>Τίποτα δεν χάθηκε.</b> Πάτα «Νέος έλεγχος» — θα συνεχίσει "
            f"από εκεί που έμεινε.",
            "warn",
        )

        for e in done.get("errors", []):
            if "Quota" in e or "429" in e:
                c.note(
                    "Το Google έκοψε τη σύνδεση (όριο 60 εγγραφών/λεπτό). "
                    "Περίμενε ένα λεπτό και ξαναδοκίμασε.",
                    "bad",
                )
                break
            c.note(e, "bad")

    if st.button("Νέος έλεγχος", key="cl_reset", width="stretch"):
        st.session_state.pop("clean_done", None)
        st.session_state.pop("clean_plan", None)


def _password() -> str:
    try:
        return st.secrets.get("EMAIL_PASS", "")
    except Exception:
        return ""
