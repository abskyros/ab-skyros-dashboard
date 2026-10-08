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
    _apply_day_night()


def _apply_day_night() -> None:
    """
    Νυχτερινή εμφάνιση αυτόματα, ανάλογα με την ώρα Ελλάδας.

    Μέρα (07:00–20:00) → φωτεινό. Νύχτα (20:00–07:00) → σκούρο, να μην κουράζει.

    Το Streamlit τρέχει σε iframe, οπότε βάζουμε την κλάση `.dark` με JavaScript
    στο σωστό στοιχείο (το body της σελίδας που περιέχει το iframe).
    """
    from core.metrics import now_greece

    hour = now_greece().hour
    is_night = hour >= 20 or hour < 7

    # Εφάρμοσε και στο τρέχον έγγραφο ΚΑΙ στο parent (έξω από το iframe).
    mode = "add" if is_night else "remove"
    st.markdown(
        f"""
        <script>
        (function() {{
            function apply(doc) {{
                if (doc && doc.body) doc.body.classList.{mode}('dark');
            }}
            apply(document);
            try {{ apply(window.parent.document); }} catch (e) {{}}
        }})();
        </script>
        """,
        unsafe_allow_html=True,
    )


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
    """Πλοήγηση desktop. ΔΕΝ δείχνει τις σελίδες που είναι μόνο για κινητό."""
    from core.config import DESKTOP_PAGES
    items = "".join(
        f'<a href="{link(p)}" target="_self" class="{"on" if p == current else ""}">{p}</a>'
        for p in DESKTOP_PAGES
    )
    html(f'<nav class="nav">{items}</nav>')


ICONS = {
    "Επισκόπηση": "🏠",
    "Πωλήσεις": "📈",
    "Παραστατικά": "🧾",
    "Τιμολογήσεις": "💳",
    "Μήνας": "📅",
    "Πρόβλεψη": "🔮",
    "Επιταγές": "💰",
}


