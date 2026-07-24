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
    today_greece,
)
from core.sheets import (
    load_invoices, check_quality, delete_row,
    purge_duplicate_invoices, find_double_charges, find_duplicate_numbers,
)
from core.backfill import (
    repair, apply_repair, rebuild_plan, apply_rebuild, audit, snapshot,
)
from core.mail import fetch_all_invoices
from core.github import trigger_workflow, workflow_url, last_run, available as gh_available
from ui import components as c
from ui import charts


def render(df: pd.DataFrame, today: date) -> None:
    if df.empty:
        c.empty(
            "Δεν υπάρχουν παραστατικά ακόμη",
            "Τα παραστατικά έρχονται αυτόματα κάθε 2 ώρες. Για άμεση ενημέρωση, δες το κάτω μέρος."
        )
        return

    weekly, yearly = st.tabs(["Εβδομαδιαία", "Ετήσια"])

    with weekly:
        _weekly(df, today)

    with yearly:
        _yearly(df, today)

    # Προειδοποίηση και εργαλεία ΚΑΤΩ — πρώτα τα δεδομένα, μετά η συντήρηση.
    _health_warning(df)
    _tools(df)


# ══════════════════════════════════════════════════════════════════════════════
def _health_warning(df: pd.DataFrame) -> None:
    """
    Η ΠΡΟΕΙΔΟΠΟΙΗΣΗ ΣΤΗΝ ΚΟΡΥΦΗ.

    Αν το Sheet έχει γραμμές ΧΩΡΙΣ αριθμό παραστατικού, τα σύνολα είναι αναξιόπιστα
    — δεν ξέρουμε ποιες είναι διπλές.

    Δεν το κρύβουμε μέσα σε expander. Ένα λάθος νούμερο που το βλέπεις κάθε μέρα
    και δεν ξέρεις ότι είναι λάθος, είναι χειρότερο από κανένα νούμερο.

    Ο έλεγχος είναι ΦΘΗΝΟΣ — μόνο μέτρημα στηλών, χωρίς κλήσεις δικτύου.
    """
    if "number" not in df.columns:
        return

    blank = df["number"].astype(str).str.strip() == ""
    n = int(blank.sum())

    if n == 0:
        return

    total = len(df)
    pct = n / total * 100

    c.note(
        f"⚠️ <b>{n:,} από τις {total:,} γραμμές δεν έχουν αριθμό παραστατικού</b> "
        f"({pct:.0f}%).<br><br>"
        f"Αυτές είναι παλιές καταχωρήσεις. Δεν ξέρουμε ποιες είναι διπλές — "
        f"άρα <b>τα σύνολα παραπάνω μπορεί να είναι φουσκωμένα</b>.<br><br>"
        f"Άνοιξε τον <b>Έλεγχο δεδομένων → 🔄 Ξαναχτίσιμο</b> για να διορθωθεί. "
        f"Τρέχει μία φορά."
        .replace(",", "."),
        "warn",
    )

    c.spacer(0.4)


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

    cols = {
        "ΗΜΕΡΟΜΗΝΙΑ": t["date"].dt.strftime("%d/%m/%Y"),
        "ΤΥΠΟΣ":      t["type"],
    }

    # Ο ΑΡΙΘΜΟΣ ΠΑΡΑΣΤΑΤΙΚΟΥ — η μοναδική ταυτότητα. Τον δείχνουμε ώστε να
    # μπορείς να δεις με το μάτι αν κάτι επαναλαμβάνεται.
    if "number" in t.columns:
        cols["ΑΡΙΘΜΟΣ"] = t["number"].replace("", "—")

    cols["ΑΞΙΑ"] = t["value"].map(c.eur)

    out = pd.DataFrame(cols)
    st.dataframe(out, width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
def _tools(df: pd.DataFrame) -> None:
    """
    ΤΡΕΙΣ ΚΑΡΤΕΛΕΣ, ΤΡΕΙΣ ΔΟΥΛΕΙΕΣ:

      🧹 ΚΑΘΑΡΙΣΜΟΣ — όλα τα χρόνια, μία φορά. Γεμίζει αριθμούς, σβήνει διπλά.
      ✅ ΕΠΑΛΗΘΕΥΣΗ — μία εβδομάδα, Sheet vs email. Για έλεγχο μετά.
      ⚠️ ΔΙΠΛΕΣ ΧΡΕΩΣΕΙΣ — ίδιο ποσό, ΑΛΛΟΣ αριθμός. Πιθανό λάθος του προμηθευτή.
    """
    # Αν υπάρχουν γραμμές χωρίς αριθμό, το expander ανοίγει ΜΟΝΟ ΤΟΥ.
    # Δεν θέλουμε ο χρήστης να ψάχνει τη λύση σε ένα πρόβλημα που του δείξαμε.
    needs_work = (
        "number" in df.columns
        and (df["number"].astype(str).str.strip() == "").any()
    )

    # ΚΡΙΣΙΜΟ: αν υπάρχει ΕΝΕΡΓΗ διαδικασία (σάρωση, σχέδιο, αποτέλεσμα), το
    # expander ΠΡΕΠΕΙ να μείνει ανοιχτό. Αλλιώς, μετά από κάθε st.rerun() που
    # κάνουν τα κουμπιά μέσα του, ξανακλείνει — και ο χρήστης νομίζει ότι
    # «γύρισε πίσω χωρίς να κάνει τίποτα».
    in_progress = any(
        st.session_state.get(k)
        for k in ("rb_plan", "rb_done", "vf_done", "chg_checked", "dup_checked")
    )

    with st.expander("Έλεγχος δεδομένων", expanded=needs_work or in_progress):
        dup_tab, clean_tab, verify_tab, charge_tab = st.tabs([
            "🔁 Διπλοκαταχωρήσεις (ίδιος αριθμός)",
            "🔄 Ξαναχτίσιμο (όλα τα χρόνια)",
            "✅ Επαλήθευση εβδομάδας",
            "⚠️ Διπλές χρεώσεις",
        ])

        with dup_tab:
            _check_duplicate_numbers(df)

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
        picked = st.date_input("Εβδομάδα", today_greece(), key="vf_day", format="DD/MM/YYYY")

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
        f"παραστατικά.",
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

    # ── Η ΔΙΟΡΘΩΣΗ, ΕΔΩ ΚΑΙ ΤΩΡΑ ──
    #
    # Το παλιό κουμπί έλεγε «Πήγαινε στον καθαρισμό» και έγραφε ένα flag στο
    # session_state που ΚΑΝΕΙΣ ΔΕΝ ΔΙΑΒΑΖΕ. Το Streamlit δεν αλλάζει καρτέλα
    # προγραμματιστικά. Άρα το κουμπί δεν έκανε τίποτα.
    #
    # Τώρα η επισκευή γίνεται ΕΔΩ, για αυτή την εβδομάδα.
    st.divider()
    c.section("Επισκευή αυτής της εβδομάδας")

    with st.spinner("Υπολογισμός…"):
        rep = repair(records, start, end)

    if not rep["fill"] and not rep["delete"]:
        c.note(
            "<b>Δεν βρέθηκε τίποτα να επισκευαστεί.</b><br><br>"
            "Οι γραμμές που περισσεύουν είναι <b>μοναδικές</b> — καμία δεν έχει "
            "ακριβώς ίδιο δίδυμο, και καμία δεν αντιστοιχεί σε email.<br><br>"
            "Πιθανόν έχουν <b>λάθος ποσό</b> (σφάλμα του παλιού συγχρονισμού) ή "
            "καταχωρήθηκαν με το χέρι.",
            "info",
        )
        return

    _repair_ui(rep, key="vf", label="Επισκευή εβδομάδας")


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
# ΔΙΠΛΟΚΑΤΑΧΩΡΗΣΕΙΣ — Ο ΙΔΙΟΣ ΑΡΙΘΜΟΣ ΠΑΝΩ ΑΠΟ ΜΙΑ ΦΟΡΑ
# ══════════════════════════════════════════════════════════════════════════════
def _check_duplicate_numbers(df: pd.DataFrame) -> None:
    """
    🔁 Ο ΙΔΙΟΣ ΑΡΙΘΜΟΣ, ΠΟΛΛΕΣ ΦΟΡΕΣ → σίγουρη διπλοκαταχώρηση.

    Ο αριθμός παραστατικού είναι ΜΟΝΑΔΙΚΟΣ. Αν το ίδιο νούμερο υπάρχει 2+ φορές,
    το παραστατικό μπήκε πολλές φορές. Κρατάμε μία γραμμή, σβήνουμε τις άλλες.

    Αυτό είναι το ΑΣΦΑΛΕΣ σβήσιμο: δεν μαντεύουμε τίποτα — ο αριθμός είναι
    απόδειξη ότι πρόκειται για το ίδιο ακριβώς παραστατικό.
    """
    st.caption(
        "Ψάχνει τον **ίδιο αριθμό παραστατικού** που εμφανίζεται πάνω από μία "
        "φορά. Επειδή ο αριθμός είναι μοναδικός, αυτές είναι **σίγουρες "
        "διπλοκαταχωρήσεις** — μπορούν να σβηστούν με ασφάλεια."
    )

    # Αν μόλις ολοκληρώθηκε διαγραφή, δείξε το αποτέλεσμα.
    done = st.session_state.get("dup_done")
    if done:
        if done.get("deleted"):
            c.note(
                f"<b>Σβήστηκαν {done['deleted']} διπλές γραμμές.</b><br>"
                f"Κάθε παραστατικό έμεινε μία φορά.",
                "ok",
            )
        for e in done.get("errors", []):
            c.note(e, "bad")

        if st.button("Νέος έλεγχος", key="dup_reset", width="stretch"):
            st.session_state.pop("dup_done", None)
            st.session_state.pop("dup_checked", None)
            st.rerun()
        return

    if st.button("Έλεγχος τώρα", key="dup_check", width="stretch", type="primary"):
        st.session_state["dup_checked"] = True

    if not st.session_state.get("dup_checked"):
        return

    with st.spinner("Έλεγχος…"):
        found = find_duplicate_numbers(df)

    if not found:
        c.note(
            "Καμία διπλοκαταχώρηση. Κάθε αριθμός παραστατικού εμφανίζεται "
            "μία μόνο φορά.",
            "ok",
        )
        return

    # Πόσες γραμμές περισσεύουν συνολικά (κρατάμε μία ανά αριθμό).
    extra_rows = sum(f["count"] - 1 for f in found)
    extra_value = sum((f["count"] - 1) * abs(f["value"]) for f in found)

    c.note(
        f"<b>{len(found)} αριθμοί</b> εμφανίζονται πάνω από μία φορά.<br><br>"
        f"Περισσεύουν <b>{extra_rows} γραμμές</b> (αξίας {c.eur(extra_value)}). "
        f"Θα κρατηθεί <b>μία</b> από κάθε αριθμό.",
        "warn",
    )

    # ── Η ΛΙΣΤΑ ──
    for f in found[:40]:
        rows_txt = ", ".join(str(r) for r in f["rows"])
        st.markdown(
            f"**#{f['number']}** — {f['type'][:34]} · **{c.eur(f['value'])}** "
            f"× **{f['count']}**  \
"
            f"<span style='color:#64748B;font-size:.8rem'>"
            f"γραμμές {rows_txt} · {f['dates'][0]}</span>",
            unsafe_allow_html=True,
        )

    if len(found) > 40:
        st.caption(f"…και άλλοι {len(found) - 40} αριθμοί")

    # ── ΤΟ ΣΒΗΣΙΜΟ ──
    #
    # Για κάθε αριθμό, κρατάμε την ΠΡΩΤΗ γραμμή και σβήνουμε τις υπόλοιπες.
    to_delete = []
    for f in found:
        to_delete.extend(f["rows"][1:])   # όλες εκτός της πρώτης

    st.divider()

    # Το Sheets API αντέχει ~60 κλήσεις/λεπτό. Με ~1,2" παύση ανά ομάδα, ένα
    # μεγάλο σβήσιμο μπορεί να ξεπεράσει το όριο ~2 λεπτών του Streamlit Cloud.
    from core.sheets import _group_runs
    runs = len(_group_runs(to_delete))
    seconds = runs * 1.5
    heavy = seconds > 90

    if heavy:
        c.note(
            f"<b>Πολλές γραμμές ({len(to_delete)}).</b><br><br>"
            f"Αυτό θέλει ~{int(seconds // 60) + 1} λεπτά — περισσότερο απ' ό,τι "
            f"αντέχει το Streamlit Cloud. Καλύτερα τρέξε το "
            f"<b>🔄 Ξαναχτίσιμο</b>, που καθαρίζει τα πάντα με ασφάλεια.",
            "info",
        )
        return

    c.note(
        "<b>Κατέβασε αντίγραφο ασφαλείας πριν σβήσεις.</b>",
        "bad",
    )
    st.download_button(
        "Λήψη αντιγράφου (CSV)",
        snapshot().encode("utf-8-sig"),
        "invoices_backup.csv",
        "text/csv",
        key="dup_backup",
        width="stretch",
    )

    confirmed = st.checkbox(
        f"Κατέβασα το αντίγραφο. Σβήσε τις {len(to_delete)} διπλές γραμμές.",
        key="dup_confirm",
    )

    if st.button("Σβήσε τις διπλές", key="dup_apply", width="stretch",
                 type="primary", disabled=not confirmed):
        from core.sheets import delete_rows_safe

        with st.spinner(f"Διαγραφή {len(to_delete)} γραμμών…"):
            deleted, errors = delete_rows_safe("invoices", to_delete)

        st.session_state["dup_done"] = {"deleted": deleted, "errors": errors}
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ΞΑΝΑΧΤΙΣΙΜΟ — ΟΛΑ ΤΑ ΧΡΟΝΙΑ, ΜΙΑ ΦΟΡΑ
# ══════════════════════════════════════════════════════════════════════════════
def _clean_all() -> None:
    """
    ΞΑΝΑΧΤΙΣΙΜΟ — σβήνουμε τα πάντα, ξαναγράφουμε από τα email.

    Τρέχει ΜΙΑ ΦΟΡΑ. Από εδώ και πέρα το data_sync κρατάει το Sheet καθαρό:
    το κλειδί είναι ο αριθμός παραστατικού και δεν αφήνει διπλά να μπουν.
    """
    df = load_invoices()

    if not df.empty and "number" in df.columns:
        blank = int((df["number"].astype(str).str.strip() == "").sum())
        total = len(df)

        if blank:
            c.note(
                f"<b>{blank:,} από τις {total:,} γραμμές δεν έχουν αριθμό "
                f"παραστατικού.</b><br><br>"
                f"Το ξαναχτίσιμο τις αντικαθιστά όλες — κάθε παραστατικό "
                f"γράφεται μία φορά, με τον μοναδικό αριθμό του."
                .replace(",", "."),
                "warn",
            )

    st.caption(
        "Σβήνει **ολόκληρη** τη λίστα παραστατικών και τη ξαναχτίζει από τα "
        "email, με τον **αριθμό παραστατικού** σε κάθε γραμμή."
    )

    with st.expander("Γιατί ξαναχτίσιμο και όχι καθαρισμός"):
        st.markdown(
            "Ο καθαρισμός προσπαθούσε να **μαντέψει** ποιες γραμμές αντιστοιχούν "
            "σε ποια email, ταιριάζοντας ημερομηνία + τύπο + ποσό.\n\n"
            "Αν το ποσό στο Sheet ήταν λάθος (π.χ. από το παλιό `daily_sync.py` "
            "που έγραφε ευρώ αντί λεπτά), το ταίριασμα **αποτύγχανε σιωπηλά**. "
            "Οι γραμμές έμεναν «άγνωστες» και δεν καθαρίζονταν ποτέ.\n\n"
            "---\n\n"
            "**Το ξαναχτίσιμο δεν μαντεύει.**\n\n"
            "Τα email είναι η **πηγή**. Το Sheet είναι απλώς αντίγραφο. Αν το "
            "αντίγραφο έχει σκουπίδια, δεν το «καθαρίζεις» — το **ξαναγράφεις**.\n\n"
            "Κάθε παραστατικό γράφεται μία φορά, με τον μοναδικό αριθμό του. "
            "Τα διπλά **εξαφανίζονται εξ ορισμού** — δεν υπάρχει τρόπος να μπουν."
        )

    pw = _password()
    if not pw:
        c.note("Λείπει το EMAIL_PASS από τα secrets.", "bad")
        return

    done = st.session_state.get("rb_done")
    if done:
        _rebuild_report(done)
        return

    plan = st.session_state.get("rb_plan")

    # ── ΒΗΜΑ 1: ΣΑΡΩΣΗ ──
    if plan is None:
        if st.button("Ξεκίνα σάρωση (όλα τα email)", key="rb_scan",
                     width="stretch", type="primary"):
            bar = st.progress(0.0, text="Σύνδεση στο Gmail…")

            def tick(scanned, found):
                bar.progress(min(0.85, scanned / 500),
                             text=f"{scanned} email · {found} παραστατικά")

            records, errors, scanned = fetch_all_invoices(pw, on_progress=tick)

            if errors:
                bar.empty()
                c.note(errors[0], "bad")
                return

            bar.progress(0.95, text="Προετοιμασία…")
            plan = rebuild_plan(records)
            plan["emails"] = scanned
            bar.empty()

            st.session_state["rb_plan"] = plan
            st.rerun()
        return

    # ── ΒΗΜΑ 2: ΤΟ ΣΧΕΔΙΟ ──
    st.divider()
    c.section("Τι βρέθηκε")

    a, b, d = st.columns(3)
    a.metric("Email", f"{plan.get('emails', 0):,}".replace(",", "."))
    b.metric("Παραστατικά", f"{plan['records']:,}".replace(",", "."))
    d.metric("Μοναδικά", f"{plan['unique']:,}".replace(",", "."))

    if plan["unique"] == 0:
        c.note("Δεν βρέθηκε κανένα παραστατικό με αριθμό. Κάτι πάει στραβά.", "bad")
        if st.button("Νέα σάρωση", key="rb_again", width="stretch"):
            st.session_state.pop("rb_plan", None)
            st.rerun()
        return

    dupes = plan["records"] - plan["unique"]

    c.section("Τι θα γίνει")

    c.note(
        f"🗑 Θα σβηστούν <b>{plan['sheet_rows']:,}</b> γραμμές<br>"
        f"✓ Θα γραφτούν <b>{plan['unique']:,}</b> μοναδικά παραστατικά<br><br>"
        f"Κάθε ένα με τον <b>αριθμό παραστατικού</b> του."
        .replace(",", "."),
        "warn",
    )

    if dupes > 0:
        st.caption(
            f"Στα email βρέθηκαν **{plan['records']:,}** εγγραφές, αλλά μόνο "
            f"**{plan['unique']:,}** μοναδικοί αριθμοί — τα υπόλοιπα "
            f"**{dupes:,}** ήταν το ίδιο παραστατικό σε πολλά email."
            .replace(",", ".")
        )

    removed = plan["sheet_rows"] - plan["unique"]
    if removed > 0:
        st.caption(
            f"Το Sheet θα πάει από **{plan['sheet_rows']:,}** σε "
            f"**{plan['unique']:,}** γραμμές — **{removed:,} λιγότερες**."
            .replace(",", ".")
        )

    # ── ΑΝΤΙΓΡΑΦΟ ──
    st.divider()
    c.section("Πριν προχωρήσεις")

    c.note(
        "<b>Κατέβασε αντίγραφο ασφαλείας.</b><br>"
        "Σβήνεται ΟΛΟΚΛΗΡΗ η λίστα. Αν κάτι πάει στραβά, ξαναγράφεις το φύλλο "
        "από αυτό το αρχείο.",
        "bad",
    )

    st.download_button(
        "Λήψη αντιγράφου (CSV)",
        snapshot().encode("utf-8-sig"),
        "invoices_backup.csv",
        "text/csv",
        key="rb_backup",
        width="stretch",
    )

    confirmed = st.checkbox(
        f"Κατέβασα το αντίγραφο. Σβήσε τις {plan['sheet_rows']:,} γραμμές και "
        f"ξαναγράψε τις {plan['unique']:,}.".replace(",", "."),
        key="rb_confirm",
    )

    # ── ΒΗΜΑ 3: ΕΚΤΕΛΕΣΗ ──
    st.divider()

    batches = (plan["unique"] + 999) // 1000
    seconds = 2 + batches * 1.5

    st.caption(f"Εκτιμώμενος χρόνος: ~{int(seconds)} δευτερόλεπτα.")

    if st.button("Ξαναχτίσιμο", key="rb_apply", width="stretch",
                 type="primary", disabled=not confirmed):

        bar = st.progress(0.0, text="Έναρξη…")

        def progress(stage, cur, total):
            bar.progress(min(1.0, cur / max(total, 1)),
                         text=f"{stage} — {cur}/{total}")

        try:
            result = apply_rebuild(plan, on_progress=progress)
        except Exception as e:
            bar.empty()
            c.note(
                f"<b>Το ξαναχτίσιμο διακόπηκε.</b><br><br>{e}<br><br>"
                f"Δοκίμασε ξανά — τα email είναι πάντα εκεί.",
                "bad",
            )
            return

        bar.empty()

        st.session_state["rb_done"] = result
        st.session_state.pop("rb_plan", None)
        st.rerun()


def _rebuild_report(done: dict) -> None:
    """Το αποτέλεσμα του ξαναχτίσιματος."""
    st.divider()

    if done.get("complete"):
        c.note(
            f"<b>Ολοκληρώθηκε.</b><br>"
            f"• {done['deleted']:,} γραμμές σβήστηκαν<br>"
            f"• {done['written']:,} παραστατικά γράφτηκαν, με αριθμό<br><br>"
            f"Το Sheet είναι πλέον καθαρό. Από εδώ και πέρα τα διπλά δεν "
            f"μπορούν να μπουν — το κλειδί είναι ο αριθμός παραστατικού."
            .replace(",", "."),
            "ok",
        )
    else:
        c.note(
            f"<b>Δεν ολοκληρώθηκε.</b><br>"
            f"Σβήστηκαν: {done['deleted']:,} · Γράφτηκαν: {done['written']:,}<br><br>"
            f"<b>Δοκίμασε ξανά</b> — τα email είναι πάντα εκεί. Αν χρειαστεί, "
            f"ξαναγράψε το φύλλο από το αντίγραφο."
            .replace(",", "."),
            "bad",
        )

        for e in done.get("errors", []):
            c.note(e, "bad")

    if st.button("Νέος έλεγχος", key="rb_reset", width="stretch"):
        st.session_state.pop("rb_done", None)
        st.session_state.pop("rb_plan", None)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Η ΕΠΙΣΚΕΥΗ — ΚΟΙΝΗ ΓΙΑ ΕΠΑΛΗΘΕΥΣΗ ΚΑΙ ΚΑΘΑΡΙΣΜΟ
# ══════════════════════════════════════════════════════════════════════════════
#
# Το Google Sheets επιτρέπει 60 εγγραφές/λεπτό. Κάνουμε παύση 1,2" ανάμεσα.
#
# Άρα:  2.876 διαγραφές × 1,2"  =  ~57 λεπτά
#
# Το Streamlit Cloud σκοτώνει κάθε αίτημα που ξεπερνά ~2 λεπτά.
#
# ┌────────────────────────────────────────────────────────────────────────────┐
# │ ΤΟ BUG ΠΟΥ ΕΦΤΙΑΞΕ ΑΥΤΟ                                                    │
# │                                                                            │
# │ Ο χρήστης πατούσε «Καθαρισμός», η μπάρα ξεκινούσε, και… τίποτα.            │
# │ Το Streamlit το σκότωνε στη μέση. Καμία ένδειξη, κανένα σφάλμα.            │
# │                                                                            │
# │ Τώρα μετράμε τον χρόνο ΠΡΙΝ ξεκινήσουμε:                                   │
# │   • Μικρή δουλειά  → τρέχει εδώ, με μπάρα                                  │
# │   • Μεγάλη δουλειά → ξεκινάει GitHub Action (90 λεπτά timeout)             │
# └────────────────────────────────────────────────────────────────────────────┘

# Πόσα δευτερόλεπτα αντέχει το Streamlit πριν μας κόψει.
SAFE_SECONDS = 90

# Χρόνος ανά ενέργεια (μετρημένος: 1,2" παύση + ~0,3" η ίδια η κλήση)
SEC_PER_BATCH = 1.5     # 500 γεμίσματα ανά batch
SEC_PER_DELETE = 1.5    # μία ομάδα συνεχόμενων γραμμών


def _estimate(rep: dict) -> float:
    """Πόσο θα κρατήσει η επισκευή, σε δευτερόλεπτα."""
    from core.sheets import _group_runs

    batches = (len(rep["fill"]) + 499) // 500
    runs = len(_group_runs(rep["delete"])) if rep["delete"] else 0

    return batches * SEC_PER_BATCH + runs * SEC_PER_DELETE


def _repair_ui(rep: dict, key: str, label: str, show_after: bool = False) -> None:
    """
    Δείχνει το σχέδιο, και το εκτελεί — εδώ ή στο GitHub, ανάλογα με το μέγεθος.
    """
    done = st.session_state.get(f"{key}_done")
    if done:
        _repair_report(done, key)
        return

    c.section("Τι θα γίνει")

    lines = []
    if rep["fill"]:
        lines.append(f"✓ <b>{len(rep['fill'])}</b> γραμμές θα πάρουν τον αριθμό τους")

    if rep["delete"]:
        self_dups = rep.get("self_dups", 0)
        confirmed_dups = len(rep["delete"]) - self_dups

        lines.append(
            f"🗑 <b>{len(rep['delete'])}</b> γραμμές θα <b>σβηστούν</b> "
            f"(αξίας {c.eur(rep['value'])})"
        )

    if rep["keep"]:
        lines.append(
            f"⊘ <b>{len(rep['keep'])}</b> γραμμές <b>δεν πειράζονται</b>"
        )

    c.note("<br>".join(lines), "warn" if rep["delete"] else "info")

    # ── ΤΙ ΣΒΗΝΕΤΑΙ ΚΑΙ ΓΙΑΤΙ ──
    #
    # Δύο διαφορετικές βεβαιότητες. Ο χρήστης πρέπει να ξέρει τη διαφορά —
    # γιατί η μία είναι απόδειξη και η άλλη είναι συμπέρασμα.
    if rep["delete"]:
        self_dups = rep.get("self_dups", 0)
        confirmed = len(rep["delete"]) - self_dups

        with st.expander("Τι ακριβώς σβήνεται;", expanded=True):
            if confirmed:
                st.markdown(
                    f"**{confirmed} — επιβεβαιωμένα από τα email**\n\n"
                    f"Το email λέει ότι η μέρα έχει π.χ. 11 τιμολόγια. "
                    f"Το Sheet έχει 30 γραμμές. Οι 19 περισσεύουν.\n\n"
                    f"*Απόδειξη, όχι εικασία.*"
                )

            if self_dups:
                if confirmed:
                    st.divider()

                st.markdown(
                    f"**{self_dups} — πανομοιότυπες μεταξύ τους**\n\n"
                    f"Ίδια ημερομηνία, ίδιος τύπος, **ίδιο ποσό**, καμία με αριθμό. "
                    f"Δεν βρέθηκαν σε κανένα email — αλλά **δεν μπορεί να είναι "
                    f"όλες σωστές**.\n\n"
                    f"Κρατιέται **μία** από κάθε ομάδα, σβήνονται οι υπόλοιπες.\n\n"
                    f"*Δεν ξέρουμε ποια είναι η αληθινή — αλλά ξέρουμε ότι μόνο "
                    f"μία μπορεί να είναι.*"
                )

    if show_after and rep.get("scanned"):
        after = rep["scanned"] - len(rep["delete"])
        st.caption(
            f"Το Sheet θα πάει από **{rep['scanned']:,}** σε **{after:,}** γραμμές."
            .replace(",", ".")
        )

    seconds = _estimate(rep)
    heavy = seconds > SAFE_SECONDS

    # ── ΑΝΤΙΓΡΑΦΟ ──
    if rep["delete"]:
        st.divider()

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
            key=f"{key}_backup",
            width="stretch",
        )

        confirmed = st.checkbox(
            f"Κατέβασα το αντίγραφο. Θα σβηστούν {len(rep['delete'])} γραμμές.",
            key=f"{key}_confirm",
        )
    else:
        confirmed = True

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # ΜΕΓΑΛΗ ΔΟΥΛΕΙΑ → GITHUB
    # ══════════════════════════════════════════════════════════════════════════
    if heavy:
        mins = int(seconds // 60) + 1

        c.note(
            f"<b>Αυτή η δουλειά θέλει ~{mins} λεπτά.</b><br><br>"
            f"Το Streamlit Cloud κόβει κάθε αίτημα μετά από 2 λεπτά — δεν "
            f"προλαβαίνει.<br><br>"
            f"Τρέχει στο <b>GitHub Actions</b>, όπου υπάρχει χρόνος.",
            "info",
        )

        if not gh_available():
            _github_manual("clean_invoices.yml", key)
            return

        if st.button(f"{label} (στο GitHub)", key=f"{key}_gh",
                     width="stretch", type="primary", disabled=not confirmed):

            ok, msg = trigger_workflow("clean_invoices.yml", inputs={"apply": "yes"})

            if ok:
                st.session_state[f"{key}_done"] = {
                    "github": True,
                    "url": workflow_url("clean_invoices.yml"),
                }
                st.session_state.pop("clean_plan", None)
                st.rerun()
            else:
                c.note(f"Δεν ξεκίνησε: {msg}", "bad")
                _github_manual("clean_invoices.yml", key)
        return

    # ══════════════════════════════════════════════════════════════════════════
    # ΜΙΚΡΗ ΔΟΥΛΕΙΑ → ΕΔΩ
    # ══════════════════════════════════════════════════════════════════════════
    st.caption(f"Εκτιμώμενος χρόνος: ~{int(seconds)} δευτερόλεπτα.")

    if st.button(label, key=f"{key}_apply", width="stretch",
                 type="primary", disabled=not confirmed):

        bar = st.progress(0.0, text="Έναρξη…")

        def progress(stage, cur, total):
            bar.progress(min(1.0, cur / max(total, 1)),
                         text=f"{stage} — {cur}/{total}")

        try:
            result = apply_repair(rep, on_progress=progress)
        except Exception as e:
            bar.empty()
            c.note(
                f"<b>Η επισκευή διακόπηκε.</b><br><br>{e}<br><br>"
                f"Δοκίμασε ξανά — θα συνεχίσει από εκεί που έμεινε.",
                "bad",
            )
            return

        bar.empty()

        st.session_state[f"{key}_done"] = result
        st.session_state.pop("clean_plan", None)
        st.rerun()


def _repair_report(done: dict, key: str) -> None:
    """Το αποτέλεσμα — με ειλικρινή αριθμητική."""
    st.divider()

    # ── Ξεκίνησε στο GitHub ──
    if done.get("github"):
        url = done.get("url", "")
        c.note(
            f"<b>Ο καθαρισμός ξεκίνησε στο GitHub.</b><br><br>"
            f"Θα πάρει μερικά λεπτά. Μπορείς να κλείσεις αυτή τη σελίδα.<br><br>"
            f'<a href="{url}" target="_blank">Δες την πρόοδο →</a>',
            "ok",
        )

        run = last_run("clean_invoices.yml")
        if run:
            status = run.get("status")
            if status in ("queued", "in_progress"):
                st.caption("Τρέχει τώρα…")
            elif run.get("conclusion") == "success":
                c.note("Ολοκληρώθηκε. Ανανέωσε τη σελίδα.", "ok")
            elif run.get("conclusion") == "failure":
                c.note(
                    f'Απέτυχε. <a href="{run.get("url")}" target="_blank">'
                    f'Δες το σφάλμα</a>.',
                    "bad",
                )

        if st.button("Έλεγχος ξανά", key=f"{key}_recheck", width="stretch"):
            st.session_state.pop(f"{key}_done", None)
            st.rerun()
        return

    # ── Έτρεξε εδώ ──
    if done.get("complete"):
        c.note(
            f"<b>Ολοκληρώθηκε.</b><br>"
            f"• {done['filled']} γραμμές πήραν αριθμό<br>"
            f"• {done['deleted']} διπλές σβήστηκαν",
            "ok",
        )
    else:
        c.note(
            f"<b>Δεν ολοκληρώθηκε.</b><br>"
            f"Πέρασαν: {done['filled']} γεμίσματα · {done['deleted']} διαγραφές<br><br>"
            f"<b>Τίποτα δεν χάθηκε.</b> Δοκίμασε ξανά — θα συνεχίσει από εκεί "
            f"που έμεινε.",
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

    if st.button("Νέος έλεγχος", key=f"{key}_reset", width="stretch"):
        st.session_state.pop(f"{key}_done", None)
        st.session_state.pop("clean_plan", None)
        st.rerun()


def _github_manual(workflow: str, key: str) -> None:
    """Όταν λείπει το token — δίνουμε δρόμο, όχι τοίχο."""
    url = workflow_url(workflow)

    c.note(
        f"<b>Κάν' το από το GitHub:</b><br><br>"
        f'1. Άνοιξε <a href="{url}" target="_blank">το workflow</a><br>'
        f"2. <b>Run workflow</b> → <b>apply: yes</b> → <b>Run workflow</b><br>"
        f"3. Σε λίγα λεπτά ανανέωσε αυτή τη σελίδα",
        "warn",
    )

    with st.expander("Ή φτιάξε GitHub token για ένα κλικ"):
        st.markdown(
            "**1. Φτιάξε το token**\n\n"
            "GitHub → Settings → Developer settings → "
            "**Fine-grained tokens** → Generate new token\n\n"
            "| Πεδίο | Τιμή |\n"
            "|---|---|\n"
            "| Repository | `ab-skyros-dashboard` |\n"
            "| Permissions → **Actions** | **Read and write** |\n\n"
            "**2. Streamlit → Settings → Secrets**\n\n"
            "```toml\n"
            'GITHUB_TOKEN = "github_pat_..."\n'
            'GITHUB_REPO  = "abskyros/ab-skyros-dashboard"\n'
            "```"
        )


def _password() -> str:
    try:
        return st.secrets.get("EMAIL_PASS", "")
    except Exception:
        return ""
