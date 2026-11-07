"""
views/month.py — Μήνας.

Η οικονομική εικόνα μιας περιόδου, γραμμή-γραμμή:

    Πωλήσεις περιόδου  −  Επιταγή  −  Έξοδα  =  Τι μένει

Το «τι μένει» είναι το μόνο νούμερο που ενδιαφέρει στο τέλος της μέρας.
Τα «Αρ. επιταγής» και «Έξοδα» τα γράφεις εσύ και αποθηκεύονται στο Sheet.

┌────────────────────────────────────────────────────────────────────────────┐
│ ΔΥΟ ΠΑΓΙΔΕΣ ΠΟΥ ΑΠΟΦΕΥΓΟΝΤΑΙ ΕΔΩ                                          │
│                                                                            │
│ 1. ΜΝΗΜΗ — ΕΝΑ data_editor, όχι text_input ανά γραμμή.                     │
│    Το παλιό loop με st.columns + st.text_input έφτιαχνε εκατοντάδες        │
│    widgets και έριχνε το Streamlit Cloud (segmentation fault).             │
│                                                                            │
│ 2. ΑΤΕΡΜΟΝΟΣ ΒΡΟΧΟΣ — ΔΕΝ συγκρίνουμε DataFrames για να δούμε τι άλλαξε.   │
│    Το data_editor γράφει στο session_state ΑΚΡΙΒΩΣ ποια γραμμή και ποια    │
│    στήλη πείραξε ο χρήστης. Αυτή είναι η αλήθεια.                          │
│                                                                            │
│    Αν αντ' αυτού συγκρίναμε «πριν» με «μετά»:                              │
│      γράφω στο Sheet → rerun → το cache (300s) δεν έχει φρεσκάρει →        │
│      οι πίνακες διαφέρουν → γράφω ξανά → rerun → ... για πάντα.            │
└────────────────────────────────────────────────────────────────────────────┘
"""

from datetime import date

import pandas as pd
import streamlit as st

from core.config import MONTHS_GR
from core.metrics import (
    as_dates, month_rows, purchase_period, cash_runway, last_sent_check, upcoming_checks,
)
from core.sheets import update_timologiseis_field, load_setting, save_setting
from ui import components as c


EDITOR_KEY = "month_editor"
CASH_SETTING = "cash_on_hand"   # κλειδί στο φύλλο settings για το ταμείο
FIXED_SETTING = "fixed_expenses"  # κλειδί για τα πάγια έξοδα (JSON)

COLS = ["Ημ. επιταγής", "Επιταγή", "Πωλήσεις περιόδου",
        "Μένει", "Αρ. επιταγής", "Voucher", "Ημερομηνία"]

# Ποιες στήλες γράφονται πίσω στο Sheet, και σε ποιο πεδίο.
EDITABLE = {
    "Αρ. επιταγής": "check_number",
    "Voucher": "voucher",
    "Ημερομηνία": "sent_date",
}


def render(df_t: pd.DataFrame, df_s: pd.DataFrame, today: date) -> None:
    if df_t.empty:
        c.empty("Δεν υπάρχουν τιμολογήσεις ακόμη")
        return

    year, month, ascending = _filters(df_t, today)

    rows = month_rows(df_t, df_s, year, month)
    if not rows:
        label = f"το {year}" if not month else f"τον {MONTHS_GR[month - 1]} {year}"
        c.empty(f"Καμία επιταγή για {label}")
        return

    rows.sort(key=lambda r: r["check_date"], reverse=not ascending)

    # Ό,τι πάτησε ο χρήστης στην προηγούμενη εκτέλεση, γράφεται τώρα.
    fresh_vouchers = _flush(rows)

    _summary(rows)

    # ── ΤΑΜΕΙΟ ──
    #
    # Το ταμείο μπαίνει πάνω από τον πίνακα, η σύνοψη κάλυψης κάτω. (Η κάλυψη
    # φαίνεται και στην Επισκόπηση και στις Επιταγές — όχι ως στήλη του πίνακα.)
    cash = _cash_input(key="month")
    runway = cash_runway(df_t, today, cash)

    sent_until = last_sent_check(df_t, fresh_vouchers)
    _editor(rows, df_t, today, sent_until)
    _runway_summary(runway)