def tabbar(current: str) -> None:
    """
    Πλοήγηση κινητού. Πάνω στην οθόνη.

    Δείχνει ΟΛΕΣ τις σελίδες, μαζί με το «Επιταγές» (η δεξαμενή) που στο κινητό
    έχει δική της καρτέλα.
    """
    items = "".join(
        f'<a href="{link(p)}" target="_self" class="{"on" if p == current else ""}">'
        f'<span class="ico">{ICONS.get(p, "•")}</span><span>{p}</span></a>'
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
def _bar(tag: str, val, fmt, cls: str, width: float | None) -> str:
    """
    Μια γραμμή σύγκρισης: ετικέτα · λεπτή μπάρα αναλογίας · ποσό.

    Η μπάρα ΔΕΝ είναι γράφημα — είναι η ζυγαριά. Δύο πάχη δίπλα-δίπλα λένε
    «ποιο είναι μεγαλύτερο» πριν προλάβεις να διαβάσεις τα νούμερα.
    """
    fill = (
        f'<span class="bar-fill" style="width:{width:.0f}%"></span>'
        if width is not None else ''
    )
    return (
        f'<div class="bar-row {cls}">'
        f'<span class="bar-tag">{_esc(tag)}</span>'
        f'<span class="bar-track">{fill}</span>'
        f'<span class="bar-val">{fmt(val)}</span>'
        '</div>'
    )


def _widths(now: float, then: float | None) -> tuple[float | None, float | None]:
    """Τα πάχη των δύο μπαρών, 0–100. None αν δεν υπάρχει σύγκριση."""
    if then is None or then <= 0:
        return (100.0 if now > 0 else 0.0), None
    base = max(now, then)
    if base <= 0:
        return 0.0, 0.0
    return 100.0 * now / base, 100.0 * then / base


def _widths3(
    now: float, then: float | None, then2: float | None
) -> tuple[float | None, float | None, float | None]:
    """
    Τα πάχη ΤΡΙΩΝ μπαρών (φέτος/πέρσι/πρόπερσι), 0–100, με κοινή βάση το
    μεγαλύτερο. Όποια τιμή λείπει → None (δεν σχεδιάζεται μπάρα).
    """
    vals = [v for v in (now, then, then2) if v is not None and v > 0]
    base = max(vals) if vals else 0.0

    def w(v):
        if v is None:
            return None
        return (100.0 * v / base) if base > 0 else 0.0

    return w(now), w(then), w(then2)


def scale(
    label: str,
    now: float | None,
    then: float | None,
    *,
    then2: float | None = None,
    fmt=eur,
    now_tag: str = "Φέτος",
    then_tag: str = "Πέρσι",
    then2_tag: str = "Πρόπερσι",
    foot: str = "",
    href: str | None = None,
    lower_is_better: bool = False,
) -> str:
    """
    Το νούμερο, και δίπλα του η σύγκριση με πέρσι (και προαιρετικά πρόπερσι).

    Η ζυγαριά: λεπτές μπάρες δείχνουν οπτικά ποιο νούμερο είναι μεγαλύτερο,
    το ποσοστό στην κορυφή λέει πόσο (φέτος vs πέρσι).

    then2 (πρόπερσι): αν δοθεί ΚΑΙ δεν είναι None, προστίθεται ΤΡΙΤΗ μπάρα.
    Αν λείπει (δεν υπάρχουν δεδομένα 2 χρόνια πίσω), η κάρτα μένει με 2 μπάρες.
    """
    n = 0.0 if now is None or pd.isna(now) else float(now)
    t = None if then is None or pd.isna(then) else float(then)
    t2 = None if then2 is None or pd.isna(then2) else float(then2)

    pct = pct_change(n, t)
    if pct is None:
        badge = '<span class="scale-delta flat">— χωρίς πέρσι</span>'
    else:
        good = (pct < 0) if lower_is_better else (pct > 0)
        cls = "up" if good else ("flat" if abs(pct) < 0.05 else "down")
        arrow = "↑" if pct >= 0 else "↓"
        badge = f'<span class="scale-delta {cls}">{arrow} {abs(pct):.1f}%</span>'

    # Αν υπάρχει πρόπερσι, 3 μπάρες με κοινή βάση· αλλιώς 2 (όπως πριν).
    bars = '<div class="bars">'
    if t2 is not None:
        now_w, then_w, then2_w = _widths3(n, t, t2)
        bars += _bar(now_tag, now, fmt, "now", now_w)
        bars += _bar(then_tag, then, fmt, "then", then_w)
        bars += _bar(then2_tag, then2, fmt, "then2", then2_w)
    else:
        now_w, then_w = _widths(n, t)
        bars += _bar(now_tag, now, fmt, "now", now_w)
        bars += _bar(then_tag, then, fmt, "then", then_w)
    bars += '</div>'

    body = (
        '<div class="scale">'
        '<div class="scale-head">'
        f'<span class="scale-label">{_esc(label)}</span>'
        f'{badge}'
        '</div>'
        f'<div class="kpi-now">{fmt(now)}</div>'
        + bars
        + (f'<div class="scale-foot">{_esc(foot)}</div>' if foot else '')
        + '</div>'
    )

    return f'<a href="{href}" target="_self" class="plain">{body}</a>' if href else body


def target(
    label: str,
    now: float | None,
    goal: float | None,
    *,
    goal2: float | None = None,
    goal2_tag: str = "Πρόπερσι",
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

    goal2 (πρόπερσι): αν δοθεί ΚΑΙ δεν είναι None, προστίθεται ΤΡΙΤΗ μπάρα με
    το ταμείο της ίδιας μέρας πριν 2 χρόνια. Αν λείπει, η κάρτα μένει 2 μπάρες.

    Η αναφορά πωλήσεων έρχεται με email το βράδυ. Μέχρι τότε η κάρτα λέει
    «να τι πρέπει να πιάσεις σήμερα».
    """
    n = 0.0 if now is None or pd.isna(now) else float(now)
    g = None if goal is None or pd.isna(goal) else float(goal)
    g2 = None if goal2 is None or pd.isna(goal2) else float(goal2)

    pending = n == 0

    # ── ΤΟ ΠΟΣΟΣΤΟ: ΜΕΤΑΒΟΛΗ, ΟΧΙ ΑΝΑΛΟΓΙΑ ──
    #
    # Παλιά έδειχνε «128% του στόχου» (= φέτος/πέρσι). Σωστό νούμερο, λάθος
    # γλώσσα: δίπλα του η κάρτα «Χθες» δείχνει ΜΕΤΑΒΟΛΗ (↑2.3%). Δύο διαφορετικά
    # μέτρα δίπλα-δίπλα μπερδεύουν — και το «128%» διαβάζεται σαν «+128%».
    #
    # Τώρα μιλούν όλες την ίδια γλώσσα: ↑28% σημαίνει 28% πάνω από πέρσι.
    pct = pct_change(n, g)

    if g is None:
        badge = '<span class="scale-delta flat">— χωρίς πέρσι</span>'
    elif pending:
        badge = '<span class="scale-delta flat">Σε εξέλιξη</span>'
    elif pct is None:
        badge = '<span class="scale-delta flat">— χωρίς πέρσι</span>'
    else:
        cls = "up" if pct > 0 else ("flat" if abs(pct) < 0.05 else "down")
        arrow = "↑" if pct >= 0 else "↓"
        badge = f'<span class="scale-delta {cls}">{arrow} {abs(pct):.1f}%</span>'

    value = (
        f'<div class="kpi-now pending">Σε εξέλιξη</div>' if pending
        else f'<div class="kpi-now">{eur(now)}</div>'
    )

    # Μπάρες: αν υπάρχει πρόπερσι (g2), 3 μπάρες με κοινή βάση· αλλιώς 2.
    if g2 is not None:
        now_w, goal_w, goal2_w = _widths3(n, g, g2)
    else:
        now_w, goal_w = _widths(n, g)
        goal2_w = None

    bars = (
        '<div class="bars">'
        + _bar("Τώρα", "—" if pending else now, (lambda v: v) if pending else eur, "now", 0.0 if pending else now_w)
        + _bar("Στόχος", goal, eur, "then", goal_w)
    )
    if g2 is not None:
        bars += _bar(goal2_tag, goal2, eur, "then2", goal2_w)
    bars += '</div>'

    body = (
        '<div class="scale target">'
        '<div class="scale-head">'
        f'<span class="scale-label">{_esc(label)}</span>'
        f'{badge}'
        '</div>'
        f'{value}'
        + bars
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


# ══════════════════════════════════════════════════════════════════════════════
# Η ΔΕΞΑΜΕΝΗ — πόσο μακριά φτάνει το ταμείο στις επόμενες επιταγές
# ══════════════════════════════════════════════════════════════════════════════
def cash_runway_card(runway: dict) -> None:
    """
    Στιλ D: μια κάρτα ανά επιταγή, με μίνι μπάρα «καυσίμου».

    Το runway έρχεται από core.metrics.cash_runway(). Εδώ γίνεται ΜΟΝΟ εμφάνιση.

    Πράσινο = πληρωμένη πλήρως · Πορτοκαλί = εδώ κόβεσαι · Γκρι = δεν φτάνεις.
    """
    checks = runway["checks"]

    if not checks:
        html(
            '<div class="runway">'
            '<div class="runway-empty">Δεν υπάρχουν επιταγές μπροστά. '
            'Ό,τι έληξε δεν μετράει εδώ.</div>'
            '</div>'
        )
        return

    # ── Οι κάρτες ──
    cards = []
    for i, c in enumerate(checks, 1):
        frac = c["fraction"]
        status = c["status"]
        pct = int(round(frac * 100))
        width = max(0, min(100, pct))

        if status == "full":
            badge = '<span class="rw-badge full">✓</span>'
        elif status == "partial":
            badge = f'<span class="rw-badge partial">{pct}%</span>'
        else:
            badge = '<span class="rw-badge empty">—</span>'

        period = f' · {_esc(c["period"])}' if c.get("period") else ""

        cards.append(
            f'<div class="rw-row {status}">'
            f'  <div class="rw-top">'
            f'    <span class="rw-name">Επιταγή {i}</span>'
            f'    <span class="rw-date">{c["date"]:%d/%m}{period}</span>'
            f'    {badge}'
            f'  </div>'
            f'  <div class="rw-track">'
            f'    <div class="rw-fill {status}" style="width:{width}%"></div>'
            f'    <span class="rw-amt">{eur(c["amount"])}</span>'
            f'  </div>'
            f'</div>'
        )

    # ── Η σύνοψη (κάτω) ──
    fully = runway["fully_covered"]
    leftover = runway["leftover_after_full"]
    surplus = runway["surplus"]

    partial = next((c for c in checks if c["status"] == "partial"), None)
    partial_idx = next((i for i, c in enumerate(checks, 1)
                        if c["status"] == "partial"), None)

    if surplus > 0:
        # Το ταμείο καλύπτει τα πάντα και περισσεύει
        summary = (
            f'<b>Το ταμείο καλύπτει και τις {fully} επιταγές.</b><br>'
            f'Περισσεύουν <b>{eur(surplus)}</b>.'
        )
        tone = "ok"
    elif partial:
        pct = int(round(partial["fraction"] * 100))
        word = "επιταγή" if fully == 1 else "επιταγές"
        summary = (
            f'<b>Καλύπτεις πλήρως {fully} {word}</b> και φτάνεις ως το '
            f'<b>{pct}%</b> της {partial_idx}ης.<br>'
            f'Μένουν <b>{eur(leftover)}</b> για να την κλείσεις.'
        )
        tone = "warn"
    elif fully > 0:
        word = "επιταγή" if fully == 1 else "επιταγές"
        summary = f'<b>Καλύπτεις πλήρως {fully} {word}.</b>'
        tone = "ok"
    else:
        # Δεν φτάνει ούτε η πρώτη
        first = checks[0]
        summary = (
            f'<b>Το ταμείο δεν καλύπτει ούτε την πρώτη επιταγή.</b><br>'
            f'Λείπουν <b>{eur(first["amount"] - first["covered"])}</b>.'
        )
        tone = "bad"

    html(
        '<div class="runway">'
        f'<div class="rw-cards">{"".join(cards)}</div>'
        f'<div class="rw-summary {tone}">{summary}</div>'
        '</div>'
    )

