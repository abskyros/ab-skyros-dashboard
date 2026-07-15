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
from core.metrics import today_greece
from core.github import trigger_workflow, last_run, available as gh_available

from ui import components as c
from ui import mobile

from views import overview, sales, invoices, timologiseis, month


VERSION = "6.7"


# ══════════════════════════════════════════════════════════════════════════════
def secret(key: str, fallback: str = "") -> str:
    try:
        return st.secrets.get(key, "") or fallback
    except Exception:
        return fallback


INV_PW = secret("EMAIL_PASS")
SALES_PW = secret("SALES_EMAIL_PASS") or INV_PW


def current_page() -> str:
    """
    Ποια σελίδα δείχνουμε.

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΤΟ BUG ΠΟΥ ΕΦΤΙΑΞΕ ΑΥΤΟ                                                │
    │                                                                        │
    │ Στα Παραστατικά, πατούσες «Ξεκίνα σάρωση» ή «Ξαναχτίσιμο», το script   │
    │ έκανε st.rerun() — και ΓΥΡΝΟΥΣΕΣ ΣΤΗΝ ΑΡΧΙΚΗ.                          │
    │                                                                        │
    │ Γιατί: η πλοήγηση είναι HTML anchors (?page=…), όχι st.button. Άρα το  │
    │ Streamlit δεν έχει «μνήμη» ποια σελίδα είσαι — τη διαβάζει ΜΟΝΟ από το │
    │ URL. Όταν ένα προγραμματιστικό st.rerun() τρέχει μέσα από βαθιά        │
    │ nested widgets (tabs → expander → tabs), το query param «page» δεν     │
    │ προλαβαίνει πάντα να διαβαστεί σωστά, κι έπεφτε στο DEFAULT_PAGE.       │
    │                                                                        │
    │ ΛΥΣΗ: κλειδώνουμε τη σελίδα και στο session_state. Το URL παραμένει η  │
    │ πηγή για πλοήγηση με links/back, αλλά το session_state είναι το δίχτυ  │
    │ ασφαλείας που επιβιώνει σε κάθε rerun.                                 │
    └────────────────────────────────────────────────────────────────────────┘
    """
    url_page = st.query_params.get("page")

    # Το URL έχει προτεραιότητα ΜΟΝΟ όταν όντως δείχνει έγκυρη σελίδα.
    # Έτσι, όταν ο χρήστης πατά link πλοήγησης, η αλλαγή γίνεται κανονικά.
    if url_page in PAGES:
        st.session_state["_page"] = url_page
        return url_page

    # Δεν υπάρχει (έγκυρο) page στο URL — π.χ. μετά από προγραμματιστικό rerun.
    # Θυμόμαστε πού ήμασταν.
    remembered = st.session_state.get("_page", DEFAULT_PAGE)

    # Ξαναγράφουμε το URL ώστε back/refresh να δουλεύουν σωστά από εδώ και πέρα.
    if remembered != DEFAULT_PAGE:
        st.query_params["page"] = remembered

    return remembered if remembered in PAGES else DEFAULT_PAGE


# ══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    today = today_greece()
    page = current_page()

    mobile.setup()          # εικονίδιο αρχικής οθόνης, κόκκινη μπάρα κατάστασης
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
            "Παραστατικά και τιμολογήσεις ενημερώνονται **κάθε 2 ώρες**. "
            "Πωλήσεις **κάθε 10 λεπτά, από τις 15:00** ώσπου να βρεθεί η αναφορά. "
            "Πάτα εδώ μόνο αν τα θέλεις αμέσως."
        )

        _workflow_status()

        a, b, d = st.columns(3)

        with a:
            if st.button("Πωλήσεις", key="sync_sales", width="stretch"):
                _sync_sales(df_s)

        with b:
            if st.button("Παραστατικά", key="sync_inv", width="stretch"):
                _sync_invoices()

        with d:
            if st.button("Τιμολογήσεις", key="sync_timol", width="stretch"):
                _sync_timologiseis()