# ══════════════════════════════════════════════════════════════════════════════
# ΤΑΜΕΙΟ — θυμάται την τελευταία τιμή, αλλάζει χειροκίνητα
# ══════════════════════════════════════════════════════════════════════════════
def _cash_input(key: str) -> float:
    """
    Το διαθέσιμο ταμείο.

    Ζει σε ΔΥΟ σημεία:
      • session_state → να μην ξαναδιαβάζουμε το Sheet σε κάθε rerun
      • φύλλο settings → να θυμάται ακόμα κι αν κλείσεις τον browser

    Ο χρήστης το αλλάζει όποτε θέλει· η αλλαγή αποθηκεύεται μόνη της.
    """
    ss_key = f"cash_{key}"
    if ss_key not in st.session_state:
        saved = load_setting(CASH_SETTING, "0")
        try:
            st.session_state[ss_key] = float(saved)
        except (ValueError, TypeError):
            st.session_state[ss_key] = 0.0

    a, _ = st.columns([1, 2])
    with a:
        cash = st.number_input(
            "💰 Διαθέσιμα μετρητά (€)",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            key=ss_key,
            help="Το ποσό που έχεις τώρα. Από αυτό υπολογίζεται ως πού φτάνει στις "
                 "επόμενες επιταγές. Θυμάται την τελευταία τιμή.",
        )

    last = st.session_state.get(f"{ss_key}_saved")
    if cash != last:
        save_setting(CASH_SETTING, str(int(cash)))
        st.session_state[f"{ss_key}_saved"] = cash

    return cash


def _fixed_expenses_input() -> list:
    """
    Πάγια μηνιαία έξοδα — μπαίνουν μία φορά, επαναλαμβάνονται κάθε μήνα.

    Επεξεργάσιμος πίνακας: Υποχρέωση | Ποσό (€) | Μέρα μήνα. Ό,τι γράφεις
    αποθηκεύεται μόνο του (ως JSON στο settings). Η πρόβλεψη τα αφαιρεί στη
    μέρα τους, κάθε μήνα.

    → [{"name": str, "amount": float, "day": int}, ...]
    """
    import json

    if "fixed_exp" not in st.session_state:
        raw = load_setting(FIXED_SETTING, "")
        try:
            data = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            data = []
        if not data:
            data = [
                {"name": "Μισθοδοσία", "amount": 0.0, "day": 30},
                {"name": "ΙΚΑ προσωπικού", "amount": 0.0, "day": 30},
                {"name": "ΦΠΑ", "amount": 0.0, "day": 25},
                {"name": "ΦΜΥ", "amount": 0.0, "day": 20},
                {"name": "Ρεύμα", "amount": 0.0, "day": 15},
                {"name": "Λογιστής", "amount": 0.0, "day": 10},
            ]
        st.session_state["fixed_exp"] = pd.DataFrame(data)

    with st.expander("💳 Πάγια έξοδα μήνα", expanded=False):
        st.caption(
            "Γράψε τις μηνιαίες υποχρεώσεις σου (ποσό και μέρα του μήνα). "
            "Μπαίνουν στην πρόβλεψη και αφαιρούνται στη μέρα τους — κάθε μήνα. "
            "Άφησε το ποσό 0 για όσες δεν ισχύουν."
        )

        edited = st.data_editor(
            st.session_state["fixed_exp"],
            key="fixed_editor",
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "name": st.column_config.TextColumn("Υποχρέωση", width="medium"),
                "amount": st.column_config.NumberColumn(
                    "Ποσό (€)", min_value=0.0, step=100.0, format="%.0f"
                ),
                "day": st.column_config.NumberColumn(
                    "Μέρα μήνα", min_value=1, max_value=31, step=1, format="%d"
                ),
            },
        )

        records = edited.to_dict("records")
        # Καθάρισε τιμές NaN/None πριν το JSON — αλλιώς σκάει η αποθήκευση.
        clean_records = [
            {
                "name": str(r.get("name", "") or "").strip(),
                "amount": _safe_float(r.get("amount")),
                "day": _safe_int(r.get("day"), 1),
            }
            for r in records
        ]
        as_json = json.dumps(clean_records, ensure_ascii=False)
        if as_json != st.session_state.get("fixed_exp_saved"):
            save_setting(FIXED_SETTING, as_json)
            st.session_state["fixed_exp_saved"] = as_json

        total = sum(_safe_float(r.get("amount")) for r in records)
        if total > 0:
            c.html(
                f"<div style='margin-top:.5rem;font-size:.85rem;color:var(--muted)'>"
                f"Σύνολο πάγιων/μήνα: <b>{c.eur(total)}</b></div>"
            )

    out = []
    for r in edited.to_dict("records"):
        name = str(r.get("name", "") or "").strip()
        amt = _safe_float(r.get("amount"))
        day = _safe_int(r.get("day"), 1)
        # Κράτα το day μέσα σε λογικά όρια (1-31).
        day = min(max(day, 1), 31)
        if name and amt > 0:
            out.append({"name": name, "amount": amt, "day": day})
    return out


