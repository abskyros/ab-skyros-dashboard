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
        _run_report()
        return

    _upcoming(df, today)

    years = sorted({int(r[:4]) for r in df["ref"].astype(str) if r[:4].isdigit()}, reverse=True)
    col, _ = st.columns([1, 2])
    with col:
        year = st.selectbox("Έτος", years, index=years.index(today.year) if today.year in years else 0,
                            key="pagia_year")
    _warnings(df, year)
    _year_table(df, year, today)
    _details(df, year)
    _manual_editor(today)
    _run_report()


def _manual_editor(today: date) -> None:
    """
    ΧΕΙΡΟΚΙΝΗΤΑ ΠΑΓΙΑ (ΦΠΑ, ενοίκιο, ρεύμα, ασφάλειες…): τα γράφεις εσύ, μία φορά,
    με επανάληψη. Φύλλο «pagia_manual» — δεν το αγγίζει ποτέ η ανάκτηση.
    Κάθε όνομα γίνεται δική του στήλη στον πίνακα ανά μήνα.
    """
    from core.pagia import FREQS
    from core.sheets import add_pagia_manual, delete_pagia_manual, load_pagia_manual

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
        st.caption("Τα αποθηκευμένα — για αλλαγή: διαγραφή και ξανά προσθήκη.")
        for it in sorted(items, key=lambda x: (x["name"], x["start"])):
            ym = lambda v: _ref_label(v) if v else "χωρίς τέλος"  # noqa: E731
            day_s = f"μέρα {it['day']}" if str(it.get("day") or "").strip() else "τέλος μήνα"
            col1, col2 = st.columns([5, 1])
            col1.markdown(f"**{it['name']}** · {c.eur(it['amount'])} · {it['freq']} · "
                          f"από {ym(it['start'])} έως {ym(it['end'])} · {day_s}"
                          + (f" · _{it['note']}_" if it.get("note") else ""))
            if col2.button("Διαγραφή", key=f"pm_del_{it['id']}"):
                delete_pagia_manual(it["id"])
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
    log = log.sort_values("email_date")
    months = sorted({str(d)[:7] for d in log["email_date"] if str(d)[:7]}, reverse=True)
    unknown = log["files"].astype(str).str.count("δεν αναγνωρίστηκε").sum()
    warn = log["found"].astype(str).str.count("⚠").sum()
    with st.expander(f"Αναφορά ανάκτησης — {len(log)} email"
                     + (f" · ⚠ {warn}" if warn else "") + (f" · {unknown} αρχεία δεν αναγνωρίστηκαν" if unknown else "")):
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
    if sub.empty:
        return
    months = sorted(sub["ref"].unique(), reverse=True)
    with st.expander("Λεπτομέρειες μήνα — από ποιο email βγήκε κάθε ποσό"):
        m = st.selectbox("Μήνας", months, format_func=_ref_label, key="pagia_detail_month")
        rows = sub[sub["ref"] == m].sort_values(["kind", "pay_date"])
        lines = []
        for _, r in rows.iterrows():
            n_emp = len([x for x in str(r.get("emps", "") or "").split(",") if x])
            chk = str(r.get("check", "") or "")
            chk_html = (f'<br><span style="color:#b45309"><b>{chk}</b></span>' if chk.startswith("⚠")
                        else (f'<br><span style="opacity:.7">{chk}</span>' if chk else ""))
            pay = f"{r['pay_date']:%d/%m/%Y}" if pd.notna(r["pay_date"]) else "—"
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


# ══════════════════════════════════════════════════════════════════════════════
def _upcoming(df: pd.DataFrame, today: date) -> None:
    """Ό,τι έχει έρθει και πληρώνεται από σήμερα ΕΩΣ ΤΟ ΤΕΛΟΣ ΤΟΥ ΜΗΝΑ (τα πιο μακρινά:
    μόνο μια γραμμή με πλήθος και σύνολο)."""
    month_end = pd.Timestamp(today) + pd.offsets.MonthEnd(0)
    ahead = df[df["pay_date"].notna() & (df["pay_date"] >= pd.Timestamp(today))]
    up = ahead[ahead["pay_date"] <= month_end].sort_values("pay_date")
    later = ahead[ahead["pay_date"] > month_end]
    if up.empty:
        if not later.empty:
            c.section("Επόμενες πληρωμές")
            c.html(f'<div style="font-size:.85rem;margin:.3rem 0 1rem">Τίποτα ως το τέλος του μήνα · '
                   f'+ {len(later)} αργότερα: <b>{c.eur(float(later["amount"].sum()))}</b></div>')
        return
    c.section("Επόμενες πληρωμές")
    cards = []
    # Ίδιο είδος + ίδια μέρα = μία κάρτα (π.χ. ΕΦΚΑ + ΤΕΚΑ, ή οι δύο εταίροι).
    for (kind, when_ts), grp in up.groupby(["kind", "pay_date"], sort=False):
        when = when_ts.date()
        days = (when - today).days
        badge = "σήμερα" if days == 0 else ("αύριο" if days == 1 else f"σε {days} μέρες")
        refs = " · ".join(sorted({_ref_label(r) for r in grp["ref"]}))
        detail = " + ".join(str(x) for x in grp["detail"] if str(x))
        cards.append(c.kpi(f"{kind} · {refs}", float(grp["amount"].sum()),
                           badge=badge, foot=f"Πληρωμή {when:%d/%m/%Y} · {detail}"))
    total = float(up["amount"].sum())
    c.grid(*cards, cols=min(len(cards), 3))
    extra = (f' · + {len(later)} αργότερα: {c.eur(float(later["amount"].sum()))}'
             if not later.empty else "")
    c.html(f'<div style="font-size:.85rem;margin:.3rem 0 1rem">Σύνολο ως {month_end:%d/%m}: '
           f'<b>{c.eur(total)}</b>{extra}</div>')


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

    kinds = list(KINDS) + sorted(set(df["kind"].astype(str)) - set(KINDS))   # + χειροκίνητα
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
        cells = "".join(f'<td class="v now">{c.eur(v)}</td>' for v in vals)
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
               "Χειροκίνητα (π.χ. ΦΠΑ): στον μήνα πληρωμής τους.")
