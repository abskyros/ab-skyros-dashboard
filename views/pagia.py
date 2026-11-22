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
        return

    _upcoming(df, today)

    years = sorted({int(r[:4]) for r in df["ref"].astype(str) if r[:4].isdigit()}, reverse=True)
    col, _ = st.columns([1, 2])
    with col:
        year = st.selectbox("Έτος", years, index=years.index(today.year) if today.year in years else 0,
                            key="pagia_year")
    _year_table(df, year, today)


# ══════════════════════════════════════════════════════════════════════════════
def _upcoming(df: pd.DataFrame, today: date) -> None:
    """Ό,τι έχει έρθει και πληρώνεται από σήμερα και μετά."""
    up = df[df["pay_date"].notna() & (df["pay_date"] >= pd.Timestamp(today))].sort_values("pay_date")
    if up.empty:
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
    c.html(f'<div style="font-size:.85rem;margin:.3rem 0 1rem">Σύνολο επόμενων πληρωμών: '
           f'<b>{c.eur(total)}</b></div>')


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

    head = "".join(f'<th class="now">{k}</th>' for k in KINDS)
    body, totals, ly_totals = [], {k: 0.0 for k in KINDS}, {k: 0.0 for k in KINDS}
    for m in range(1, 13):
        vals = [month_sum(year, m, k) for k in KINDS]
        ly = [month_sum(year - 1, m, k) for k in KINDS]
        if all(v is None for v in vals) and (year, m) > (today.year, today.month):
            continue
        for k, v, lv in zip(KINDS, vals, ly):
            totals[k] += v or 0
            ly_totals[k] += lv or 0
        row_sum = sum(v or 0 for v in vals)
        ly_sum = sum(v or 0 for v in ly)
        cells = "".join(f'<td class="v now">{c.eur(v)}</td>' for v in vals)
        body.append(
            f'<tr><td class="day"><b>{month_name(m)}</b></td>{cells}'
            f'<td class="v now"><b>{c.eur(row_sum or None)}</b></td>'
            f'<td class="v then">{c.eur(ly_sum or None)}</td></tr>'
        )

    tot_cells = "".join(f'<td class="v now"><b>{c.eur(totals[k] or None)}</b></td>' for k in KINDS)
    ly_cells = "".join(f'<td class="v then">{c.eur(ly_totals[k] or None)}</td>' for k in KINDS)
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
    st.caption("Μισθοδοσία, δώρα, συμπληρωματικές και ΕΦΚΑ: στον μήνα που αφορούν "
               "(συνήθως πληρώνονται τον επόμενο). ΑΑΔΕ: στον μήνα λήξης.")