def _safe_float(v) -> float:
    """Μετατρέπει σε float ό,τι κι αν είναι — None, κενό, NaN, κόμμα-δεκαδικό."""
    if v is None:
        return 0.0
    try:
        # NaN (από κενά κελιά pandas) → 0
        if isinstance(v, float) and v != v:
            return 0.0
    except Exception:
        pass
    s = str(v).strip().replace(",", ".")
    if not s or s.lower() in ("nan", "none"):
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(v, default: int = 0) -> int:
    """Μετατρέπει σε int ό,τι κι αν είναι — None, κενό, NaN, δεκαδικό."""
    f = _safe_float(v)
    if f == 0.0 and default:
        # Ξεχώρισε «πραγματικό 0» από «κενό» — αν ήταν κενό, βάλε default.
        s = str(v).strip() if v is not None else ""
        if not s or s.lower() in ("nan", "none"):
            return default
    return int(f)


def _runway_summary(runway: dict) -> None:
    """Μία γραμμή: ως πού φτάνει το ταμείο. Κάτω από τον πίνακα."""
    checks = runway["checks"]
    if not checks or runway["cash"] <= 0:
        return

    fully = runway["fully_covered"]
    partial = next((c for c in checks if c["status"] == "partial"), None)
    idx = next((i for i, c in enumerate(checks, 1) if c["status"] == "partial"), None)

    if runway["surplus"] > 0:
        c.note(
            f"<b>Το ταμείο καλύπτει και τις {fully} επόμενες επιταγές.</b> "
            f"Περισσεύουν <b>{c.eur(runway['surplus'])}</b>.",
            "ok",
        )
    elif partial:
        word = "επιταγή" if fully == 1 else "επιταγές"
        c.note(
            f"<b>Καλύπτεις πλήρως {fully} {word}</b> και φτάνεις ως το "
            f"<b>{int(round(partial['fraction'] * 100))}%</b> της {idx}ης. "
            f"Μένουν <b>{c.eur(runway['leftover_after_full'])}</b> για να την κλείσεις.",
            "warn",
        )
    elif fully == 0:
        first = checks[0]
        c.note(
            f"<b>Το ταμείο δεν καλύπτει ούτε την πρώτη επιταγή.</b> "
            f"Λείπουν <b>{c.eur(first['amount'] - first['covered'])}</b>.",
            "bad",
        )


