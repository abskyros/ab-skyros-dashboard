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
from core.metrics import as_dates, month_rows, check_period, cash_runway
from core.sheets import update_timologiseis_field, load_setting, save_setting
from ui import components as c


EDITOR_KEY = "month_editor"
CASH_SETTING = "cash_on_hand"   # κλειδί στο φύλλο settings για το ταμείο

COLS = ["Ημ. επιταγής", "Επιταγή", "Πωλήσεις περιόδου",
        "Έξοδα", "Μένει", "Αρ. επιταγής", "", "Κάλυψη ταμείου"]

# Ποιες στήλες γράφονται πίσω στο Sheet, και σε ποιο πεδίο.
EDITABLE = {
    "Αρ. επιταγής": "check_number",
    "Έξοδα": "expenses",
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
    _flush(rows)

    _summary(rows)

    # ── ΤΑΜΕΙΟ + ΚΑΛΥΨΗ ──
    #
    # Το ταμείο μπαίνει πάνω από τον πίνακα. Η κάλυψη κάθε επιταγής μπαίνει
    # ΜΕΣΑ στον πίνακα, ως στήλη με μπάρα — δίπλα στον αριθμό επιταγής.
    cash = _cash_input(key="month")
    runway = cash_runway(df_t, today, cash)

    # Χάρτης: ημερομηνία επιταγής → κάλυψη. Ο πίνακας δείχνει ΤΟΝ ΜΗΝΑ που
    # διάλεξες, ενώ η κάλυψη υπολογίζεται σε ΟΛΕΣ τις μελλοντικές επιταγές.
    # Έτσι, όποιον μήνα κι αν δεις, η μπάρα λέει την αλήθεια.
    coverage = {
        _cov_key(ch["date"]): ch
        for ch in runway["checks"]
    }

    _editor(rows, coverage)

    # Μια γραμμή σύνοψης κάτω από τον πίνακα — η γενική εικόνα με μια ματιά.
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
            help="Το ποσό που έχεις τώρα. Η στήλη «Κάλυψη ταμείου» δείχνει ως "
                 "πού φτάνει στις επόμενες επιταγές. Θυμάται την τελευταία τιμή.",
        )

    last = st.session_state.get(f"{ss_key}_saved")
    if cash != last:
        save_setting(CASH_SETTING, str(int(cash)))
        st.session_state[f"{ss_key}_saved"] = cash

    return cash


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
               foot=f"Πωλήσεις − επιταγές − έξοδα ({c.eur(total_exp)})"),
        cols=3,
    )