def _workflow_status() -> None:
    """
    Η ΚΑΤΑΣΤΑΣΗ ΤΟΥ ΑΥΤΟΜΑΤΟΥ ΣΥΓΧΡΟΝΙΣΜΟΥ.

    Χωρίς αυτό, όταν κάτι χαλάσει, ο χρήστης κοιτάει μια άδεια κάρτα και δεν
    ξέρει αν φταίει το σύστημα ή απλώς δεν ήρθε το email.

    Ένα σιωπηλό σφάλμα είναι χειρότερο από ένα θορυβώδες.
    """
    if not gh_available():
        return

    run = last_run("sales_sync.yml")
    if not run:
        return

    status = run.get("status")
    result = run.get("conclusion")

    if status in ("queued", "in_progress"):
        c.note("Ο συγχρονισμός πωλήσεων τρέχει τώρα. Ανανέωσε σε 1-2 λεπτά.", "info")

    elif result == "failure":
        url = run.get("url", "")
        c.note(
            f"⚠️ <b>Ο τελευταίος αυτόματος συγχρονισμός πωλήσεων ΑΠΕΤΥΧΕ.</b><br><br>"
            f"Γι' αυτό δεν ενημερώνονται οι πωλήσεις. "
            f'<a href="{url}" target="_blank">Δες το σφάλμα στο GitHub</a>.',
            "bad",
        )