# ══════════════════════════════════════════════════════════════════════════════
# ΠΡΟΒΛΕΨΗ ΡΕΥΣΤΟΤΗΤΑΣ — τι θα φτάνει όταν λήξει κάθε επιταγή
# ══════════════════════════════════════════════════════════════════════════════
def _sales_detail(ch: dict) -> str:
    """
    Κάτω από τις πωλήσεις μιας επιταγής: ποιες μέρες, και πόσα είναι ήδη
    πραγματικά (φέτος) και πόσα πρόβλεψη (πέρσι).
    """
    if not ch.get("sales_from"):
        return ""
    txt = f"{ch['sales_from']:%d/%m}–{ch['sales_to']:%d/%m}"
    if ch.get("sales_actual"):
        txt += (f" · πραγματικά {c.eur(ch['sales_actual'])}"
                f" + πρόβλεψη {c.eur(ch.get('sales_ly') or 0)}")
    return f"<br><span style='font-size:.72rem;opacity:.85'>{txt}</span>"


def _forecast_display(forecast: dict) -> None:
    """
    Δείχνει πώς εξελίσσεται το ταμείο μπροστά, επιταγή-επιταγή, με βάση τις
    προβλεπόμενες πωλήσεις (περσινές, ίδιες μέρες).
    """
    checks = forecast["checks"]
    if not checks or forecast["cash"] <= 0:
        return

    c.spacer(0.8)
    c.section("🔮 Πρόβλεψη ρευστότητας")

    # Πόσες επιταγές είναι πραγματικές και πόσες πρόβλεψη;
    n_real = sum(1 for ch in checks if ch.get("kind") == "check" and not ch.get("estimated"))
    n_est = sum(1 for ch in checks if ch.get("kind") == "check" and ch.get("estimated"))

    # Headline: η γενική εικόνα με μια πρόταση.
    if forecast["all_covered"]:
        last = checks[-1]
        c.note(
            f"<b>Με τον ρυθμό της περσινής χρονιάς, όλες οι επιταγές βγαίνουν.</b> "
            f"Μετά την τελευταία ({last['date']:%d/%m}), προβλέπεται να σου "
            f"μένουν <b>{c.eur(last['balance_after'])}</b>.",
            "ok",
        )
    else:
        gap = forecast["first_gap"]
        c.note(
            f"<b>Με τον ρυθμό της περσινής χρονιάς, στις "
            f"{gap['date']:%d/%m} θα σου λείψουν "
            f"{c.eur(gap['shortfall'])}</b> για να πληρώσεις την επιταγή των "
            f"{c.eur(gap['amount'])}.<br>"
            f"<span style='font-size:.85rem;opacity:.85'>Πρόβλεψη βάσει "
            f"πωλήσεων {forecast['based_on_year']} — όχι εγγύηση. Ένας καλός "
            f"μήνας μπορεί να την καλύψει.</span>",
            "bad",
        )

    # Υπόμνημα: εξήγησε πραγματικές vs προβλεπόμενες επιταγές.
    if n_est > 0:
        c.html(
            f"<div style='font-size:.78rem;color:var(--muted);margin:.4rem 0 .2rem'>"
            f"<b>{n_real}</b> πραγματικές επιταγές (σταλμένες) · "
            f"<span style='color:var(--prev)'><b>{n_est}</b> ~προβλεπόμενες (πέρσι)</span> "
            f"ως το τέλος του έτους"
            f"</div>"
        )

    # Αναλυτικά: μία γραμμή ανά υποχρέωση, με το τρέχον προβλεπόμενο υπόλοιπο.
    # ΧΡΟΝΟΛΟΓΙΚΑ — από σήμερα (πάνω) προς το τέλος του έτους (κάτω).
    lines = []
    for ch in checks:
        if ch["covered"]:
            dot = "🟢"
            after = f"μένουν {c.eur(ch['balance_after'])}"
            color = "var(--pos)"
        else:
            dot = "🔴"
            after = f"λείπουν {c.eur(ch['shortfall'])}"
            color = "var(--neg)"

        # Επιταγή ή πάγιο; Τα πάγια δείχνουν το όνομά τους, σε άλλο χρώμα.
        is_est = ch.get("estimated", False)
        if ch.get("kind") == "fixed":
            label = (
                f"<span style='color:#7C3AED'>💳 {ch.get('name', 'πάγιο')} "
                f"{c.eur(ch['amount'])}</span>"
            )
        elif is_est:
            # ΠΡΟΒΛΕΠΟΜΕΝΗ επιταγή (περσινή) — ξεθωριασμένη, με «~» και ένδειξη.
            label = (
                f"<span style='color:var(--prev)'>~επιταγή {c.eur(ch['amount'])} "
                f"<span style='font-size:.72rem;opacity:.8'>(πέρσι)</span></span>"
            )
        else:
            label = f"επιταγή {c.eur(ch['amount'])}"

        sales_part = (
            f"<span style='color:var(--dim)'>+{c.eur(ch['sales_until'])} πωλήσεις"
            + _sales_detail(ch) + "</span>"
            if ch["sales_until"] > 0 else
            "<span style='color:var(--dim)'>—</span>"
        )

        # Οι προβλεπόμενες γραμμές λίγο πιο διάφανες, να ξεχωρίζουν με μια ματιά.
        row_opacity = "opacity:.72;" if is_est else ""

        lines.append(
            f"<div style='display:flex;align-items:center;gap:.6rem;padding:.45rem 0;"
            f"border-bottom:1px solid var(--line-soft);{row_opacity}'>"
            f"<span style='font-size:.9rem'>{dot}</span>"
            f"<span style='min-width:64px;font-weight:600'>{ch['date']:%d/%m}</span>"
            f"<span style='min-width:140px'>{label}</span>"
            f"<span style='flex:1'>{sales_part}</span>"
            f"<span style='font-weight:700;color:{color}'>{after}</span>"
            f"</div>"
        )

    c.html(
        "<div style='margin-top:.6rem;font-size:.85rem'>" + "".join(lines) + "</div>"
    )


