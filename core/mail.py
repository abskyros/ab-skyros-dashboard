"""
core/mail.py — Κατεβάζει τα συνημμένα από τα email.

Τρεις πηγές, τρεις ροές:
  • Παραστατικά  ← Notifications@WeDoConnect.com → abf.skyros@gmail.com
  • Τιμολογήσεις ← ab.gr                         → abf.skyros@gmail.com
  • Πωλήσεις     ← abf.skyros@gmail.com          → ftoulisgm@gmail.com  (PDF, θέλει OCR)
"""

from __future__ import annotations

from datetime import date, timedelta

from imap_tools import MailBox, AND

from core.config import (
    IMAP_HOST,
    INVOICES_EMAIL_USER, INVOICES_EMAIL_SENDER,
    SALES_EMAIL_USER, SALES_EMAIL_SENDER, SALES_SUBJECT_KW,
    TIMOL_EMAIL_USER, TIMOL_SUBJECT_KW,
)
from core.parsers import parse_invoices, parse_timologisi, parse_sales_pdf


# ══════════════════════════════════════════════════════════════════════════════
# ΠΑΡΑΣΤΑΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
def fetch_invoices(password: str, limit: int = 60, since: date | None = None) -> tuple[list, list]:
    """→ (records, errors)"""
    records, errors = [], []

    criteria = AND(from_=INVOICES_EMAIL_SENDER) if since is None else \
        AND(from_=INVOICES_EMAIL_SENDER, date_gte=since)

    try:
        with MailBox(IMAP_HOST).login(INVOICES_EMAIL_USER, password) as mb:
            for msg in mb.fetch(criteria, limit=limit, reverse=True, mark_seen=False):
                for att in msg.attachments:
                    name = att.filename or ""
                    if name.lower().endswith((".xlsx", ".xls", ".csv")):
                        records.extend(parse_invoices(att.payload, name))
    except Exception as e:
        errors.append(_friendly(e))

    return records, errors


def fetch_all_invoices(
    password: str,
    since: date | None = None,
    on_progress=None,
) -> tuple[list, list, int]:
    """
    ΒΑΘΙΑ ΣΑΡΩΣΗ — κατεβάζει ΟΛΑ τα email παραστατικών, χωρίς όριο.

    → (records, errors, emails_scanned)

    Χρησιμοποιείται μόνο από τον βαθύ έλεγχο (core/backfill.py), για να
    ανακατασκευάσει τους αριθμούς παραστατικών των παλιών εγγραφών.

    ΔΕΝ βάζουμε limit. Θέλουμε την πλήρη εικόνα — αν χάσουμε έστω ένα email,
    οι γραμμές του θα φανούν «αταίριαστες» και δεν θα καθαριστούν.

    Το `on_progress(σαρωμένα, εγγραφές)` καλείται κάθε 10 email — για να μη
    φαίνεται κολλημένη η μπάρα προόδου σε 2 χρόνια αρχείου.
    """
    records, errors = [], []
    scanned = 0

    criteria = AND(from_=INVOICES_EMAIL_SENDER) if since is None else \
        AND(from_=INVOICES_EMAIL_SENDER, date_gte=since)

    try:
        with MailBox(IMAP_HOST).login(INVOICES_EMAIL_USER, password) as mb:
            for msg in mb.fetch(criteria, reverse=True, mark_seen=False, bulk=True):
                scanned += 1

                for att in msg.attachments:
                    name = att.filename or ""
                    if name.lower().endswith((".xlsx", ".xls", ".csv")):
                        records.extend(parse_invoices(att.payload, name))

                if on_progress and scanned % 10 == 0:
                    on_progress(scanned, len(records))

    except Exception as e:
        errors.append(_friendly(e))

    if on_progress:
        on_progress(scanned, len(records))

    return records, errors, scanned


