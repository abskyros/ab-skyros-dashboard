"""
core/diag.py — Διαγνωστικά σύνδεσης email.

ΓΙΑΤΙ ΥΠΑΡΧΕΙ

Ο αυτόματος συγχρονισμός πωλήσεων ανοίγει ΜΟΝΟ μετά τις 15:00 (ώρα Ελλάδας).
Πριν απ' αυτό, το κύριο script βγαίνει αμέσως με «success» — χωρίς καν να
δοκιμάσει τον κωδικό email. Άρα το πρωί ΔΕΝ μπορείς να ξέρεις αν ο κωδικός
δουλεύει: ό,τι κωδικό κι αν βάλεις, φαίνεται «ΟΚ» αλλά δεν διαβάζει τίποτα.

Αυτό το εργαλείο δοκιμάζει τη σύνδεση IMAP ΤΩΡΑ, όποια ώρα, και στα δύο
mailboxes ξεχωριστά. Σου λέει καθαρά:
  • αν το login πέτυχε ή απέτυχε (λάθος κωδικός)
  • πόσα email βλέπει από τον σωστό αποστολέα
  • πόσα απ' αυτά έχουν συνημμένο (PDF/Excel)

Έτσι ξεχωρίζεις αμέσως «λάθος κωδικός» από «ο κωδικός είναι σωστός αλλά κάτι
άλλο φταίει» — χωρίς να περιμένεις τις 15:00 και χωρίς GitHub logs.

ΔΕΝ γράφει τίποτα. ΔΕΝ κάνει OCR. Μόνο συνδέεται και μετράει.
"""

from __future__ import annotations

from datetime import date, timedelta

from imap_tools import MailBox, AND

from core.config import (
    IMAP_HOST,
    INVOICES_EMAIL_USER, INVOICES_EMAIL_SENDER,
    SALES_EMAIL_USER, SALES_EMAIL_SENDER, SALES_SUBJECT_KW,
    TIMOL_EMAIL_USER, TIMOL_EMAIL_SENDER, TIMOL_SUBJECT_KW,
)


def _classify_error(e: Exception) -> str:
    """Κρυπτικό IMAP σφάλμα → καθαρό μήνυμα."""
    msg = str(e)
    up = msg.upper()
    if "AUTHENTICATIONFAILED" in up or "INVALID CREDENTIALS" in up:
        return "✗ Ο κωδικός ΔΕΝ έγινε δεκτός (λάθος app password)."
    if "timed out" in msg.lower():
        return "✗ Το Gmail δεν απάντησε (timeout). Δοκίμασε ξανά."
    if "Lookup failed" in msg or "nonexistent" in msg.lower():
        return "✗ Ο λογαριασμός email δεν βρέθηκε."
    return f"✗ Σφάλμα: {msg}"


def check_mailbox(
    user: str,
    password: str,
    sender: str,
    *,
    subject_kw: str | None = None,
    needs_pdf: bool = False,
    needs_attachment: bool = False,
    days_back: int = 10,
    limit: int = 40,
) -> dict:
    """
    Δοκιμάζει ΜΙΑ σύνδεση IMAP και μετράει τι βλέπει.

    → {
        "user": str,
        "ok": bool,              # πέτυχε το login;
        "error": str | None,     # αν απέτυχε, γιατί
        "total_seen": int,       # πόσα email από τον σωστό αποστολέα
        "matched": int,          # πόσα πέρασαν και το φίλτρο θέματος
        "with_file": int,        # πόσα απ' αυτά έχουν το σωστό συνημμένο
        "latest": str | None,    # ημ/νία + θέμα του πιο πρόσφατου σχετικού
      }
    """
    out = {
        "user": user, "ok": False, "error": None,
        "total_seen": 0, "matched": 0, "with_file": 0, "latest": None,
    }

    if not password:
        out["error"] = "✗ Λείπει ο κωδικός (κενό secret)."
        return out

    since = date.today() - timedelta(days=days_back)

    try:
        with MailBox(IMAP_HOST).login(user, password) as mb:
            out["ok"] = True   # το login πέτυχε — φτάσαμε ως εδώ

            # Ψάχνουμε μόνο πρόσφατα email από τον σωστό αποστολέα.
            criteria = AND(from_=sender, date_gte=since)
            latest_desc = None

            for msg in mb.fetch(criteria, limit=limit, reverse=True, mark_seen=False):
                out["total_seen"] += 1

                subj = (msg.subject or "")
                subj_up = subj.upper()

                # Φίλτρο θέματος (όπως το κάνει ο πραγματικός κώδικας).
                passes = True
                if subject_kw:
                    passes = (subject_kw.upper() in subj_up) or ("SKYROS" in subj_up)

                if not passes:
                    continue

                out["matched"] += 1

                # Έχει το σωστό συνημμένο;
                has_file = False
                if needs_pdf:
                    has_file = any(
                        (a.filename or "").lower().endswith(".pdf")
                        for a in msg.attachments
                    )
                elif needs_attachment:
                    has_file = any(
                        (a.filename or "").lower().endswith((".xlsx", ".xls", ".csv"))
                        for a in msg.attachments
                    )
                else:
                    has_file = len(msg.attachments) > 0

                if has_file:
                    out["with_file"] += 1

                if latest_desc is None:
                    d = msg.date
                    d_str = d.strftime("%d/%m %H:%M") if d else "—"
                    files = ", ".join(a.filename or "?" for a in msg.attachments) or "χωρίς συνημμένο"
                    latest_desc = f"{d_str} · «{subj[:40]}» · {files}"

            out["latest"] = latest_desc

    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["error"] = _classify_error(e)

    return out


