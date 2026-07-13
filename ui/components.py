"""
ui/components.py — Τα δομικά κομμάτια της οθόνης.

ΚΑΝΟΝΑΣ: HTML γράφεται ΜΟΝΟ εδώ. Οι σελίδες στο views/ καλούν συναρτήσεις.
Έτσι η αλλαγή εμφάνισης δεν αγγίζει τη λογική, και το αντίστροφο.
"""

from __future__ import annotations

import urllib.parse
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from core.config import PAGES, DEFAULT_PAGE
from core.metrics import pct_change, day_name


# ══════════════════════════════════════════════════════════════════════════════
# ΜΟΡΦΟΠΟΙΗΣΗ
# ══════════════════════════════════════════════════════════════════════════════
def eur(v, dash: str = "—") -> str:
    """1547.7 → «1.547,70 €». Ελληνικό format, χειροκίνητα (το locale δεν είναι αξιόπιστο στο cloud)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return dash

    n = round(float(v), 2)
    whole, dec = f"{abs(n):,.2f}".split(".")
    whole = whole.replace(",", ".")
    sign = "-" if n < 0 else ""

    return f"{sign}{whole},{dec} €"


def num(v, dash: str = "—") -> str:
    """1547 → «1.547»"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return dash
    return f"{int(v):,}".replace(",", ".")


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(page: str, **params) -> str:
    """Σύνδεσμος σε σελίδα. target=_self — αλλιώς σπάει μέσα σε iframe."""
    q = urllib.parse.urlencode({"page": page, **params}, quote_via=urllib.parse.quote)
    return f"?{q}"


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# ΣΚΕΛΕΤΟΣ
# ══════════════════════════════════════════════════════════════════════════════
def load_css() -> None:
    css = (Path(__file__).parent / "style.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def topbar(today: date) -> None:
    stamp = f"{day_name(today)} {today:%d/%m/%Y}"
    html(
        '<div class="topbar">'
        '<div class="brand">'
        '<div class="brand-name">ΑΒ Σκύρος</div>'
        '<div class="brand-sub">Πωλήσεις · Παραστατικά · Τιμολογήσεις</div>'
        '</div>'
        f'<div class="today-stamp">{stamp}</div>'
        '</div>'
    )


def nav(current: str) -> None:
    items = "".join(
        f'<a href="{link(p)}" target="_self" class="{"on" if p == current else ""}">{p}</a>'
        for p in PAGES
    )
    html(f'<nav class="nav">{items}</nav>')


ICONS = {
    "Επισκόπηση": "🏠",
    "Πωλήσεις": "📈",
    "Παραστατικά": "🧾",
    "Τιμολογήσεις": "💳",
    "Μήνας": "📅",
}


def tabbar(current: str) -> None:
    """Πλοήγηση κινητού. Κάτω, όπου φτάνει ο αντίχειρας."""
    items = "".join(
        f'<a href="{link(p)}" target="_self" class="{"on" if p == current else ""}">'
        f'<span class="ico">{ICONS[p]}</span><span>{p}</span></a>'
        for p in PAGES
    )
    html(f'<nav class="tabbar">{items}</nav>')


def title(text: str, subtitle: str = "") -> None:
    html(
        f'<h1 class="page-title">{_esc(text)}</h1>'
        + (f'<p class="page-sub">{_esc(subtitle)}</p>' if subtitle else '<div style="height:1rem"></div>')
    )


def section(label: str) -> None:
    html(f'<div class="eyebrow">{_esc(label)}</div>')


def spacer(rem: float = 1.0) -> None:
    html(f'<div style="height:{rem}rem"></div>')


# ══════════════════════════════════════════════════════════════════════════════
# Η ΖΥΓΑΡΙΑ
# ══════════════════════════════════════════════════════════════════════════════
def scale(
    label: str,
    now: float | None,
    then: float | None,
    *,
    fmt=eur,
    now_tag: str = "Φέτος",
    then_tag: str = "Πέρσι",
    foot: str = "",
    href: str | None = None,
    lower_is_better: bool = False,
) -> str:
    """
    Δύο νούμερα, δύο μπάρες. Το πλάτος των μπαρών ΕΙΝΑΙ η σύγκριση.

    Το μάτι βλέπει ποια μπάρα είναι μακρύτερη πριν προλάβει να διαβάσει το
    ποσοστό. Αυτό είναι το ζητούμενο σε ένα εργαλείο που το κοιτάς 5 φορές τη μέρα.
    """
    n = 0.0 if now is None or pd.isna(now) else float(now)
    t = None if then is None or pd.isna(then) else float(then)

    # Οι μπάρες κλιμακώνονται στο μεγαλύτερο από τα δύο.
    peak = max(n, t or 0) or 1
    w_now = min(100, n / peak * 100)
    w_then = min(100, (t or 0) / peak * 100)

    pct = pct_change(n, t)
    if pct is None:
        badge = '<span class="scale-delta flat">— χωρίς πέρσι</span>'
    else:
        good = (pct < 0) if lower_is_better else (pct > 0)
        cls = "up" if good else ("flat" if abs(pct) < 0.05 else "down")
        arrow = "↑" if pct >= 0 else "↓"
        badge = f'<span class="scale-delta {cls}">{arrow} {abs(pct):.1f}%</span>'

    body = (
        '<div class="scale">'
        '<div class="scale-head">'
        f'<span class="scale-label">{_esc(label)}</span>'
        f'{badge}'
        '</div>'
        f'<div class="kpi-now">{fmt(now)}</div>'
        '<div class="bars">'
        '<div class="bar-row now">'
        f'<span class="bar-tag">{_esc(now_tag)}</span>'
        f'<span class="bar-track"><span class="bar-fill now" style="width:{w_now:.1f}%"></span></span>'
        f'<span class="bar-val">{fmt(now)}</span>'
        '</div>'
        '<div class="bar-row then">'
        f'<span class="bar-tag">{_esc(then_tag)}</span>'
        f'<span class="bar-track"><span class="bar-fill then" style="width:{w_then:.1f}%"></span></span>'
        f'<span class="bar-val">{fmt(then)}</span>'
        '</div>'
        '</div>'
        + (f'<div class="scale-foot">{_esc(foot)}</div>' if foot else '')
        + '</div>'
    )

    return f'<a href="{href}" target="_self" class="plain">{body}</a>' if href else body


def target(
    label: str,
    now: float | None,
    goal: float | None,
    *,
    foot: str = "",
    href: str | None = None,
) -> str:
    """
    Η ΚΑΡΤΑ ΣΤΟΧΟΥ — για τη σημερινή μέρα, που δεν έχει τελειώσει.

    Διαφέρει από τη ζυγαριά. Η ζυγαριά συγκρίνει δύο ΤΕΛΕΙΩΜΕΝΑ νούμερα.
    Εδώ το ένα νούμερο δεν υπάρχει ακόμα — η μέρα τρέχει.

    Άρα δεν δείχνουμε «↓ 100%» (που θα ήταν και σωστό και άχρηστο). Δείχνουμε:
      • Πόσο έχεις κάνει ως τώρα (συνήθως 0 μέχρι το βράδυ)
      • Τι έκανες την ίδια μέρα πέρσι — ΑΥΤΟΣ είναι ο στόχος
      • Πόσο έχεις φτάσει, ως ποσοστό

    Η αναφορά πωλήσεων έρχεται με email το βράδυ. Μέχρι τότε η κάρτα λέει
    «να τι πρέπει να πιάσεις σήμερα».
    """
    n = 0.0 if now is None or pd.isna(now) else float(now)
    g = None if goal is None or pd.isna(goal) else float(goal)

    done = (n / g * 100) if (g and g > 0) else None
    pending = n == 0

    if g is None:
        badge = '<span class="scale-delta flat">— χωρίς πέρσι</span>'
    elif pending:
        badge = '<span class="scale-delta flat">Σε εξέλιξη</span>'
    elif done is not None and done >= 100:
        badge = f'<span class="scale-delta up">✓ {done:.0f}% του στόχου</span>'
    else:
        badge = f'<span class="scale-delta flat">{done:.0f}% του στόχου</span>'

    w_now = min(100, done) if done else 0

    value = (
        f'<div class="kpi-now pending">Σε εξέλιξη</div>' if pending
        else f'<div class="kpi-now">{eur(now)}</div>'
    )

    body = (
        '<div class="scale target">'
        '<div class="scale-head">'
        f'<span class="scale-label">{_esc(label)}</span>'
        f'{badge}'
        '</div>'
        f'{value}'
        '<div class="bars">'
        '<div class="bar-row now">'
        '<span class="bar-tag">Τώρα</span>'
        f'<span class="bar-track"><span class="bar-fill now" style="width:{w_now:.1f}%"></span></span>'
        f'<span class="bar-val">{eur(now) if not pending else "—"}</span>'
        '</div>'
        '<div class="bar-row then">'
        '<span class="bar-tag">Στόχος</span>'
        '<span class="bar-track"><span class="bar-fill goal" style="width:100%"></span></span>'
        f'<span class="bar-val">{eur(goal)}</span>'
        '</div>'
        '</div>'
        + (f'<div class="scale-foot">{_esc(foot)}</div>' if foot else '')
        + '</div>'
    )

    return f'<a href="{href}" target="_self" class="plain">{body}</a>' if href else body


# ══════════════════════════════════════════════════════════════════════════════
# ΑΠΛΗ ΜΕΤΡΗΣΗ
# ══════════════════════════════════════════════════════════════════════════════
def stat(
    label: str,
    value,
    *,
    fmt=eur,
    tone: str = "",
    accent: str = "var(--brand)",
    foot: str = "",
    href: str | None = None,
) -> str:
    """Νούμερο χωρίς σύγκριση. Όταν δεν υπάρχει πέρσι, ή δεν έχει νόημα."""
    empty = value is None or (isinstance(value, float) and pd.isna(value))
    cls = "none" if empty else tone

    body = (
        f'<div class="stat" style="--accent:{accent}">'
        f'<div class="stat-label">{_esc(label)}</div>'
        f'<div class="stat-value {cls}">{fmt(value)}</div>'
        + (f'<div class="stat-foot">{_esc(foot)}</div>' if foot else '')
        + '</div>'
    )

    return f'<a href="{href}" target="_self" class="plain">{body}</a>' if href else body


def grid(*cards: str, cols: int = 3) -> None:
    html(f'<div class="grid g{cols}">{"".join(cards)}</div>')


# ══════════════════════════════════════════════════════════════════════════════
# ΕΠΙΤΑΓΗ
# ══════════════════════════════════════════════════════════════════════════════
def check_card(when: date, amount: float, period: str = "", tag: str = "Επόμενη επιταγή") -> None:
    extra = f' · Περίοδος {_esc(period)}' if period and period != "—" else ""
    html(
        '<div class="check">'
        '<div>'
        f'<div class="check-tag">{_esc(tag)}</div>'
        f'<div class="check-when">Πληρωμή <b>{when:%d/%m/%Y}</b>{extra}</div>'
        '</div>'
        f'<div class="check-amt">{eur(amount)}</div>'
        '</div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# ΣΕΙΡΕΣ
# ══════════════════════════════════════════════════════════════════════════════
def row(key: str, amount, meta: str = "", *, href: str | None = None, open_: bool = False) -> str:
    body = (
        f'<div class="row {"open" if open_ else ""}">'
        '<div>'
        f'<span class="row-key">{_esc(key)}</span>'
        + (f' <span class="row-meta">· {_esc(meta)}</span>' if meta else '')
        + '</div>'
        f'<span class="row-amt">{eur(amount)}</span>'
        '</div>'
    )
    return f'<a href="{href}" target="_self" class="plain">{body}</a>' if href else body


def year_row(year: int, purchases: float, sales, count: int, *, href: str, open_: bool) -> str:
    """Σειρά έτους στις Τιμολογήσεις — αγορές δίπλα σε πωλήσεις."""
    caret = "▾" if open_ else "▸"
    return (
        f'<a href="{href}" target="_self" class="plain">'
        f'<div class="row {"open" if open_ else ""}">'
        '<div>'
        f'<span class="caret">{caret}</span>'
        f'<span class="row-key">{year}</span>'
        f' <span class="row-meta">· {count} επιταγές</span>'
        '</div>'
        '<div style="display:flex;gap:.6rem">'
        f'<span class="chip buy">{eur(purchases)}</span>'
        f'<span class="chip sell">{eur(sales)}</span>'
        '</div></div></a>'
    )


def sub_list(header: tuple[str, str, str], rows: list[tuple[str, str, float]]) -> None:
    """Ανοιγμένη λίστα κάτω από μια σειρά έτους."""
    if not rows:
        return

    head = (
        '<div class="sub-head">'
        f'<span style="min-width:96px">{_esc(header[0])}</span>'
        f'<span style="flex:1;text-align:center">{_esc(header[1])}</span>'
        f'<span style="min-width:96px;text-align:right">{_esc(header[2])}</span>'
        '</div>'
    )
    body = "".join(
        '<div class="sub">'
        f'<span class="sub-date">{_esc(a)}</span>'
        f'<span class="sub-mid">{_esc(b or "—")}</span>'
        f'<span class="sub-amt">{eur(c)}</span>'
        '</div>'
        for a, b, c in rows
    )
    html(f'<div style="margin-bottom:.8rem">{head}{body}</div>')


def totals(items: list[tuple[str, str, str]]) -> None:
    """Γραμμή συνόλων. items = [(ετικέτα, τιμή, τόνος), ...] — τόνος: "" | "pos" | "neg" """
    cells = "".join(
        f'<div class="total-item"><span>{_esc(a)}</span><b class="{c}">{_esc(b)}</b></div>'
        for a, b, c in items
    )
    html(f'<div class="total"><span class="total-tag">Σύνολο</span><div class="total-set">{cells}</div></div>')


# ══════════════════════════════════════════════════════════════════════════════
# ΜΗΝΥΜΑΤΑ
# ══════════════════════════════════════════════════════════════════════════════
def note(text: str, kind: str = "info") -> None:
    """kind: info | ok | warn | bad"""
    html(f'<div class="note {kind}">{text}</div>')


def empty(headline: str, body: str = "") -> None:
    """
    Το άδειο δεν απολογείται. Λέει τι λείπει και τι να κάνεις.
    """
    html(
        '<div class="empty">'
        f'<div class="empty-head">{_esc(headline)}</div>'
        + (f'<div class="empty-body">{_esc(body)}</div>' if body else '')
        + '</div>'
    )