# ══════════════════════════════════════════════════════════════════════════════
# ΤΙΜΟΛΟΓΗΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
def _is_timologisi(msg) -> bool:
    """Χαλαρό φίλτρο — το θέμα δεν είναι πάντα το ίδιο."""
    subject = (getattr(msg, "subject", "") or "").upper()
    sender = (getattr(msg, "from_", "") or "").lower()

    if TIMOL_SUBJECT_KW in subject:
        return True
    if "ab.gr" in sender and ("ΤΙΜΟΛΟΓ" in subject or "ΒΑΣΙΛΟΠΟΥΛ" in subject):
        return True
    return False


def fetch_timologiseis(password: str, limit: int = 200) -> tuple[list, list]:
    """→ (records, errors)"""
    records, errors = [], []
    scanned = matched = 0

    try:
        with MailBox(IMAP_HOST).login(TIMOL_EMAIL_USER, password) as mb:
            for msg in mb.fetch(limit=limit, reverse=True, mark_seen=False):
                scanned += 1
                if not _is_timologisi(msg):
                    continue
                matched += 1

                for att in msg.attachments:
                    name = att.filename or ""
                    if name.lower().endswith((".xlsx", ".xls")):
                        rec = parse_timologisi(att.payload)
                        if rec:
                            records.append(rec)
    except Exception as e:
        errors.append(_friendly(e))
        return records, errors

    if matched == 0 and scanned > 0:
        errors.append(
            f"Σαρώθηκαν {scanned} email, κανένα δεν είναι τιμολόγηση. "
            f"Έλεγξε το θέμα ή τον αποστολέα."
        )

    return records, errors


# ══════════════════════════════════════════════════════════════════════════════
# ΠΩΛΗΣΕΙΣ (PDF → OCR)
# ══════════════════════════════════════════════════════════════════════════════
def _is_sales(msg) -> bool:
    subject = (msg.subject or "").upper()
    sender = (msg.from_ or "").lower()

    if SALES_EMAIL_SENDER.lower() not in sender:
        return False
    return SALES_SUBJECT_KW in subject or "SKYROS" in subject


def fetch_sales(
    password: str,
    since: date | None = None,
    limit: int = 80,
    want: int | None = None,
) -> tuple[list, list, int]:
    """
    → (records, errors, emails_seen)

    Σταματάει μόλις βρει `want` εγγραφές — το OCR είναι αργό, δεν έχει νόημα
    να διαβάσουμε 80 PDF όταν ψάχνουμε τα χθεσινά.
    """
    records, errors = [], []
    seen = 0

    try:
        with MailBox(IMAP_HOST).login(SALES_EMAIL_USER, password) as mb:
            for msg in mb.fetch(limit=limit, reverse=True, mark_seen=False):
                if want and len(records) >= want:
                    break

                sent = _naive_date(msg)
                if since and sent and sent < since:
                    break  # τα email είναι σε φθίνουσα σειρά — από εδώ και πίσω, παλιά

                if not _is_sales(msg):
                    continue

                pdfs = [
                    a for a in msg.attachments
                    if a.filename and a.filename.lower().endswith(".pdf")
                ]
                if not pdfs:
                    continue

                seen += 1
                for pdf in pdfs:
                    rec = parse_sales_pdf(pdf.payload)
                    if rec["date"] and rec["net_sales"] is not None:
                        records.append(rec)
                        break

    except Exception as e:
        errors.append(_friendly(e))

    return records, errors, seen


# ══════════════════════════════════════════════════════════════════════════════
# ΒΟΗΘΗΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
def _naive_date(msg) -> date | None:
    """Το imap_tools επιστρέφει tz-aware datetime — δεν συγκρίνεται με date."""
    d = msg.date
    if not d:
        return None
    if hasattr(d, "tzinfo") and d.tzinfo:
        d = d.replace(tzinfo=None)
    return d.date()


def _friendly(e: Exception) -> str:
    """Το IMAP βγάζει κρυπτικά μηνύματα. Λέμε τι να κάνει ο χρήστης."""
    msg = str(e)
    if "AUTHENTICATIONFAILED" in msg.upper() or "Invalid credentials" in msg:
        return "Το app password δεν έγινε δεκτό. Έλεγξε το EMAIL_PASS στα secrets."
    if "timed out" in msg.lower():
        return "Το Gmail δεν απάντησε. Δοκίμασε ξανά σε λίγο."
    return msg