# ══════════════════════════════════════════════════════════════════════════════
def _filters(df: pd.DataFrame, today: date) -> tuple[int, int, bool]:
    years = sorted({d.year for d in as_dates(df["check_date"])}, reverse=True)
    default = years.index(today.year) if today.year in years else 0

    a, b, d = st.columns(3)

    with a:
        year = st.selectbox("Έτος", years, index=default, key="m_year")

    with b:
        month = st.selectbox(
            "Μήνας",
            [0] + list(range(1, 13)),
            format_func=lambda m: "Όλο το έτος" if m == 0 else MONTHS_GR[m - 1],
            index=0,
            key="m_month",
        )

    with d:
        order = st.selectbox("Σειρά", ["Νεότερες πρώτα", "Παλαιότερες πρώτα"], key="m_order")

    return year, month, order.startswith("Παλαι")


# ══════════════════════════════════════════════════════════════════════════════
def _summary(rows: list[dict]) -> None:
    """Τα σύνολα ΠΑΝΩ από τον πίνακα. Πρώτα η απάντηση, μετά τα στοιχεία."""
    total_check = sum(r["amount"] for r in rows)
    total_sales = sum(r["sales"] or 0 for r in rows)
    total_exp = sum(r["expenses"] for r in rows)
    balance = total_sales - total_check - total_exp

    ly_check = sum(r["ly_amount"] or 0 for r in rows if r["ly_amount"])
    ly_sales = sum(r["ly_sales"] or 0 for r in rows if r["ly_sales"])

    c.grid(
        c.scale("Πωλήσεις περιόδου", total_sales, ly_sales or None,
                foot=f"{len(rows)} περίοδοι"),
        c.scale("Επιταγές", total_check, ly_check or None,
                lower_is_better=True,
                foot="Λιγότερο είναι καλύτερα"),
        c.stat("Μένει", balance,
               tone="pos" if balance >= 0 else "neg",
               accent="var(--pos)" if balance >= 0 else "var(--neg)",
               foot=f"Πωλήσεις − επιταγές − έξοδα ({c.eur(total_exp)})" if total_exp
                    else "Πωλήσεις − επιταγές"),
        cols=3,
    )


