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
            years = list(range(today.year - 2, today.year + 3))
            end_years = list(range(today.year - 2, today.year + 16))   # λήξη: έως 15 χρόνια μπροστά
            sy = y1.selectbox("Πρώτος μήνας — έτος", years, index=years.index(today.year))
            sm = m1.selectbox("Πρώτος μήνας", list(range(1, 13)), index=today.month - 1,
                              format_func=month_name)
            day = d1.number_input("Μέρα πληρωμής (0 = τέλος μήνα)", min_value=0, max_value=31, value=0)
            e1, e2, e3 = st.columns(3)
            has_end = e1.checkbox("Μέχρι κάποιον μήνα")
            ey = e2.selectbox("Τελευταίος — έτος", end_years, index=end_years.index(today.year))
            em = e3.selectbox("Τελευταίος μήνας", list(range(1, 13)), index=11, format_func=month_name)
            n1, n2 = st.columns([1.3, 1])
            rf = n1.text_input("Κωδικός πληρωμής RF (προαιρετικά)", placeholder="π.χ. RF12 3456 7890 …")
            note = n2.text_input("Σημείωση (προαιρετικά)")
            if st.form_submit_button("➕ Προσθήκη", type="primary"):
                if not name.strip() or amount <= 0:
                    st.error("Γράψε όνομα και ποσό.")
                elif has_end and (ey, em) < (sy, sm):
                    st.error("Ο τελευταίος μήνας είναι πριν από τον πρώτο.")
                else:
                    add_pagia_manual({"name": name.strip(), "amount": amount, "freq": freq,
                                      "start": f"{sy:04d}-{sm:02d}",
                                      "end": f"{ey:04d}-{em:02d}" if has_end else "",
                                      "day": int(day) or "", "note": note,
                                      "rf": " ".join(rf.upper().split())})
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
                          + (f" · _{it['note']}_" if it.get("note") else "")
                          + (f" · RF **{it['rf']}**" if it.get("rf") else ""))
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
            rf = str(p.get("rf") or "").strip() or _rf_of(sub.sort_values("pay_date").tail(1))
            if rf:
                col1.caption(f"Κωδικός πληρωμής: **{rf}**" + ("" if p.get("rf") else " (από τον λογαριασμό)"))
            if p["active"] and col2.button("🔍 Αναζήτηση", key=f"prov_search_{p['id']}", width="stretch",
                                           help="Όλα τα email του από τον Ιανουάριο 2024 ως σήμερα (λίγα λεπτά)"):
                st.session_state["pagia_prov_msg"] = _start_bills(p["id"], p["name"], gh_available, trigger_workflow)
                st.rerun()
            with col3.popover("Αλλαγή", width="stretch"):
                _provider_change(p)
            if not sub.empty and st.toggle(f"📂 Λογαριασμοί {p['name']} ({len(sub)})", key=f"prov_hist_{p['id']}"):
                _bill_history(sub)


