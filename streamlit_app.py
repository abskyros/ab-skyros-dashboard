"""
streamlit_app.py — ΑΒ Σκύρος Dashboard

Το entry point. Δεν κάνει τίποτα άλλο εκτός από:
  1. Φορτώνει τα δεδομένα (μία φορά, cached)
  2. Διαβάζει ποια σελίδα ζητήθηκε από το URL
  3. Καλεί την αντίστοιχη view

Η λογική είναι στο core/, η εμφάνιση στο ui/, οι σελίδες στο views/.

ΕΚΔΟΣΗ: 6.0
"""

from datetime import date, timedelta

import streamlit as st

st.set_page_config(
    page_title="ΑΒ Σκύρος",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from core.config import PAGES, DEFAULT_PAGE
from core.sheets import (
    load_sales, load_invoices, load_timologiseis,
    merge_sales, merge_invoices, merge_timologiseis,
    clear_all_caches,
)
from core.mail import fetch_sales, fetch_invoices, fetch_timologiseis
from core.parsers import ocr_available

from ui import components as c

from views import overview, sales, invoices, timologiseis, month


VERSION = "6.0"


# ══════════════════════════════════════════════════════════════════════════════
def secret(key: str, fallback: str = "") -> str:
    try:
        return st.secrets.get(key, "") or fallback
    except Exception:
        return fallback


INV_PW = secret("EMAIL_PASS")
SALES_PW = secret("SALES_EMAIL_PASS") or INV_PW


def current_page() -> str:
    """Η σελίδα έρχεται από το URL — ώστε να δουλεύει το back και τα links."""
    p = st.query_params.get("page", DEFAULT_PAGE)
    return p if p in PAGES else DEFAULT_PAGE


# ══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    today = date.today()
    page = current_page()

    c.load_css()
    c.topbar(today)
    c.nav(page)

    df_s = load_sales()
    df_i = load_invoices()
    df_t = load_timologiseis()

    if page == "Επισκόπηση":
        overview.render(df_s, df_i, df_t, today)

    elif page == "Πωλήσεις":
        sales.render(df_s, today)

    elif page == "Παραστατικά":
        invoices.render(df_i, today)

    elif page == "Τιμολογήσεις":
        timologiseis.render(df_t, df_s, today, st.query_params.get("ty"))

    elif page == "Μήνας":
        month.render(df_t, df_s, today)

    sync_panel(df_s)
    footer()
    c.tabbar(page)


# ══════════════════════════════════════════════════════════════════════════════
def sync_panel(df_s) -> None:
    """
    Χειροκίνητη ενημέρωση.

    Κανονικά δεν χρειάζεται — τα GitHub Actions τρέχουν μόνα τους. Αυτό είναι
    για όταν θέλεις τα δεδομένα ΤΩΡΑ και δεν περιμένεις το επόμενο cron.
    """
    c.spacer(2)

    with st.expander("Ενημέρωση δεδομένων"):
        st.caption(
            "Παραστατικά και τιμολογήσεις ενημερώνονται κάθε 2 ώρες. "
            "Πωλήσεις κάθε μισή ώρα, από τις 20:00 ως τις 02:00. "
            "Πάτα εδώ μόνο αν τα θέλεις αμέσως."
        )

        a, b, d = st.columns(3)

        with a:
            if st.button("Πωλήσεις", key="sync_sales", width='stretch'):
                _sync_sales(df_s)

        with b:
            if st.button("Παραστατικά", key="sync_inv", width='stretch'):
                _sync_invoices()

        with d:
            if st.button("Τιμολογήσεις", key="sync_timol", width='stretch'):
                _sync_timologiseis()


def _sync_sales(df_s) -> None:
    if not SALES_PW:
        c.note("Λείπει το SALES_EMAIL_PASS από τα secrets.", "bad")
        return

    if not ocr_available():
        c.note(
            "Το OCR δεν είναι διαθέσιμο εδώ — χρειάζεται tesseract και poppler, "
            "που δεν υπάρχουν στο Streamlit Cloud. "
            "Οι πωλήσεις ενημερώνονται αυτόματα κάθε βράδυ μέσω GitHub Actions.",
            "info",
        )
        return

    # Ξεκινάμε λίγο πριν την τελευταία αποθηκευμένη μέρα, για να πιάσουμε τυχόν κενά.
    since = None
    if not df_s.empty:
        latest = df_s["date"].max()
        latest = latest.date() if hasattr(latest, "date") else latest
        since = latest - timedelta(days=4)

    with st.spinner("Διάβασμα email και OCR…"):
        records, errors, seen = fetch_sales(SALES_PW, since=since, limit=120, want=60)

    if errors:
        c.note(errors[0], "bad")
        return

    saved = merge_sales(records)

    if saved:
        c.note(f"{saved} νέες ημέρες από {seen} email.", "ok")
        st.rerun()
    elif seen == 0:
        c.note("Δεν έχει έρθει νέο email πωλήσεων ακόμη.", "info")
    else:
        c.note(f"Βρέθηκαν {seen} email, αλλά οι ημέρες υπάρχουν ήδη.", "info")


def _sync_invoices() -> None:
    if not INV_PW:
        c.note("Λείπει το EMAIL_PASS από τα secrets.", "bad")
        return

    with st.spinner("Διάβασμα email…"):
        records, errors = fetch_invoices(INV_PW, limit=60)

    if errors:
        c.note(errors[0], "bad")
        return

    saved = merge_invoices(records)
    c.note(
        f"{saved} νέα παραστατικά από {len(records)} εγγραφές." if saved
        else f"Βρέθηκαν {len(records)} εγγραφές — όλες υπάρχουν ήδη.",
        "ok" if saved else "info",
    )
    if saved:
        st.rerun()


def _sync_timologiseis() -> None:
    if not INV_PW:
        c.note("Λείπει το EMAIL_PASS από τα secrets.", "bad")
        return

    with st.spinner("Διάβασμα email…"):
        records, errors = fetch_timologiseis(INV_PW, limit=200)

    if errors:
        c.note(errors[0], "warn")
        return

    saved = merge_timologiseis(records)
    c.note(
        f"{saved} νέες τιμολογήσεις από {len(records)} που βρέθηκαν." if saved
        else f"Βρέθηκαν {len(records)} τιμολογήσεις — όλες υπάρχουν ήδη.",
        "ok" if saved else "info",
    )
    if saved:
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
def footer() -> None:
    c.html(
        '<div style="text-align:center;padding:2rem 0 1rem;font-size:.68rem;color:var(--dim)">'
        f'ΑΒ Σκύρος · v{VERSION}'
        '</div>'
    )


if __name__ == "__main__":
    main()