def run_all(email_pass: str, sales_pass: str) -> list[dict]:
    """
    Τρέχει και τους τρεις ελέγχους (πωλήσεις, παραστατικά, τιμολογήσεις).

    → λίστα από {label, secret_name, result(dict)} για εμφάνιση.
    """
    return [
        {
            "label": "Πωλήσεις",
            "secret": "SALES_EMAIL_PASS",
            "mailbox": SALES_EMAIL_USER,
            "result": check_mailbox(
                SALES_EMAIL_USER, sales_pass, SALES_EMAIL_SENDER,
                subject_kw=SALES_SUBJECT_KW, needs_pdf=True,
            ),
        },
        {
            "label": "Παραστατικά",
            "secret": "EMAIL_PASS",
            "mailbox": INVOICES_EMAIL_USER,
            "result": check_mailbox(
                INVOICES_EMAIL_USER, email_pass, INVOICES_EMAIL_SENDER,
                needs_attachment=True,
            ),
        },
        {
            "label": "Τιμολογήσεις",
            "secret": "SALES_EMAIL_PASS",
            "mailbox": TIMOL_EMAIL_USER,
            "result": check_mailbox(
                TIMOL_EMAIL_USER, sales_pass, TIMOL_EMAIL_SENDER,
                subject_kw=TIMOL_SUBJECT_KW, needs_attachment=True,
            ),
        },
    ]


# ══════════════════════════════════════════════════════════════════════════════
# ΛΟΓΙΚΗ ΠΩΛΗΣΕΩΝ — γιατί (δεν) τρέχει ο συγχρονισμός
# ══════════════════════════════════════════════════════════════════════════════
LOOKBACK_DAYS = 21


def sales_logic_report() -> dict:
    """
    Δείχνει ΑΚΡΙΒΩΣ τι βλέπει ο μηχανισμός απόφασης των πωλήσεων — χωρίς OCR,
    χωρίς Gmail. Μόνο το ρολόι και το Sheet.

    Αναπαράγει πιστά τη λογική του jobs/sales_sync.py + jobs/sales_precheck.py,
    ώστε να φανεί ΓΙΑΤΙ μια μέρα δεν μπαίνει:
      • Είναι ανοιχτό το παράθυρο ώρας;
      • Ποια είναι η «νεότερη μέρα προς αναζήτηση»;
      • Ποιες μέρες του παραθύρου λείπουν;
      • Θα έτρεχε το OCR ή θα σταματούσε;

    → dict με όλα τα παραπάνω, για εμφάνιση.
    """
    from core.metrics import now_greece, sales_window_open
    from core.sheets import load_sales

    now = now_greece()
    out = {
        "now": f"{now:%d/%m/%Y %H:%M} ({now.tzname() or 'EET/EEST'})",
        "window_open": False,
        "window_why": "",
        "sheet_days": [],          # τελευταίες μέρες στο Sheet
        "sheet_count": 0,
        "newest_target": None,
        "missing": [],             # μέρες που λείπουν στο παράθυρο
        "would_run": False,
        "error": None,
    }

    # 1. Παράθυρο ώρας
    open_, why = sales_window_open(now)
    out["window_open"] = open_
    out["window_why"] = why

    # 2. Τι υπάρχει στο Sheet
    try:
        df = load_sales()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"Δεν διάβασα το Sheet: {e}"
        return out

    have = set()
    if not df.empty:
        have = {d.date() if hasattr(d, "date") else d for d in df["date"]}

    out["sheet_count"] = len(have)
    out["sheet_days"] = [f"{d:%d/%m/%Y}" for d in sorted(have, reverse=True)[:10]]

    # 3. Η λογική «ποιες μέρες λείπουν» (ίδια με sales_sync.py)
    newest_target = now.date() if now.hour >= 12 else now.date() - timedelta(days=1)
    out["newest_target"] = f"{newest_target:%d/%m/%Y}"

    window_days = [newest_target - timedelta(days=i) for i in range(LOOKBACK_DAYS + 1)]
    missing = [d for d in window_days if d not in have]
    out["missing"] = [f"{d:%d/%m/%Y}" for d in sorted(missing, reverse=True)]

    # 4. Θα έτρεχε το OCR;
    #    Τρέχει μόνο αν: παράθυρο ανοιχτό ΚΑΙ λείπει τουλάχιστον μία μέρα.
    out["would_run"] = bool(open_ and missing)

    return out