def _bill_history(sub: pd.DataFrame) -> None:
    """Όλοι οι λογαριασμοί ενός παρόχου: περίοδος · λήξη · ποσό · κατάσταση · email + σύνολα ανά έτος."""
    import re
    today = pd.Timestamp(date.today())
    rows = []
    for _, r in sub.sort_values("pay_date", ascending=False).iterrows():
        det = str(r.get("detail") or "")
        per = re.search(r"περίοδος ([^·]+)", det)
        sup = re.search(r"παροχή ([^·]+)", det)
        if bool(r.get("paid", False)):
            state = "✓ προπληρώθηκε"
        elif pd.notna(r["pay_date"]) and r["pay_date"] >= today:
            state = "επόμενη"
        else:
            state = "πληρωμένος (έληξε)"
        ed = r.get("email_date")
        rows.append({"Περίοδος": per.group(1).strip() if per else "",
                     "Λήξη": f"{r['pay_date']:%d/%m/%Y}" if pd.notna(r["pay_date"]) else "—",
                     "Ποσό": c.eur(float(r["amount"])), "Κατάσταση": state,
                     "Παροχή": sup.group(1).strip() if sup else "",
                     "RF": _rf_of(pd.DataFrame([r])),
                     "Email": (f"{ed:%d/%m/%Y} · " if pd.notna(ed) and hasattr(ed, "strftime") else "")
                              + str(r.get("source") or "").replace("πάροχος · ", "")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    yr = sub[sub["pay_date"].notna()].groupby(sub["pay_date"].dt.year)["amount"].agg(["sum", "count"])
    st.caption(" · ".join(f"{int(y)}: {c.eur(float(s))} ({int(n)} λογ., μ.ό. {c.eur(float(s) / n)})"
                          for y, (s, n) in yr.sort_index(ascending=False).iterrows()))


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
    """ΚΑΡΤΕΛΑ παρόχου: όλα τα στοιχεία σε μία φόρμα → «Αποθήκευση»· από κάτω παύση/διαγραφή."""
    from core.sheets import delete_provider, rename_provider_bills, set_provider_active, set_provider_fields

    pid = p["id"]
    with st.form(f"prov_edit_{pid}", border=False):
        st.markdown(f"**Καρτέλα · {p['name']}**")
        name = st.text_input("Όνομα (στήλη)", value=p["name"])
        email = st.text_input("Email αποστολέα", value=p["email"])
        must = st.text_input("Μόνο αν περιέχει", value=str(p.get("must") or ""))
        a, b = st.columns(2)
        days = a.number_input("Μέρες προθεσμίας", min_value=0, max_value=90, value=int(p.get("days") or 15))
        rf = b.text_input("Κωδικός πληρωμής RF", value=str(p.get("rf") or ""))
        if st.form_submit_button("Αποθήκευση", type="primary", width="stretch"):
            email = email.strip().lower()
            if not name.strip() or "@" not in email or " " in email:
                st.error("Γράψε όνομα και σωστό email αποστολέα.")
            else:
                set_provider_fields(pid, {"name": name.strip()[:40], "email": email, "must": must.strip(),
                                          "days": int(days), "rf": " ".join(rf.upper().split())})
                moved = rename_provider_bills(p["name"], name.strip()[:40]) if name.strip() != p["name"] else 0
                st.session_state["pagia_prov_msg"] = (
                    f"<b>{name.strip()}</b>: αποθηκεύτηκε" + (f" · {moved} λογαριασμοί πήραν το νέο όνομα" if moved else ""),
                    "ok")
                st.rerun()
    if st.button("⏸ Απενεργοποίηση (άλλαξα πάροχο)" if p["active"] else "▶ Ενεργοποίηση",
                 key=f"prov_act_{pid}", width="stretch",
                 help="Σταματά να διαβάζει νέα email και να τον υπολογίζει στην Πρόβλεψη· οι παλιοί λογαριασμοί μένουν"
                 if p["active"] else "Ξαναρχίζει να διαβάζει τα νέα email του"):
        set_provider_active(pid, not p["active"])
        st.session_state["pagia_prov_msg"] = (
            (f"<b>{p['name']}</b>: σε παύση — οι παλιοί λογαριασμοί μένουν, η Πρόβλεψη δεν τον υπολογίζει πια."
             if p["active"] else f"<b>{p['name']}</b>: ενεργός ξανά."), "ok")
        st.rerun()
    d1, d2 = st.columns(2)
    if d1.button("Διαγραφή", key=f"prov_del_{pid}", width="stretch", help="Οι παλιοί λογαριασμοί μένουν"):
        delete_provider(pid)
        st.session_state["pagia_prov_msg"] = (f"Διαγράφηκε ο πάροχος <b>{p['name']}</b>.", "ok")
        st.rerun()
    if d2.button("Διαγραφή + λογαριασμοί", key=f"prov_delall_{pid}", width="stretch"):
        delete_provider(pid, with_bills=True)
        st.session_state["pagia_prov_msg"] = (f"Διαγράφηκε ο <b>{p['name']}</b> και οι λογαριασμοί του.", "ok")
        st.rerun()


def _manual_change(it: dict, today: date) -> None:
    """
    ΚΑΡΤΕΛΑ χειροκίνητου παγίου: ΟΛΑ τα στοιχεία σε μία φόρμα → «Αποθήκευση»
    (ισχύει για όλους τους μήνες του). Από κάτω:
      • Νέο ποσό από μήνα Χ → οι παλιοί μήνες κρατούν το παλιό ποσό
      • Διαγραφή → φεύγει από ΟΛΟΥΣ τους μήνες
    """
    from core.pagia import FREQS
    from core.sheets import add_pagia_manual, delete_pagia_manual, update_pagia_manual

    iid = it["id"]
    years = list(range(today.year - 3, today.year + 16))       # λήξη: έως 15 χρόνια μπροστά

    def ym(v, dy, dm):
        try:
            y, m = (int(x) for x in str(v).split("-")[:2])
            return (y if y in years else dy), m
        except (ValueError, TypeError):
            return dy, dm

    sy, sm = ym(it.get("start"), today.year, today.month)
    ey, em = ym(it.get("end"), today.year, 12)
    freqs = list(FREQS)
    with st.form(f"pm_edit_{iid}", border=False):
        st.markdown(f"**Καρτέλα · {it['name']}**")
        name = st.text_input("Όνομα", value=it["name"])
        a, b = st.columns(2)
        amount = a.number_input("Ποσό (€)", min_value=0.0, step=10.0, format="%.2f", value=float(it["amount"]))
        freq = b.selectbox("Επανάληψη", freqs, index=freqs.index(it["freq"]) if it["freq"] in freqs else 1)
        a, b, d = st.columns(3)
        sy = a.selectbox("Πρώτο έτος", years, index=years.index(sy))
        sm = b.selectbox("Πρώτος μήνας", list(range(1, 13)), index=sm - 1, format_func=month_name)
        day = d.number_input("Μέρα (0 = τέλος)", min_value=0, max_value=31, value=int(it.get("day") or 0))
        a, b, d = st.columns(3)
        has_end = a.checkbox("Έχει τέλος", value=bool(it.get("end")))
        ey = b.selectbox("Τελευταίο έτος", years, index=years.index(ey))
        em = d.selectbox("Τελευταίος μήνας", list(range(1, 13)), index=em - 1, format_func=month_name)
        a, b = st.columns(2)
        rf = a.text_input("Κωδικός πληρωμής RF", value=str(it.get("rf") or ""))
        note = b.text_input("Σημείωση", value=str(it.get("note") or ""))
        if st.form_submit_button("Αποθήκευση", type="primary", width="stretch"):
            if not name.strip() or amount <= 0:
                st.error("Γράψε όνομα και ποσό.")
            elif has_end and (ey, em) < (sy, sm):
                st.error("Ο τελευταίος μήνας είναι πριν από τον πρώτο.")
            else:
                update_pagia_manual(iid, {"name": name.strip(), "amount": amount, "freq": freq,
                                          "start": f"{sy:04d}-{sm:02d}",
                                          "end": f"{ey:04d}-{em:02d}" if has_end else "",
                                          "day": int(day) or "", "note": note,
                                          "rf": " ".join(rf.upper().split())})
                st.session_state["pagia_manual_msg"] = f"<b>{name.strip()}</b>: αποθηκεύτηκε"
                st.rerun()
    with st.form(f"pm_new_amount_{iid}", border=False):
        st.caption("Νέο ποσό ΑΠΟ κάποιον μήνα (οι προηγούμενοι κρατούν το παλιό):")
        a, b, d = st.columns(3)
        ny = a.selectbox("Έτος", years, index=years.index(today.year))
        nm = b.selectbox("Μήνας", list(range(1, 13)), index=today.month - 1, format_func=month_name)
        na = d.number_input("Νέο ποσό", min_value=0.0, step=10.0, format="%.2f", value=float(it["amount"]))
        if st.form_submit_button("Νέο ποσό από αυτόν τον μήνα", width="stretch"):
            ref = f"{ny:04d}-{nm:02d}"
            if na <= 0:
                st.error("Γράψε ποσό.")
            else:
                if ref <= it["start"]:
                    update_pagia_manual(iid, {"amount": na})
                else:
                    pk = ny * 12 + nm - 2
                    update_pagia_manual(iid, {"end": f"{pk // 12:04d}-{pk % 12 + 1:02d}"})
                    add_pagia_manual({**it, "amount": na, "start": ref})
                st.session_state["pagia_manual_msg"] = f"<b>{it['name']}</b>: {c.eur(na)} από {_ref_label(ref)}"
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


def _warn_key(r) -> str:
    """Ταυτότητα ειδοποίησης = είδος · μήνας · υποκατηγορία · ΚΕΙΜΕΝΟ ελέγχου (αν αλλάξει
    το αποτέλεσμα, π.χ. ήρθε το αρχείο που έλειπε → νέα ειδοποίηση, ξαναφαίνεται)."""
    import hashlib
    raw = f"{r['kind']}|{r['ref']}|{r.get('sub', '')}|{r.get('check', '')}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _warn_seen() -> set:
    import json
    try:
        from core.sheets import load_setting
        return set(json.loads(load_setting("pagia_warn_seen", "") or "[]"))
    except Exception:
        return set()


def _warn_save(seen: set) -> None:
    import json
    from core.sheets import save_setting
    save_setting("pagia_warn_seen", json.dumps(sorted(seen)))


def _warnings(df: pd.DataFrame, year: int) -> None:
    """Μισθοδοσίες που ΔΕΝ συμφωνούν με τα σύνολα των αρχείων τους — πάνω-πάνω.
    «✓ Το είδα» → κρύβεται (και το ⚠ του μήνα στον πίνακα)· «Εμφάνιση κρυμμένων» → πίσω."""
    if "check" not in df.columns:
        return
    bad = df[df["check"].astype(str).str.startswith("⚠")
             & df["ref"].astype(str).str.startswith(str(year))]
    if bad.empty:
        return
    seen = _warn_seen()
    hidden = 0
    for _, r in bad.sort_values("ref").iterrows():
        k = _warn_key(r)
        if k in seen:
            hidden += 1
            continue
        a, b = st.columns([6, 1.2])
        with a:
            c.note(f"⚠ <b>{r['kind']} {_ref_label(r['ref'])}{' · ' + r['sub'] if r['sub'] else ''}</b>: "
                   f"{str(r['check'])[2:]}", "warn")
        if b.button("✓ Το είδα", key=f"warn_seen_{k}", width="stretch"):
            _warn_save(seen | {k})
            st.rerun()
    if hidden and st.toggle(f"Κρυμμένες ειδοποιήσεις: {hidden} · εμφάνιση", key=f"warn_show_{year}"):
        for _, r in bad.sort_values("ref").iterrows():
            k = _warn_key(r)
            if k not in seen:
                continue
            a, b = st.columns([6, 1.2])
            a.caption(f"✓ {r['kind']} {_ref_label(r['ref'])}: {str(r['check'])[2:]}")
            if b.button("Επαναφορά", key=f"warn_back_{k}", width="stretch"):
                _warn_save(seen - {k})
                st.rerun()


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
# Χρώμα ανά κατηγορία (επόμενες πληρωμές + πίνακας ανά μήνα).
KIND_COLORS = {"Μισθοδοσία": "#185FA5", "Δώρα/Επιδόματα": "#C2185B", "Συμπληρωματική": "#0E7490",
               "ΕΦΚΑ/ΤΕΚΑ": "#534AB7", "ΕΦΚΑ εταίρων": "#7E57C2", "ΑΑΔΕ": "#D85A30",
               "Λογιστής": "#5F5E5A", "ΦΠΑ": "#A32D2D"}
PROVIDER_COLOR, MANUAL_COLOR, OTHER_COLOR = "#0F8A6A", "#B7791F", "#64748B"


def _kind_color(kind: str, providers: set | None = None) -> str:
    if kind in KIND_COLORS:
        return KIND_COLORS[kind]
    if providers is None:
        try:
            from core.sheets import load_providers
            providers = {p["name"] for p in load_providers()}
        except Exception:
            providers = set()
    return PROVIDER_COLOR if kind in providers else MANUAL_COLOR


HORIZONS = {"Αυτός ο μήνας": 0, "+ επόμενος": 1, "+ 2 μήνες": 2, "+ 3 μήνες": 3, "6 μήνες": 5}


def _rf_of(grp: pd.DataFrame) -> str:
    """Κωδικός πληρωμής RF: από το πεδίο «rf» (χειροκίνητα/πάροχοι) ή από τον λογαριασμό."""
    import re
    for col in ("rf", "sub", "detail"):
        if col in grp.columns:
            for v in grp[col]:
                m = re.search(r"RF\s?\d[\d ]{6,30}\d", str(v or "").upper())
                if m:
                    return re.sub(r"\s", "", m.group(0))
    return ""


def _upcoming(df: pd.DataFrame, today: date) -> None:
    """
    ΕΠΟΜΕΝΕΣ ΠΛΗΡΩΜΕΣ — ό,τι έχει έρθει ή είναι δηλωμένο (αυτόματα, χειροκίνητα,
    πάροχοι) από σήμερα ως όσους μήνες μπροστά διαλέξεις, ΑΝΑ ΜΗΝΑ. Κάθε κάρτα έχει
    «✓ Πληρώθηκε» (προπληρωμή → έξω από εδώ και από την Πρόβλεψη).
    """
    from core.pagia import ALREADY_PAID
    paid = df["paid"].astype(bool) if "paid" in df.columns else pd.Series(False, index=df.index)
    ahead_all = df[df["pay_date"].notna() & (df["pay_date"] >= pd.Timestamp(today))
                   & ~df["kind"].isin(ALREADY_PAID) & (df["amount"] > 0)]  # συμπληρωματικές = ήδη πληρωμένες
    prepaid = ahead_all[paid.loc[ahead_all.index]]
    ahead = ahead_all[~paid.loc[ahead_all.index]].sort_values("pay_date")   # «✓ Πληρώθηκε» → έξω
    msg = st.session_state.pop("pagia_paid_msg", None)
    if ahead.empty and prepaid.empty and not msg:
        return
    c.section("Επόμενες πληρωμές")
    if msg:
        c.note(msg, "ok")
    h = st.segmented_control("Μπροστά", list(HORIZONS), default="+ επόμενος", key="pagia_horizon",
                             label_visibility="collapsed") or "+ επόμενος"
    k = today.year * 12 + today.month - 1 + HORIZONS[h]
    end = pd.Timestamp(date(k // 12, k % 12 + 1, 1)) + pd.offsets.MonthEnd(0)
    shown = ahead[ahead["pay_date"] <= end]
    later = ahead[ahead["pay_date"] > end]
    if shown.empty:
        c.html('<div style="font-size:.85rem;margin:.3rem 0 .6rem">Τίποτα σε αυτό το διάστημα.</div>')
    try:
        from core.sheets import load_providers
        provs = {p["name"] for p in load_providers()}
    except Exception:
        provs = set()
    for ym, mon in shown.groupby(shown["pay_date"].dt.strftime("%Y-%m"), sort=True):
        y, m = int(ym[:4]), int(ym[5:7])
        c.html(f'<div class="pg-mh"><span>{month_name(m)} {y}</span>'
               f'<span>{c.eur(float(mon["amount"].sum()))}</span></div>')
        # Ίδιο είδος + ίδια μέρα = μία γραμμή (π.χ. ΕΦΚΑ + ΤΕΚΑ, ή οι δύο εταίροι).
        for i, ((kind, when_ts), grp) in enumerate(mon.groupby(["kind", "pay_date"], sort=False)):
            when = when_ts.date()
            days = (when - today).days
            badge = "σήμερα" if days == 0 else ("αύριο" if days == 1 else f"σε {days} μ.")
            refs = " · ".join(sorted({_ref_label(r) for r in grp["ref"]}))
            detail = " + ".join(str(x) for x in grp["detail"] if str(x))
            rf = _rf_of(grp)
            sub = " · ".join(x for x in (refs, detail, rf) if x)
            label = f"{kind} {when:%d/%m}"
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                c.html(f'<div class="pg-row"><span class="dot" style="background:{_kind_color(kind, provs)}"></span>'
                       f'<span><b>{kind}</b><span class="pg-sub">{sub}</span></span>'
                       f'<span class="pg-when">{when:%d/%m}<br>{badge}</span>'
                       f'<span class="pg-amt" data-when="{when:%d/%m} · {badge}">'
                       f'{c.eur(float(grp["amount"].sum()))}</span></div>')
                if st.button("✓", key=f"paid_{ym}_{i}", help=f"Πληρώθηκε νωρίτερα: {label} — "
                             "φεύγει από τις επόμενες πληρωμές και την Πρόβλεψη"):
                    _mark_paid(grp, label)
    if not shown.empty:
        extra = (f' · + {len(later)} αργότερα: {c.eur(float(later["amount"].sum()))}'
                 if not later.empty else "")
        c.html(f'<div style="font-size:.85rem;margin:.5rem 0 .4rem">Σύνολο ως {end:%d/%m/%Y}: '
               f'<b>{c.eur(float(shown["amount"].sum()))}</b>{extra}</div>')
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
    try:
        from core.sheets import load_providers
        provs = {p["name"] for p in load_providers()}
    except Exception:
        provs = set()
    col = {k: _kind_color(k, provs) for k in kinds}        # χρώμα ανά κατηγορία
    head = "".join(f'<th class="k" style="background:{col[k]}">{k}</th>' for k in kinds)
    seen = _warn_seen()                       # «✓ Το είδα» → χωρίς ⚠ στον μήνα
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
        cells = "".join(f'<td class="v now" style="background:{col[k]}14;'
                        f'">{"✎ " if (ref_m, k) in fixed else ""}{c.eur(v)}</td>'
                        for k, v in zip(kinds, vals))
        warn = "check" in df.columns and any(
            _warn_key(r) not in seen for _, r in df[(df["ref"] == ref_m)
                                                    & df["check"].astype(str).str.startswith("⚠")].iterrows())
        body.append(
            f'<tr><td class="day"><b>{month_name(m)}</b>{" ⚠" if warn else ""}</td>{cells}'
            f'<td class="v now"><b>{c.eur(row_sum or None)}</b></td>'
            f'<td class="v then">{c.eur(ly_sum or None)}</td></tr>'
        )

    tot_cells = "".join(f'<td class="v now" style="background:{col[k]}33">'
                        f'<b>{c.eur(totals[k] or None)}</b></td>' for k in kinds)
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
        '<div class="tbl3-wrap pg-wrap"><table class="tbl3 pg">'
        f'<thead><tr><th class="day">Μήνας</th>{head}<th class="now">Σύνολο</th>'
        f'<th class="then">Σύνολο {year - 1}</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody><tfoot>{foot}</tfoot></table></div>'
    )
    st.caption("Μισθοδοσία, δώρα, συμπληρωματικές, ΕΦΚΑ και λογιστής: στον μήνα που αφορούν "
               "(συνήθως πληρώνονται τον επόμενο). ΑΑΔΕ: στον μήνα λήξης. "
               "Χειροκίνητα (π.χ. ΦΠΑ) και πάροχοι (ρεύμα, τηλέφωνο): στον μήνα πληρωμής/λήξης τους. "
               "✎ = διόρθωση με το χέρι («Λεπτομέρειες μήνα»).")
