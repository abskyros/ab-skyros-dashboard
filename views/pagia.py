"""
views/pagia.py — Πάγια έξοδα (μισθοδοσία, δώρα, συμπληρωματικές, ΕΦΚΑ/ΤΕΚΑ,
ΕΦΚΑ εταίρων, ΑΑΔΕ).

Έρχονται ΑΥΤΟΜΑΤΑ από τα email του λογιστή (core/pagia.py → φύλλο «pagia»).
  • Επόμενες πληρωμές: ό,τι έχει έρθει και δεν έχει λήξει ακόμη
  • Ανά μήνα: ένας μήνας ανά γραμμή, μία στήλη ανά είδος, σύνολα έτους
    και σύγκριση με την προηγούμενη χρονιά

Μισθοδοσία & ΕΦΚΑ/ΤΕΚΑ μπαίνουν στον μήνα ΑΝΑΦΟΡΑΣ (π.χ. «Οκτώβριος 2026»,
ας πληρώνονται τον Νοέμβριο)· η ΑΑΔΕ στον μήνα ΛΗΞΗΣ (εκεί δεν υπάρχει άλλος).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.pagia import KINDS
from core.metrics import month_name
from ui import components as c


def render(df: pd.DataFrame, today: date) -> None:
    if df.empty:
        c.empty(
            "Δεν υπάρχουν πάγια ακόμη",
            "Έρχονται αυτόματα από τα email του λογιστή. Για πρώτη φορά πάτα "
            "«Ενημέρωση» → «Ανάκτηση παγίων (από 2024)».",
        )
        _manual_editor(today)
        _providers(df)
        _run_report()
        return

    _upcoming(df, today)
    _aade_debt()

    years = sorted({int(r[:4]) for r in df["ref"].astype(str) if r[:4].isdigit()}, reverse=True)
    col, _ = st.columns([1, 2])
    with col:
        year = st.selectbox("Έτος", years, index=years.index(today.year) if today.year in years else 0,
                            key="pagia_year")
    _warnings(df, year)
    _year_table(df, year, today)
    _details(df, year)
    _manual_editor(today)
    _providers(df)
    _run_report()


def _manual_editor(today: date) -> None:
    """
    ΧΕΙΡΟΚΙΝΗΤΑ ΠΑΓΙΑ (ΦΠΑ, ενοίκιο, ρεύμα, ασφάλειες…): τα γράφεις εσύ, μία φορά,
    με επανάληψη. Φύλλο «pagia_manual» — δεν το αγγίζει ποτέ η ανάκτηση.
    Κάθε όνομα γίνεται δική του στήλη στον πίνακα ανά μήνα.
    """
    from core.pagia import FREQS
    from core.sheets import add_pagia_manual, load_pagia_manual

    items = load_pagia_manual()
    with st.expander(f"Χειροκίνητα πάγια ({len(items)}) — ΦΠΑ, ενοίκιο, ρεύμα, ασφάλειες…"):
        msg = st.session_state.pop("pagia_manual_msg", None)
        if msg:
            c.note(msg, "ok")
        with st.form("pagia_manual_add", clear_on_submit=True):
            a, b, f = st.columns([2, 1, 1.4])
            name = a.text_input("Όνομα", placeholder="π.χ. ΦΠΑ, Ενοίκιο, ΔΕΗ")
            amount = b.number_input("Ποσό (€)", min_value=0.0, step=10.0, format="%.2f")
            freq = f.selectbox("Επανάληψη", list(FREQS))
            y1, m1, d1 = st.columns(3)
            years = list(range(today.year - 2, today.year + 2))
            sy = y1.selectbox("Πρώτος μήνας — έτος", years, index=years.index(today.year))
            sm = m1.selectbox("Πρώτος μήνας", list(range(1, 13)), index=today.month - 1,
                              format_func=month_name)
            day = d1.number_input("Μέρα πληρωμής (0 = τέλος μήνα)", min_value=0, max_value=31, value=0)
            e1, e2, e3 = st.columns(3)
            has_end = e1.checkbox("Μέχρι κάποιον μήνα")
            ey = e2.selectbox("Τελευταίος — έτος", years + [today.year + 2], index=years.index(today.year))
            em = e3.selectbox("Τελευταίος μήνας", list(range(1, 13)), index=11, format_func=month_name)
            note = st.text_input("Σημείωση (προαιρετικά)")
            if st.form_submit_button("➕ Προσθήκη", type="primary"):
                if not name.strip() or amount <= 0:
                    st.error("Γράψε όνομα και ποσό.")
                elif has_end and (ey, em) < (sy, sm):
                    st.error("Ο τελευταίος μήνας είναι πριν από τον πρώτο.")
                else:
                    add_pagia_manual({"name": name.strip(), "amount": amount, "freq": freq,
                                      "start": f"{sy:04d}-{sm:02d}",
                                      "end": f"{ey:04d}-{em:02d}" if has_end else "",
                                      "day": int(day) or "", "note": note})
                    st.session_state["pagia_manual_msg"] = f"Προστέθηκε: <b>{name.strip()}</b> {c.eur(amount)} · {freq}"
                    st.rerun()
        if not items:
            st.caption("Δεν έχεις βάλει ακόμη χειροκίνητα πάγια.")
            return
        st.caption("«Κάθε μήνα» χωρίς τελευταίο μήνα = μπαίνει κάθε μήνα μέχρι να το σταματήσεις. "
                   "«Αλλαγή» → νέο ποσό από κάποιον μήνα, λήξη ή διαγραφή.")
        cur = f"{today.year:04d}-{today.month:02d}"
        for it in sorted(items, key=lambda x: (x["name"], x["start"])):
            ym = lambda v: _ref_label(v) if v else "χωρίς τέλος"  # noqa: E731
            day_s = f"μέρα {it['day']}" if str(it.get("day") or "").strip() else "τέλος μήνα"
            ended = bool(it.get("end")) and it["end"] < cur
            col1, col2 = st.columns([5, 1.3])
            col1.markdown(("~~" if ended else "") + f"**{it['name']}** · {c.eur(it['amount'])} · {it['freq']} · "
                          f"από {ym(it['start'])} έως {ym(it['end'])} · {day_s}" + ("~~" if ended else "")
                          + (f" · _{it['note']}_" if it.get("note") else ""))
            with col2.popover("Αλλαγή", width="stretch"):
                _manual_change(it, today)


def _providers(df: pd.DataFrame) -> None:
    """
    ΠΑΡΟΧΟΙ ΜΕ EMAIL (ρεύμα, τηλέφωνο, νερό…): δηλώνεις αποστολέα → «🔍 Αναζήτηση»
    → το GitHub διαβάζει ΟΛΑ τα email του από τον Ιανουάριο 2024 (κείμενο + PDF) και
    καταχωρεί κάθε λογαριασμό· μετά κάθε βράδυ τους καινούργιους (core/bills.py).
    Αλλαγή παρόχου: «⏸ Απενεργοποίηση» στον παλιό (το ιστορικό μένει, η Πρόβλεψη
    σταματά να τον υπολογίζει) και προσθήκη του νέου.
    """
    from core.github import available as gh_available, trigger_workflow
    from core.sheets import add_provider, load_providers

    provs = load_providers()
    act = sum(1 for p in provs if p["active"])
    with st.expander(f"Πάροχοι με email ({act} ενεργοί" + (f" · {len(provs) - act} σε παύση" if len(provs) > act else "")
                     + ") — ρεύμα, τηλέφωνο… διαβάζονται αυτόματα"):
        msg = st.session_state.pop("pagia_prov_msg", None)
        if msg:
            c.note(*msg)
        with st.form("pagia_prov_add", clear_on_submit=True):
            a, b = st.columns([1, 1.6])
            name = a.text_input("Όνομα (στήλη)", placeholder="π.χ. Ρεύμα, Τηλέφωνο")
            email = b.text_input("Email αποστολέα", placeholder="π.χ. mynrg@my-nrg.gr")
            m1, m2 = st.columns([1.6, 1])
            must = m1.text_input("Μόνο αν περιέχει (προαιρετικό)",
                                 placeholder="π.χ. NOVA — αν ο αποστολέας στέλνει για πολλές εταιρείες")
            days = m2.number_input("Μέρες προθεσμίας αν δεν γράφει λήξη", min_value=0, max_value=90, value=15)
            if st.form_submit_button("➕ Προσθήκη παρόχου", type="primary"):
                email = email.strip().lower()
                if not name.strip() or "@" not in email or " " in email:
                    st.error("Γράψε όνομα και σωστό email αποστολέα.")
                else:
                    add_provider({"name": name, "email": email, "must": must, "days": days})
                    st.session_state["pagia_prov_msg"] = (
                        f"Προστέθηκε <b>{name.strip()}</b> — ενεργός. Πάτα <b>«🔍 Αναζήτηση»</b> δίπλα του "
                        "για τους λογαριασμούς από τον Ιανουάριο 2024· τους επόμενους τους πιάνει μόνο του κάθε βράδυ.",
                        "ok")
                    st.rerun()
        if not provs:
            st.caption("Π.χ. «Ρεύμα» → mynrg@my-nrg.gr · «Τηλέφωνο» → epsilondigital-info@epsilonnet.gr "
                       "με «Μόνο αν περιέχει: NOVA». Το ποσό μπαίνει στον μήνα λήξης.")
            return
        st.caption("Διαβάζει κείμενο email + PDF (όχι συνδέσμους που θέλουν κωδικό). Ποσό: «Πληρωτέο», "
                   "«Συνολικό ποσό»… · Λήξη: «λήξης», «Εξόφληση έως»… (αλλιώς έκδοση + μέρες). "
                   "Λάθος ποσό → ✎ διόρθωση. Αλλαγή παρόχου → «Αλλαγή» → Απενεργοποίηση.")
        for p in sorted(provs, key=lambda x: (not x["active"], x["name"])):
            sub = df[(df["kind"] == p["name"]) & df["sub"].astype(str).str.startswith("№ ")]                 if not df.empty else df
            last = sub.sort_values("pay_date").iloc[-1] if not sub.empty else None
            info = (f"{len(sub)} λογαριασμοί · τελευταίος {c.eur(float(last['amount']))} "
                    f"λήξη {last['pay_date']:%d/%m/%Y}" if last is not None and pd.notna(last["pay_date"])
                    else "κανένας λογαριασμός ακόμη")
            col1, col2, col3 = st.columns([4.2, 1.3, 1.1])
            col1.markdown(("⏸ ~~" if not p["active"] else "")
                          + f"**{p['name']}** · {p['email']}" + ("~~ (σε παύση)" if not p["active"] else "")
                          + (f" · μόνο με «{p['must']}»" if p.get("must") else "")
                          + f" · _{info}_")
            res = str(p.get("result") or "")
            if res:
                col1.caption(("⏳ " if res.startswith("⏳") else "🔍 ")
                             + f"{p.get('searched') or ''} — {res.lstrip('⏳ ')}")
            elif p["active"]:
                col1.caption("Δεν έχει γίνει αναζήτηση ακόμη — πάτα «🔍 Αναζήτηση».")
            if p["active"] and col2.button("🔍 Αναζήτηση", key=f"prov_search_{p['id']}", width="stretch",
                                           help="Όλα τα email του από τον Ιανουάριο 2024 ως σήμερα (λίγα λεπτά)"):
                st.session_state["pagia_prov_msg"] = _start_bills(p["id"], p["name"], gh_available, trigger_workflow)
                st.rerun()
            with col3.popover("Αλλαγή", width="stretch"):
                _provider_change(p)


def _start_bills(iid: str, name: str, gh_available, trigger_workflow) -> tuple:
    """«🔍 Αναζήτηση»: ξεκινάει στο GitHub την ανάγνωση από τον Ιανουάριο 2024 → (μήνυμα, είδος)."""
    from datetime import datetime as _dt
    from core.config import PAGIA_FROM
    from core.sheets import set_provider_fields
    if not gh_available():
        return (f"<b>{name}</b>: η αναζήτηση γίνεται από το GitHub → «Λογαριασμοί παρόχων» → Run workflow "
                f"(provider = {iid}). Τους επόμενους τους πιάνει μόνο του κάθε βράδυ.", "warn")
    days = (date.today() - date.fromisoformat(PAGIA_FROM)).days + 1
    ok, msg = trigger_workflow("bills_sync.yml", inputs={"provider": iid, "days": str(days)})
    if ok:
        set_provider_fields(iid, {"searched": _dt.now().strftime("%d/%m/%Y %H:%M"),
                                  "result": "⏳ αναζήτηση σε εξέλιξη στο GitHub (λίγα λεπτά)"})
        return (f"<b>{name}</b>: ξεκίνησε η αναζήτηση από {date.fromisoformat(PAGIA_FROM):%m/%Y} ως σήμερα "
                "(λίγα λεπτά). Μετά ανανέωσε τη σελίδα — δίπλα στον πάροχο θα γράφει τι βρέθηκε.", "ok")
    return (f"<b>{name}</b>: η αναζήτηση δεν ξεκίνησε: {msg}", "bad")


def _provider_change(p: dict) -> None:
    from core.sheets import delete_provider, set_provider_active

    st.markdown(f"**{p['name']}**")
    if st.button("⏸ Απενεργοποίηση (άλλαξα πάροχο)" if p["active"] else "▶ Ενεργοποίηση",
                 key=f"prov_act_{p['id']}", width="stretch",
                 help="Σταματά να διαβάζει νέα email και να τον υπολογίζει στην Πρόβλεψη· οι παλιοί λογαριασμοί μένουν"
                 if p["active"] else "Ξαναρχίζει να διαβάζει τα νέα email του"):
        set_provider_active(p["id"], not p["active"])
        st.session_state["pagia_prov_msg"] = (
            (f"<b>{p['name']}</b>: σε παύση — οι παλιοί λογαριασμοί μένουν, η Πρόβλεψη δεν τον υπολογίζει πια."
             if p["active"] else f"<b>{p['name']}</b>: ενεργός ξανά."), "ok")
        st.rerun()
    if st.button("Διαγραφή (κρατά τους παλιούς λογαριασμούς)", key=f"prov_del_{p['id']}", width="stretch"):
        delete_provider(p["id"])
        st.session_state["pagia_prov_msg"] = (f"Διαγράφηκε ο πάροχος <b>{p['name']}</b>.", "ok")
        st.rerun()
    if st.button("Διαγραφή ΜΑΖΙ με τους λογαριασμούς", key=f"prov_delall_{p['id']}", width="stretch"):
        delete_provider(p["id"], with_bills=True)
        st.session_state["pagia_prov_msg"] = (f"Διαγράφηκε ο <b>{p['name']}</b> και οι λογαριασμοί του.", "ok")
        st.rerun()


def _manual_change(it: dict, today: date) -> None:
    """
    ΑΛΛΑΓΗ χειροκίνητου παγίου ΧΩΡΙΣ να πειράζονται οι παλιοί μήνες:
      • Νέο ποσό από μήνα Χ → το παλιό λήγει τον μήνα πριν, νέο από τον Χ
      • Λήξη → τελευταίος μήνας ο Χ (οι προηγούμενοι μένουν)
      • Διαγραφή → φεύγει από ΟΛΟΥΣ τους μήνες
    """
    from core.sheets import add_pagia_manual, delete_pagia_manual, update_pagia_manual

    iid = it["id"]
    st.markdown(f"**{it['name']}**")
    years = list(range(today.year - 2, today.year + 3))
    y1, m1 = st.columns(2)
    y = y1.selectbox("Έτος", years, index=years.index(today.year), key=f"pmc_y_{iid}")
    m = m1.selectbox("Μήνας", list(range(1, 13)), index=today.month - 1,
                     format_func=month_name, key=f"pmc_m_{iid}")
    ref = f"{y:04d}-{m:02d}"
    amount = st.number_input("Νέο ποσό (€)", min_value=0.0, step=10.0, format="%.2f",
                             value=float(it["amount"]), key=f"pmc_a_{iid}")
    if st.button("Νέο ποσό από αυτόν τον μήνα", key=f"pmc_amt_{iid}", width="stretch"):
        if amount <= 0:
            st.error("Γράψε ποσό.")
            return
        if ref <= it["start"]:                      # από την αρχή → απλή αλλαγή ποσού
            update_pagia_manual(iid, {"amount": amount})
        else:
            pk = y * 12 + m - 2                      # μήνας πριν
            update_pagia_manual(iid, {"end": f"{pk // 12:04d}-{pk % 12 + 1:02d}"})
            add_pagia_manual({**it, "amount": amount, "start": ref})
        st.session_state["pagia_manual_msg"] = (f"<b>{it['name']}</b>: {c.eur(amount)} "
                                                f"από {_ref_label(ref)}")
        st.rerun()
    if st.button("Λήξη — τελευταίος μήνας αυτός", key=f"pmc_end_{iid}", width="stretch"):
        if ref < it["start"]:
            st.error("Ο μήνας είναι πριν από τον πρώτο μήνα.")
            return
        update_pagia_manual(iid, {"end": ref})
        st.session_state["pagia_manual_msg"] = f"<b>{it['name']}</b>: λήγει {_ref_label(ref)}"
        st.rerun()
    if st.button("Διαγραφή από όλους τους μήνες", key=f"pmc_del_{iid}", width="stretch"):
        delete_pagia_manual(iid)
        st.session_state["pagia_manual_msg"] = f"Διαγράφηκε: <b>{it['name']}</b>"
        st.rerun()


def _run_report() -> None:
    """
    ΑΝΑΦΟΡΑ ΑΝΑΚΤΗΣΗΣ — τι διάβασε σε ΚΑΘΕ email του λογιστή: αρχεία, τι βγήκε
    από το καθένα (ή «δεν αναγνωρίστηκε»), ποσά και έλεγχοι (φύλλο «pagia_log»).
    """
    import html
    try:
        from core.sheets import load_pagia_log
        log = load_pagia_log()
    except Exception:
        return
    if log.empty:
        return
    from core.pagia import ignore_reason

    def mark(files: str) -> str:
        """«x.png: δεν αναγνωρίστηκε» → «x.png: δεν χρειάζεται (εικόνα…)» για τα άσχετα."""
        out = []
        for ln in str(files or "").splitlines():
            if ln.endswith(": δεν αναγνωρίστηκε"):
                why = ignore_reason(ln[: -len(": δεν αναγνωρίστηκε")])
                if why:
                    ln = ln[: -len("δεν αναγνωρίστηκε")] + f"δεν χρειάζεται ({why})"
            out.append(ln)
        return "\n".join(out)

    log = log.copy()
    log["files"] = log["files"].map(mark)
    log = log.sort_values("email_date")
    months = sorted({str(d)[:7] for d in log["email_date"] if str(d)[:7]}, reverse=True)
    unknown = log["files"].astype(str).str.count("δεν αναγνωρίστηκε").sum()
    skipped = log["files"].astype(str).str.count("δεν χρειάζεται").sum()
    warn = log["found"].astype(str).str.count("⚠").sum()
    with st.expander(f"Αναφορά ανάκτησης — {len(log)} email"
                     + (f" · ⚠ {warn}" if warn else "")
                     + (f" · {unknown} αρχεία ΔΕΝ διαβάστηκαν" if unknown else " · όλα τα χρήσιμα διαβάστηκαν")):
        st.caption(f"{skipped} συνημμένα δεν χρειάζονται (υπογραφές, συμβάσεις, φορολογικά, myDATA…) — "
                   "φαίνονται με γκρι.")
        st.caption(f"Τελευταία ανάκτηση: {log['run_at'].max() or '—'} · μήνας = μήνας ΑΠΟΣΤΟΛΗΣ του email")
        only = st.toggle("Μόνο όσα θέλουν προσοχή (⚠ ή αρχείο που δεν αναγνωρίστηκε)", key="pagia_log_only")
        m = st.selectbox("Μήνας email", ["Όλοι"] + months,
                         format_func=lambda x: x if x == "Όλοι" else _ref_label(x), key="pagia_log_month")
        sub = log if m == "Όλοι" else log[log["email_date"].astype(str).str.startswith(m)]
        if only:
            sub = sub[sub["files"].astype(str).str.contains("δεν αναγνωρίστηκε")
                      | sub["found"].astype(str).str.contains("⚠")]
        if sub.empty:
            st.caption("Τίποτα εδώ.")
            return

        def lines(txt, color=None):
            out = []
            for ln in str(txt or "").splitlines():
                e = html.escape(ln)
                if "⚠" in ln or "δεν αναγνωρίστηκε" in ln:
                    e = f'<span style="color:#b45309"><b>{e}</b></span>'
                elif "δεν χρειάζεται" in ln:
                    e = f'<span style="opacity:.45">{e}</span>'
                elif color:
                    e = f'<span style="color:{color}">{e}</span>'
                out.append(e)
            return "<br>".join(out)

        cards = []
        for _, r in sub.iloc[::-1].iterrows():
            body = (f'<b>{html.escape(str(r["email_date"]))}</b> · {html.escape(str(r["subject"]) or "(χωρίς θέμα)")}'
                    + (f'<div style="margin-top:4px">📎 {lines(r["files"])}</div>' if r["files"] else "")
                    + (f'<div style="margin-top:4px">→ {lines(r["found"])}</div>' if r["found"]
                       else '<div style="margin-top:4px;opacity:.6">→ κανένα ποσό</div>')
                    + (f'<div style="margin-top:4px">! {lines(r["notes"], "#b45309")}</div>' if r["notes"] else ""))
            cards.append(f'<div style="border-bottom:1px solid rgba(128,128,128,.25);padding:8px 0;'
                         f'font-size:.86rem;line-height:1.45">{body}</div>')
        st.markdown("".join(cards[:300]), unsafe_allow_html=True)
        if len(cards) > 300:
            st.caption(f"Εμφανίζονται τα 300 πιο πρόσφατα από {len(cards)} — διάλεξε μήνα.")


def _warnings(df: pd.DataFrame, year: int) -> None:
    """Μισθοδοσίες που ΔΕΝ συμφωνούν με τα σύνολα των αρχείων τους — πάνω-πάνω."""
    if "check" not in df.columns:
        return
    bad = df[df["check"].astype(str).str.startswith("⚠")
             & df["ref"].astype(str).str.startswith(str(year))]
    for _, r in bad.sort_values("ref").iterrows():
        c.note(f"⚠ <b>{r['kind']} {_ref_label(r['ref'])}{' · ' + r['sub'] if r['sub'] else ''}</b>: "
               f"{str(r['check'])[2:]}", "warn")


def _details(df: pd.DataFrame, year: int) -> None:
    """
    ΛΕΠΤΟΜΕΡΕΙΕΣ ΜΗΝΑ — από πού βγήκε κάθε ποσό (θέμα email · αρχεία ·
    πόσοι εργαζόμενοι). Για να εντοπίζονται γρήγορα λάθη ή διπλά.
    """
    sub = df[df["ref"].astype(str).str.startswith(str(year))]
    months = [f"{year:04d}-{mm:02d}" for mm in range(12, 0, -1)]
    have = set(sub["ref"].astype(str))
    today = date.today()
    cur = f"{today.year:04d}-{today.month:02d}"
    first = (months.index(cur) if cur in months
             else next((i for i, x in enumerate(months) if x in have), 0))
    with st.expander("Λεπτομέρειες μήνα — από πού βγήκε κάθε ποσό · ✎ διόρθωση"):
        m = st.selectbox("Μήνας", months, index=first, format_func=_ref_label, key=f"pagia_detail_month_{year}")
        rows = sub[sub["ref"] == m].sort_values(["kind", "pay_date"])
        _detail_rows(rows)
        _fix_editor(df, m)


def _detail_rows(rows: pd.DataFrame) -> None:
    if rows.empty:
        st.caption("Τίποτα καταχωρημένο αυτόν τον μήνα.")
        return
    lines = []
    for _, r in rows.iterrows():
        n_emp = len([x for x in str(r.get("emps", "") or "").split(",") if x])
        chk = str(r.get("check", "") or "")
        chk_html = (f'<br><span style="color:#b45309"><b>{chk}</b></span>' if chk.startswith("⚠")
                    else (f'<br><span style="opacity:.7">{chk}</span>' if chk else ""))
        pay = f"{r['pay_date']:%d/%m/%Y}" if pd.notna(r["pay_date"]) else "—"
        if bool(r.get("paid", False)):
            pay += " ✓ προπληρώθηκε"
        lines.append(
            f'<tr><td class="day"><b>{r["kind"]}</b>'
            f'{" · " + str(r["sub"]) if str(r.get("sub", "") or "") else ""}</td>'
            f'<td class="v now">{c.eur(float(r["amount"]))}</td>'
            f'<td class="v then">{pay}</td>'
            f'<td class="v then">{n_emp or ""}</td>'
            f'<td class="v then" style="text-align:left">{r.get("detail", "")}<br>'
            f'<span style="opacity:.7">{r.get("source", "")}</span>{chk_html}</td></tr>'
        )
    c.html(
        '<div class="tbl3-wrap"><table class="tbl3"><thead><tr>'
        '<th class="day">Είδος</th><th class="now">Ποσό</th><th class="then">Πληρωμή</th>'
        '<th class="then">Εργαζ.</th><th class="then">Από πού</th></tr></thead>'
        f'<tbody>{"".join(lines)}</tbody></table></div>'
    )


def _fix_editor(df: pd.DataFrame, ref: str) -> None:
    """
    ✎ ΔΙΟΡΘΩΣΗ ΜΕ ΤΟ ΧΕΡΙ — όταν το σύστημα δεν διάβασε σωστά ένα ποσό. Η διόρθωση
    ΑΝΤΙΚΑΘΙΣΤΑ ό,τι υπάρχει για (μήνας, είδος) — φύλλο «pagia_fix», δεν το αγγίζει
    καμία ανάκτηση. Σβήνεις τη διόρθωση → γυρνάει το αυτόματο.
    """
    from core.sheets import delete_pagia_fix, load_pagia_fix, save_pagia_fix

    st.markdown(f"**✎ Διόρθωση — {_ref_label(ref)}**")
    msg = st.session_state.pop("pagia_fix_msg", None)
    if msg:
        c.note(msg, "ok")
    for f in [f for f in load_pagia_fix() if f["ref"] == ref]:
        a, b = st.columns([5, 1.3])
        pay = f" · πληρωμή {'/'.join(reversed(f['pay_date'].split('-')))}" if f.get("pay_date") else ""
        a.markdown(f"✎ **{f['kind']}** = {c.eur(f['amount'])}{pay}"
                   + (f" · _{f['note']}_" if f.get("note") else ""))
        if b.button("Αναίρεση", key=f"pfix_del_{f['id']}", width="stretch"):
            delete_pagia_fix(iid=f["id"])
            st.session_state["pagia_fix_msg"] = f"Αναιρέθηκε η διόρθωση: <b>{f['kind']}</b> — γύρισε το αυτόματο."
            st.rerun()
    kinds = list(KINDS) + sorted(set(df["kind"].astype(str)) - set(KINDS))
    with st.form(f"pagia_fix_{ref}", clear_on_submit=True):
        a, b = st.columns([1.4, 1])
        kind = a.selectbox("Είδος", kinds)
        amount = b.number_input("Σωστό ποσό (€) — 0 = δεν υπάρχει", min_value=0.0, step=10.0, format="%.2f")
        p1, p2 = st.columns([1, 1.4])
        has_pay = p1.checkbox("Με ημερομηνία πληρωμής")
        pay = p2.date_input("Πληρωμή", value=date(int(ref[:4]), int(ref[5:7]), 1), format="DD/MM/YYYY")
        note = st.text_input("Σημείωση (π.χ. «από το PDF του λογιστή»)")
        if st.form_submit_button("✎ Αποθήκευση διόρθωσης", type="primary"):
            save_pagia_fix(ref, kind, amount, f"{pay:%Y-%m-%d}" if has_pay else "", note)
            st.session_state["pagia_fix_msg"] = (f"Διορθώθηκε: <b>{kind}</b> {_ref_label(ref)} = "
                                                 f"{c.eur(amount)}")
            st.rerun()
    st.caption("Η διόρθωση αντικαθιστά το ποσό αυτού του είδους για αυτόν τον μήνα (και στη σελίδα «Μήνας»). "
               "Καμία ανάκτηση δεν τη σβήνει· «Αναίρεση» → γυρνάει το αυτόματο.")


# ══════════════════════════════════════════════════════════════════════════════
def _upcoming(df: pd.DataFrame, today: date) -> None:
    """Ό,τι έχει έρθει και πληρώνεται από σήμερα ΕΩΣ ΤΟ ΤΕΛΟΣ ΤΟΥ ΜΗΝΑ (τα πιο μακρινά:
    μόνο μια γραμμή με πλήθος και σύνολο)."""
    from core.pagia import ALREADY_PAID
    month_end = pd.Timestamp(today) + pd.offsets.MonthEnd(0)
    paid = df["paid"].astype(bool) if "paid" in df.columns else pd.Series(False, index=df.index)
    ahead_all = df[df["pay_date"].notna() & (df["pay_date"] >= pd.Timestamp(today))
                   & ~df["kind"].isin(ALREADY_PAID) & (df["amount"] > 0)]  # συμπληρωματικές = ήδη πληρωμένες
    prepaid = ahead_all[paid.loc[ahead_all.index]]
    ahead = ahead_all[~paid.loc[ahead_all.index]]                # «✓ Πληρώθηκε» → έξω
    up = ahead[ahead["pay_date"] <= month_end].sort_values("pay_date")
    later = ahead[ahead["pay_date"] > month_end].sort_values("pay_date")
    msg = st.session_state.pop("pagia_paid_msg", None)
    if up.empty and later.empty and prepaid.empty and not msg:
        return
    c.section("Επόμενες πληρωμές")
    if msg:
        c.note(msg, "ok")
    if up.empty:
        if not later.empty:
            c.html(f'<div style="font-size:.85rem;margin:.3rem 0 1rem">Τίποτα ως το τέλος του μήνα · '
                   f'+ {len(later)} αργότερα: <b>{c.eur(float(later["amount"].sum()))}</b></div>')
    else:
        cards, groups = [], []
        # Ίδιο είδος + ίδια μέρα = μία κάρτα (π.χ. ΕΦΚΑ + ΤΕΚΑ, ή οι δύο εταίροι).
        for (kind, when_ts), grp in up.groupby(["kind", "pay_date"], sort=False):
            when = when_ts.date()
            days = (when - today).days
            badge = "σήμερα" if days == 0 else ("αύριο" if days == 1 else f"σε {days} μέρες")
            refs = " · ".join(sorted({_ref_label(r) for r in grp["ref"]}))
            detail = " + ".join(str(x) for x in grp["detail"] if str(x))
            cards.append(c.kpi(f"{kind} · {refs}", float(grp["amount"].sum()),
                               badge=badge, foot=f"Πληρωμή {when:%d/%m/%Y} · {detail}"))
            groups.append((f"{kind} {when:%d/%m}", grp))
        total = float(up["amount"].sum())
        c.grid(*cards, cols=min(len(cards), 3))
        extra = (f' · + {len(later)} αργότερα: {c.eur(float(later["amount"].sum()))}'
                 if not later.empty else "")
        c.html(f'<div style="font-size:.85rem;margin:.3rem 0 .4rem">Σύνολο ως {month_end:%d/%m}: '
               f'<b>{c.eur(total)}</b>{extra}</div>')
        # ✓ ΠΛΗΡΩΘΗΚΕ — όταν πληρώνεις νωρίτερα από τη λήξη (φεύγει και από την Πρόβλεψη).
        cols = st.columns(min(len(groups), 3))
        for i, (label, grp) in enumerate(groups):
            if cols[i % len(cols)].button(f"✓ Πληρώθηκε · {label}", key=f"paid_{i}_{label}",
                                          width="stretch"):
                _mark_paid(grp, label)
    _paid_tools(later, prepaid)


def _mark_paid(grp: pd.DataFrame, label: str) -> None:
    from core.sheets import mark_pagia_paid
    mark_pagia_paid([{"kind": r["kind"], "ref": r["ref"], "sub": r.get("sub", ""),
                      "amount": r["amount"], "pay_date": r["pay_date"]} for _, r in grp.iterrows()])
    st.session_state["pagia_paid_msg"] = (f"<b>{label}</b> σημειώθηκε ως πληρωμένο — "
                                          "βγήκε από τις επόμενες πληρωμές και την Πρόβλεψη.")
    st.rerun()


def _paid_tools(later: pd.DataFrame, prepaid: pd.DataFrame) -> None:
    """Προπληρωμή και πιο μακρινών πληρωμών + λίστα προπληρωμένων με «Αναίρεση»."""
    from core.sheets import paid_key, unmark_pagia_paid
    if later.empty and prepaid.empty:
        return
    n_pre = prepaid.groupby(["kind", "pay_date"]).ngroups if not prepaid.empty else 0
    title = "Προπληρωμή άλλης πληρωμής" + (f" · ✓ {n_pre} προπληρωμένα" if n_pre else "")
    with st.expander(title):
        if not later.empty:
            opts = {}
            for (kind, when_ts), grp in later.groupby(["kind", "pay_date"], sort=False):
                opts[f"{kind} · {when_ts:%d/%m/%Y} · {c.eur(float(grp['amount'].sum()))}"] = \
                    (f"{kind} {when_ts:%d/%m}", grp)
            a, b = st.columns([3, 1.3])
            pick = a.selectbox("Επόμενη πληρωμή", list(opts), key="paid_later_pick",
                               label_visibility="collapsed")
            if b.button("✓ Πληρώθηκε", key="paid_later_go", width="stretch"):
                _mark_paid(opts[pick][1], opts[pick][0])
        if not prepaid.empty:
            st.caption("Προπληρωμένα (δεν μετράνε στις επόμενες πληρωμές και την Πρόβλεψη):")
            groups = prepaid.sort_values("pay_date").groupby(["kind", "pay_date"], sort=False)
            for i, ((kind, when_ts), grp) in enumerate(groups):
                x, y = st.columns([4, 1.3])
                x.markdown(f"✓ **{kind}** · {c.eur(float(grp['amount'].sum()))} · λήξη {when_ts:%d/%m/%Y}")
                if y.button("Αναίρεση", key=f"paid_undo_{i}", width="stretch"):
                    unmark_pagia_paid([paid_key(r["kind"], r["ref"], r.get("sub", ""), r["pay_date"])
                                       for _, r in grp.iterrows()])
                    st.session_state["pagia_paid_msg"] = f"Αναιρέθηκε: <b>{kind}</b> — ξαναμπήκε στις επόμενες."
                    st.rerun()


def _aade_debt() -> None:
    """Συνολική οφειλή στην ΑΑΔΕ — από την πιο πρόσφατη κατάσταση «Οφειλές προς το Δημόσιο»."""
    import json
    try:
        from core.sheets import load_setting
        d = json.loads(load_setting("aade_debt", "") or "{}")
    except Exception:
        return
    if not d.get("date"):
        return
    day = "/".join(reversed(str(d["date"]).split("-")))
    c.html(f'<div style="font-size:.85rem;margin:-.4rem 0 1rem">Οφειλή ΑΑΔΕ στις {day}: '
           f'<b>{c.eur(float(d.get("total") or 0))}</b> '
           f'(εκτός ρύθμισης {c.eur(float(d.get("out") or 0))} · '
           f'σε ρύθμιση {c.eur(float(d.get("in") or 0))})</div>')


def _ref_label(ref: str) -> str:
    try:
        y, m = int(ref[:4]), int(ref[5:7])
        return f"{month_name(m)} {y}"
    except (ValueError, TypeError):
        return str(ref)


def _year_table(df: pd.DataFrame, year: int, today: date) -> None:
    """Μήνες × είδη, με σύνολο έτους και την προηγούμενη χρονιά από κάτω."""
    def month_sum(y: int, m: int, kind: str) -> float | None:
        sub = df[(df["ref"] == f"{y:04d}-{m:02d}") & (df["kind"] == kind)]
        return float(sub["amount"].sum()) if not sub.empty else None

    from core.sheets import FIX_SOURCE
    kinds = list(KINDS) + sorted(set(df["kind"].astype(str)) - set(KINDS))   # + χειροκίνητα
    fixed = set(zip(df.loc[df["source"] == FIX_SOURCE, "ref"].astype(str),
                    df.loc[df["source"] == FIX_SOURCE, "kind"].astype(str)))   # ✎ διορθώσεις
    head = "".join(f'<th class="now">{k}</th>' for k in kinds)
    body, totals, ly_totals = [], {k: 0.0 for k in kinds}, {k: 0.0 for k in kinds}
    for m in range(1, 13):
        vals = [month_sum(year, m, k) for k in kinds]
        ly = [month_sum(year - 1, m, k) for k in kinds]
        if all(v is None for v in vals) and (year, m) > (today.year, today.month):
            continue
        for k, v, lv in zip(kinds, vals, ly):
            totals[k] += v or 0
            ly_totals[k] += lv or 0
        row_sum = sum(v or 0 for v in vals)
        ly_sum = sum(v or 0 for v in ly)
        ref_m = f"{year:04d}-{m:02d}"
        cells = "".join(f'<td class="v now">{"✎ " if (ref_m, k) in fixed else ""}{c.eur(v)}</td>'
                        for k, v in zip(kinds, vals))
        warn = "check" in df.columns and df[(df["ref"] == f"{year:04d}-{m:02d}")
                                             & df["check"].astype(str).str.startswith("⚠")].shape[0] > 0
        body.append(
            f'<tr><td class="day"><b>{month_name(m)}</b>{" ⚠" if warn else ""}</td>{cells}'
            f'<td class="v now"><b>{c.eur(row_sum or None)}</b></td>'
            f'<td class="v then">{c.eur(ly_sum or None)}</td></tr>'
        )

    tot_cells = "".join(f'<td class="v now"><b>{c.eur(totals[k] or None)}</b></td>' for k in kinds)
    ly_cells = "".join(f'<td class="v then">{c.eur(ly_totals[k] or None)}</td>' for k in kinds)
    grand, ly_grand = sum(totals.values()), sum(ly_totals.values())
    foot = (
        f'<tr style="border-top:2px solid currentColor"><td class="day"><b>Σύνολο {year}</b></td>'
        f'{tot_cells}<td class="v now"><b>{c.eur(grand or None)}</b></td>'
        f'<td class="v then"><b>{c.eur(ly_grand or None)}</b></td></tr>'
        f'<tr><td class="day">{year - 1}</td>{ly_cells}'
        f'<td class="v then">{c.eur(ly_grand or None)}</td><td class="v then"></td></tr>'
    )
    c.section(f"Ανά μήνα · {year}")
    c.html(
        '<div class="tbl3-wrap"><table class="tbl3">'
        f'<thead><tr><th class="day">Μήνας</th>{head}<th class="now">Σύνολο</th>'
        f'<th class="then">Σύνολο {year - 1}</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody><tfoot>{foot}</tfoot></table></div>'
    )
    st.caption("Μισθοδοσία, δώρα, συμπληρωματικές, ΕΦΚΑ και λογιστής: στον μήνα που αφορούν "
               "(συνήθως πληρώνονται τον επόμενο). ΑΑΔΕ: στον μήνα λήξης. "
               "Χειροκίνητα (π.χ. ΦΠΑ) και πάροχοι (ρεύμα, τηλέφωνο): στον μήνα πληρωμής/λήξης τους. "
               "✎ = διόρθωση με το χέρι («Λεπτομέρειες μήνα»).")