# ══════════════════════════════════════════════════════════════════════════════
def _editor(rows: list[dict], coverage: dict | None = None) -> None:
    """
    Ο πίνακας ανά περίοδο.

    coverage: {ημερομηνία επιταγής → {"fraction": 0-1, "status": full|partial|empty}}
    Αν δοθεί, προστίθεται στήλη «Κάλυψη ταμείου» με μπάρα σε ΚΑΘΕ γραμμή —
    δίπλα στον αριθμό επιταγής, στο ύψος της κάθε επιταγής.
    """
    c.section("Ανά περίοδο")
    st.caption("Συμπλήρωσε τον αριθμό επιταγής και τα έξοδα — αποθηκεύονται αυτόματα.")

    coverage = coverage or {}

    # Σήμα κατάστασης — το ProgressColumn δίνει ΕΝΑ χρώμα σε όλη τη στήλη,
    # οπότε το χρώμα το δίνουμε με ένα μικρό εικονίδιο δίπλα.
    MARK = {"full": "🟢", "partial": "🟠", "empty": "⚪", None: ""}

    table = pd.DataFrame([
        {
            "Ημ. επιταγής":      f"{r['check_date']:%d/%m/%Y}",
            "Περίοδος":          _period_label(r),
            "Επιταγή":           r["amount"],
            "Πωλήσεις περιόδου": r["sales"],
            "Έξοδα":             r["expenses_raw"],
            "Μένει":             r["balance"],
            "Αρ. επιταγής":      r["check_number"],
            "":                  MARK.get(
                                     (coverage.get(_cov_key(r["check_date"])) or {}).get("status")
                                 ),
            "Κάλυψη ταμείου":    (coverage.get(_cov_key(r["check_date"])) or {}).get("fraction"),
        }
        for r in rows
    ])

    money = st.column_config.NumberColumn(format="%.2f €", disabled=True)

    # ── ΧΡΩΜΑ ΑΝΑ ΣΤΗΛΗ ──
    #
    # Απαλές αποχρώσεις, ώστε το μάτι να «κλειδώνει» στη στήλη που διαβάζει.
    # Δεν είναι διακόσμηση: με 10 στήλες, το χρώμα είναι ο γρηγορότερος τρόπος
    # να μη χαθείς όταν σκρολάρεις οριζόντια.
    #
    # ΠΡΟΣΟΧΗ: το Streamlit εφαρμόζει Styler ΜΟΝΟ σε μη-επεξεργάσιμες στήλες.
    # Άρα «Αρ. επιταγής» και «Έξοδα» μένουν λευκές — που βολεύει: ξεχωρίζουν
    # αμέσως ως τα δύο πεδία που συμπληρώνεις εσύ.
    TINT = {
        "Ημ. επιταγής":      "#F1F5F9",   # γκρι-μπλε — η ταυτότητα της γραμμής
        "Επιταγή":           "#FEF2F2",   # απαλό κόκκινο — τι πληρώνεις
        "Πωλήσεις περιόδου": "#EFF6FF",   # απαλό μπλε — τι μπήκε
        "Μένει":             "#F0FDF4",   # απαλό πράσινο — το αποτέλεσμα
        "Κάλυψη ταμείου":    "#FFFBEB",   # απαλό κεχριμπάρι — η δεξαμενή
    }

    styled = table.style
    for col, color in TINT.items():
        if col in table.columns:
            styled = styled.set_properties(subset=[col], **{"background-color": color})

    st.data_editor(
        styled,
        key=EDITOR_KEY,
        width="stretch",
        hide_index=True,
        column_order=COLS,
        row_height=42,          # ψηλότερες γραμμές — να «αναπνέει» η μπάρα
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
            "": st.column_config.TextColumn(
                disabled=True,
                width="small",
                help="🟢 καλύπτεται πλήρως · 🟠 μερικώς · ⚪ δεν φτάνει",
            ),
            "Κάλυψη ταμείου": st.column_config.ProgressColumn(
                "Κάλυψη ταμείου",
                help="Πόσο καλύπτει το διαθέσιμο ταμείο αυτή την επιταγή, "
                     "αν πληρώσεις τις επιταγές με τη σειρά",
                format="percent",
                min_value=0.0,
                max_value=1.0,
                width="medium",
            ),
            "Έξοδα": st.column_config.TextColumn(
                help="Τα έξοδα της περιόδου σε ευρώ, π.χ. 1250.50",
                width="small",
            ),
        },
    )


def _cov_key(d) -> str:
    """Κλειδί αντιστοίχισης επιταγής ↔ κάλυψης. Η ημερομηνία, ως κείμενο."""
    dd = d.date() if hasattr(d, "date") else d
    return f"{dd:%Y-%m-%d}"


def _period_label(r: dict) -> str:
    """Αν το Excel δεν έδωσε περίοδο, τη φτιάχνουμε από τις 7 μέρες πριν την επιταγή."""
    p = r["period"]
    if p and p.lower() != "nan":
        return p
    start, end = check_period(r["check_date"])
    return f"{start:%d/%m} – {end:%d/%m}"


# ══════════════════════════════════════════════════════════════════════════════
def _flush(rows: list[dict]) -> None:
    """
    Γράφει στο Sheet ό,τι πείραξε ο χρήστης.

    Το data_editor αφήνει στο session_state:
        {"edited_rows": {3: {"Έξοδα": "1250"}}, "added_rows": [], "deleted_rows": []}

    Μας λέει ρητά ποια γραμμή και ποια στήλη. Καμία μαντεψιά, κανένας βρόχος.
    """
    state = st.session_state.get(EDITOR_KEY)
    if not isinstance(state, dict):
        return

    edits = state.get("edited_rows") or {}
    if not edits:
        return

    saved, failed = 0, []

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

            if update_timologiseis_field(sheet_row, field, str(value or "")):
                saved += 1
            else:
                failed.append(str(sheet_row))

    # ΠΑΝΤΑ καθαρίζουμε — αλλιώς η ίδια αλλαγή ξαναγράφεται σε κάθε rerun.
    state["edited_rows"] = {}

    if saved:
        c.note(f"Αποθηκεύτηκαν {saved} αλλαγές.", "ok")
    if failed:
        c.note(f"Δεν αποθηκεύτηκαν οι γραμμές {', '.join(failed)}. Δοκίμασε ξανά.", "bad")