# ══════════════════════════════════════════════════════════════════════════════
def _editor(rows: list[dict], df_t: pd.DataFrame, today: date, sent_until: date | None) -> None:
    """
    Ο πίνακας ανά περίοδο. Συμπληρώνεις: αριθμό επιταγής, voucher (ο κωδικός όταν
    στέλνεις το πακέτο) και ημερομηνία αποστολής.

    Σταλμένες = έως και την πιο πρόσφατη επιταγή με voucher (last_sent_check).
    """
    c.section("Ανά περίοδο")

    ahead = upcoming_checks(df_t, today)
    sent = sum(1 for ch in ahead if sent_until and ch["date"] <= sent_until)
    st.caption(
        f"Επόμενες επιταγές — **Σταλμένες: {sent} · Απομένουν: {len(ahead) - sent}**. "
        "Γράψε το voucher στην τελευταία επιταγή του πακέτου — "
        "οι προηγούμενες μετράνε αυτόματα ως σταλμένες."
    )

    table = pd.DataFrame([
        {
            "Ημ. επιταγής":      f"{r['check_date']:%d/%m/%Y}",
            "Περίοδος":          _period_label(r),
            # Τα ποσά μπαίνουν ΗΔΗ μορφοποιημένα (βλ. «ΜΟΡΦΗ ΠΟΣΩΝ» παρακάτω).
            "Επιταγή":           c.eur(r["amount"]),
            "Πωλήσεις περιόδου": c.eur(r["sales"]),
            "Μένει":             c.eur(r["balance"]),
            "Αρ. επιταγής":      r["check_number"],
            "Voucher":           r["voucher"],
            "Ημερομηνία":        r["sent_date"],
        }
        for r in rows
    ])

    money = st.column_config.TextColumn(disabled=True)

    # ── ΣΤΑΛΜΕΝΕΣ vs ΜΗ ΣΤΑΛΜΕΝΕΣ ──
    #
    # Ξεχωρίζουν μόνο με το χρώμα των γραμμάτων: σκούρα οι σταλμένες, απαλό γκρι
    # οι υπόλοιπες. ΟΧΙ έντονο φόντο — τα γράμματα πρέπει να διαβάζονται άνετα
    # στο κινητό. Το γκρι έχει αρκετή αντίθεση πάνω στο ανοιχτό φόντο.
    #
    # ΠΡΟΣΟΧΗ: το Streamlit εφαρμόζει Styler ΜΟΝΟ σε μη-επεξεργάσιμες στήλες.
    # Άρα «Αρ. επιταγής», «Voucher» και «Ημερομηνία» μένουν λευκές — που βολεύει:
    # ξεχωρίζουν αμέσως ως τα πεδία που συμπληρώνεις εσύ.
    SENT = "background-color: #F7F8FA; color: #0F172A"
    UNSENT = "background-color: #F7F8FA; color: #7A8496"
    read_only = [col for col in ("Ημ. επιταγής", "Περίοδος", "Επιταγή", "Πωλήσεις περιόδου",
                                 "Μένει") if col in table.columns]

    css = pd.DataFrame("", index=table.index, columns=table.columns)
    for i, r in enumerate(rows):
        cd = r["check_date"].date() if hasattr(r["check_date"], "date") else r["check_date"]
        css.loc[i, read_only] = SENT if sent_until and cd <= sent_until else UNSENT

    # ── ΜΟΡΦΗ ΠΟΣΩΝ ──
    #
    # ΓΙΑΤΙ ΕΒΓΑΙΝΕ «None» και «81584.88 €»: το format="%.2f €" του Streamlit
    # δεν βάζει διαχωριστικό χιλιάδων, και τα κενά (μέλλουσες περίοδοι) ο Styler
    # τα γράφει «None». Άρα τα ποσά μπαίνουν στον πίνακα ΗΔΗ ως κείμενο με
    # ελληνική μορφή (c.eur → «81.584,88 €», κενό → «—»). Είναι στήλες μόνο για
    # ανάγνωση, οπότε η αποθήκευση των πεδίων σου δεν επηρεάζεται.
    styled = table.style.apply(lambda _: css, axis=None)

    st.data_editor(
        styled,
        key=EDITOR_KEY,
        width="stretch",
        hide_index=True,
        column_order=COLS,
        row_height=42,
        column_config={
            "Ημ. επιταγής":      st.column_config.TextColumn(disabled=True, width="small"),
            "Περίοδος":          st.column_config.TextColumn(disabled=True),
            "Επιταγή":           money,
            "Πωλήσεις περιόδου": money,
            "Μένει":             money,
            "Αρ. επιταγής": st.column_config.TextColumn(
                help="Ο αριθμός της επιταγής, όπως τον γράφεις στο μπλοκ",
                width="small",
            ),
            "Voucher": st.column_config.TextColumn(
                help="Ο κωδικός voucher, όταν στέλνεις το πακέτο",
                width="small",
            ),
            # Κείμενο και όχι DateColumn: η DateColumn ζωγραφίζει «None» σε κάθε
            # κενό κελί και δεν αλλάζει. ΟΧΙ validate= εδώ: με αυτό, οι αλλαγές
            # ΟΛΟΥ του πίνακα δεν έφταναν στον server (χανόταν και το voucher).
            "Ημερομηνία": st.column_config.TextColumn(
                help="Πότε έστειλες το πακέτο, π.χ. 02/11/2026",
                width="small",
            ),
        },
    )