def _sync_sales(df_s) -> None:
    """
    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΓΙΑΤΙ ΔΕΝ ΤΡΕΧΕΙ ΤΟ OCR ΕΔΩ                                            │
    │                                                                        │
    │ Το Streamlit Cloud ΔΕΝ έχει tesseract και poppler. Είναι system libs,  │
    │ όχι python packages — δεν εγκαθίστανται με pip.                        │
    │                                                                        │
    │ Το παλιό κουμπί έλεγε «το OCR δεν είναι διαθέσιμο» και σταματούσε.     │
    │ Άχρηστο: όταν το GitHub Action αποτύχει, ο χρήστης δεν είχε ΚΑΝΕΝΑΝ    │
    │ τρόπο να το διορθώσει.                                                 │
    │                                                                        │
    │ Τώρα το κουμπί ΞΕΚΙΝΑΕΙ το GitHub Action — εκεί το OCR δουλεύει.       │
    └────────────────────────────────────────────────────────────────────────┘
    """
    latest = None
    if not df_s.empty:
        d = df_s["date"].max()
        latest = d.date() if hasattr(d, "date") else d

    if latest:
        gap = (today_greece() - latest).days
        st.caption(f"Τελευταία καταχώρηση: **{latest:%d/%m/%Y}** ({gap} μέρες πίσω)"
                   if gap > 1 else f"Τελευταία καταχώρηση: **{latest:%d/%m/%Y}**")

    # ── ΤΟΠΙΚΟ OCR (αν κάποιος τρέχει την εφαρμογή στον υπολογιστή του) ──
    if ocr_available():
        since = (latest - timedelta(days=4)) if latest else None

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
        return

    # ── STREAMLIT CLOUD ──
    #
    # Εδώ δεν υπάρχει OCR. Ο συγχρονισμός πωλήσεων γίνεται στο GitHub Actions,
    # ΑΥΤΟΜΑΤΑ, κάθε 10 λεπτά από τις 15:00 ώρα Ελλάδας ώσπου να βρεθεί η
    # αναφορά. Άρα ΔΕΝ χρειάζεται να κάνεις τίποτα — απλώς περιμένεις.
    #
    # Το κουμπί απλώς «σκουντάει» τον συγχρονισμό να τρέξει ΤΩΡΑ, αν βιάζεσαι.

    # Αν δεν υπάρχει token, ΔΕΝ στέλνουμε τον χρήστη σε χειρωνακτική διαδικασία.
    # Ο αυτόματος συγχρονισμός τρέχει έτσι κι αλλιώς. Το λέμε καθαρά.
    if not gh_available():
        c.note(
            "<b>Ο συγχρονισμός πωλήσεων τρέχει αυτόματα.</b><br><br>"
            "Κάθε 10 λεπτά, από τις <b>15:00</b> ώρα Ελλάδας, το σύστημα ψάχνει "
            "μόνο του την αναφορά της ημέρας — και μόλις έρθει το email, την "
            "καταχωρεί.<br><br>"
            "Δεν χρειάζεται να κάνεις κάτι. Αν μόλις ήρθε το email, ανανέωσε τη "
            "σελίδα σε λίγα λεπτά.",
            "info",
        )
        return

    ok, msg = trigger_workflow("sales_sync.yml")

    if ok:
        c.note(
            "<b>Ξεκίνησε ο συγχρονισμός πωλήσεων.</b><br><br>"
            "Τρέχει στο GitHub (εκεί υπάρχει το OCR). Θα πάρει 1-3 λεπτά.<br>"
            "Η σελίδα θα ανανεωθεί μόνη της.",
            "ok",
        )
        # Μικρή αναμονή και αυτόματη ανανέωση — να μη χρειαστεί να την πατήσει
        # ο χρήστης. Αν το OCR προλάβει, θα δει αμέσως τα νέα δεδομένα.
        import time
        time.sleep(2)
        st.rerun()
        return

    # ── ΤΟ ΚΟΥΜΠΙ ΑΠΕΤΥΧΕ (λ.χ. έληξε το token) ──
    #
    # Ακόμα κι εδώ, ο ΑΥΤΟΜΑΤΟΣ συγχρονισμός συνεχίζει να τρέχει κάθε 10 λεπτά.
    # Άρα καθησυχάζουμε — δεν ρίχνουμε τοίχο χειρωνακτικών βημάτων.
    c.note(
        "<b>Το χειροκίνητο σκούντημα δεν πέρασε αυτή τη φορά.</b><br><br>"
        "Δεν πειράζει: ο <b>αυτόματος</b> συγχρονισμός τρέχει μόνος του κάθε "
        "10 λεπτά, από τις 15:00 ώρα Ελλάδας. Η αναφορά θα μπει μόλις έρθει "
        "το email.<br><br>"
        "Αν θέλεις να το ψάξεις: ο τελευταίος αυτόματος συγχρονισμός φαίνεται "
        "πιο πάνω, στην κατάσταση.",
        "info",
    )

    repo = _repo_name()
    link = (
        f"https://github.com/{repo}/actions/workflows/sales_sync.yml"
        if repo else "https://github.com"
    )

    with st.expander("Λεπτομέρειες (προαιρετικά)"):
        st.markdown(
            f"Το χειροκίνητο κουμπί χρειάζεται ένα **GitHub token** για να "
            f"ξεκινήσει το workflow με ένα κλικ. Αν λείπει ή έληξε, το κουμπί "
            f"δεν δουλεύει — αλλά **ο αυτόματος συγχρονισμός συνεχίζει κανονικά**.\n\n"
            f"Σφάλμα: `{msg}`\n\n"
            f"Αν θέλεις να ξεκινήσεις τον συγχρονισμό με το χέρι αυτή τη στιγμή: "
            f"[άνοιξε το workflow στο GitHub]({link}) → **Run workflow**.\n\n"
            f"Για να δουλεύει ξανά το κουμπί, ανανέωσε το token στα Streamlit secrets:\n\n"
            "```toml\n"
            'GITHUB_TOKEN = "github_pat_..."\n'
            'GITHUB_REPO  = "abskyros/ab-skyros-dashboard"\n'
            "```"
        )


def _repo_name() -> str:
    try:
        return st.secrets.get("GITHUB_REPO", "")
    except Exception:
        return ""


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
    """
    Η έκδοση και η ώρα Ελλάδας.

    Η έκδοση: για να ξέρεις αμέσως αν ανέβηκε ο νέος κώδικας.
    Η ώρα: για να επιβεβαιώνεις ότι το σύστημα ξέρει τη σωστή ώρα (θερινή/χειμερινή).
    """
    from core.metrics import now_greece
    now = now_greece()

    c.html(
        '<div style="text-align:center;padding:2rem 0 1rem;font-size:.68rem;color:var(--dim)">'
        f'ΑΒ Σκύρος · v{VERSION} · {now:%H:%M} ({now.tzname() or "EET"})'
        '</div>'
    )


if __name__ == "__main__":
    main()