def _period_label(r: dict) -> str:
    """Αν το Excel δεν έδωσε περίοδο, τη βγάζουμε από τον κανόνα (εβδομάδα ή δεκαήμερο)."""
    p = r["period"]
    if p and p.lower() != "nan":
        return p
    start, end = purchase_period(r["check_date"])
    return f"{start:%d/%m} – {end:%d/%m}"


# ══════════════════════════════════════════════════════════════════════════════
def _flush(rows: list[dict]) -> dict:
    """
    Γράφει στο Sheet ό,τι πείραξε ο χρήστης.

    → {ημερομηνία επιταγής → voucher} όσων voucher γράφτηκαν τώρα, για να
      χρωματιστούν αμέσως (το df_t φορτώθηκε πριν την αποθήκευση).

    Το data_editor αφήνει στο session_state:
        {"edited_rows": {3: {"Έξοδα": "1250"}}, "added_rows": [], "deleted_rows": []}

    Μας λέει ρητά ποια γραμμή και ποια στήλη. Καμία μαντεψιά, κανένας βρόχος.
    """
    state = st.session_state.get(EDITOR_KEY)
    if not isinstance(state, dict):
        return {}

    edits = state.get("edited_rows") or {}
    if not edits:
        return {}

    saved, failed = 0, []
    fresh = {}

    for idx, changes in edits.items():
        i = int(idx)
        if i >= len(rows):
            continue

        sheet_row = rows[i]["_row"]
        if not sheet_row:
            continue

        for col, value in changes.items():
            field = EDITABLE.get(col)
            if not field:
                continue

            text = str(value or "")

            if update_timologiseis_field(sheet_row, field, text):
                saved += 1
                if field == "voucher":
                    cd = rows[i]["check_date"]
                    fresh[cd.date() if hasattr(cd, "date") else cd] = text.strip()
            else:
                failed.append(str(sheet_row))

    # ΠΑΝΤΑ καθαρίζουμε — αλλιώς η ίδια αλλαγή ξαναγράφεται σε κάθε rerun.
    state["edited_rows"] = {}

    if saved:
        c.note(f"Αποθηκεύτηκαν {saved} αλλαγές.", "ok")
    if failed:
        c.note(f"Δεν αποθηκεύτηκαν οι γραμμές {', '.join(failed)}. Δοκίμασε ξανά.", "bad")

    return fresh
