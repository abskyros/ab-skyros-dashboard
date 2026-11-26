"""
core/bills.py — ΛΟΓΑΡΙΑΣΜΟΙ ΠΑΡΟΧΩΝ (ρεύμα, τηλέφωνο, νερό, ασφάλειες…).

Ο χρήστης δηλώνει έναν «πάροχο με email» (φύλλο «pagia_providers»):
  όνομα (= στήλη στα Πάγια) · email αποστολέα · «μόνο αν περιέχει» (προαιρετικό,
  π.χ. «NOVA» — όταν ο αποστολέας στέλνει για ΠΟΛΛΕΣ εταιρείες, όπως η epsilonnet)
  · μέρες προθεσμίας (όταν ο λογαριασμός ΔΕΝ γράφει λήξη).

Από ΚΑΘΕ email του παρόχου διαβάζουμε κείμενο + κάθε PDF (OCR όπου χρειάζεται):
  ΠΟΣΟ   «Πληρωτέο», «Συνολικό ποσό», «Ποσό πληρωμής», «Σύνολο λογαριασμού»,
         «Τελική αξία»… — και ελληνική (6.095,51) και αγγλική (6,095.51) μορφή
  ΛΗΞΗ   «λήξης», «Λήξη», «Εξόφληση έως», «Πληρωμή έως»… — αλλιώς έκδοση + μέρες
  ΤΑΥΤΟΤΗΤΑ  κωδικός πληρωμής RF / αριθμός παραστατικού / όνομα PDF — ο ίδιος
         λογαριασμός (π.χ. σε δύο γραμματοκιβώτια) μετράει ΜΙΑ φορά
Μπαίνει στον ΜΗΝΑ ΛΗΞΗΣ (όπως η ΑΑΔΕ και τα χειροκίνητα).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from core.parsers import norm_greek

BILL_PREFIX = "№ "            # sub των λογαριασμών → core.pagia.key() τους ξεχωρίζει

# Ποσό: 6.095,51 · 6,095.51 · 120,65 · 120.65 — ΟΧΙ ημερομηνίες (01.12.2026).
_NUM = r"(\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d{2})(?!\d|[.,]\d)"
_DATE = r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(20\d\d)"

# Λέξεις-κλειδιά ΠΟΣΟΥ — με σειρά προτίμησης (το «πληρωτέο» πάνω από το «σύνολο»).
AMOUNT_KEYS = (
    "ΠΛΗΡΩΤΕΟ ΠΟΣΟ", "ΠΟΣΟ ΠΛΗΡΩΜΗΣ", "ΠΟΣΟ ΠΡΟΣ ΠΛΗΡΩΜΗ", "ΠΛΗΡΩΤΕΟ",
    "ΣΥΝΟΛΙΚΟ ΠΟΣΟ ΠΛΗΡΩΜΗΣ", "ΣΥΝΟΛΙΚΟΥ ΠΟΣΟΥ", "ΣΥΝΟΛΙΚΟ ΠΟΣΟ", "ΣΥΝΟΛΟ ΠΛΗΡΩΜΗΣ",
    "ΣΥΝΟΛΟ ΛΟΓΑΡΙΑΣΜΟΥ", "ΠΟΣΟ ΛΟΓΑΡΙΑΣΜΟΥ", "ΤΕΛΙΚΗ ΑΞΙΑ", "ΣΥΝΟΛΙΚΗ ΑΞΙΑ",
    "ΓΕΝΙΚΟ ΣΥΝΟΛΟ", "ΣΥΝΟΛΟ ΠΡΟΣ ΠΛΗΡΩΜΗ",
)
# Λέξεις-κλειδιά ΛΗΞΗΣ.
DUE_KEYS = (
    "ΗΜΕΡΟΜΗΝΙΑ ΛΗΞΗΣ", "ΛΗΞΗ ΠΛΗΡΩΜΗΣ", "ΕΞΟΦΛΗΣΗ ΕΩΣ", "ΕΞΟΦΛΗΤΕΟ ΕΩΣ", "ΠΛΗΡΩΜΗ ΕΩΣ",
    "ΠΛΗΡΩΤΕΟ ΕΩΣ", "ΠΡΟΘΕΣΜΙΑ ΠΛΗΡΩΜΗΣ", "ΠΛΗΡΩΤΕΟ ΜΕΧΡΙ", "ΛΗΞΗΣ", "ΛΗΞΗ",
)
ISSUE_KEYS = ("ΗΜΕΡΟΜΗΝΙΑ ΕΚΔΟΣΗΣ", "ΗΜ/ΝΙΑ ΕΚΔΟΣΗΣ", "ΗΜΕΡΟΜΗΝΙΑ ΤΙΜΟΛΟΓΗΣΗΣ", "ΕΚΔΟΣΗΣ")


def to_amount(s: str) -> float | None:
    """«6,095.51» / «6.095,51» / «120,65» → float. Το ΤΕΛΕΥΤΑΙΟ διαχωριστικό = δεκαδικά."""
    s = re.sub(r"\s", "", s or "")
    if len(s) < 4 or s[-3] not in ".,":
        return None
    whole, dec = s[:-3], s[-2:]
    whole = re.sub(r"[.,]", "", whole)
    try:
        return float(f"{whole or 0}.{dec}")
    except ValueError:
        return None


def _date_of(m) -> date | None:
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except (ValueError, AttributeError):
        return None


def _after(t: str, keys: tuple, pattern: str, span: int) -> tuple[str | None, re.Match | None]:
    """Πρώτο `pattern` μέσα σε `span` χαρακτήρες μετά από λέξη-κλειδί (με σειρά προτίμησης)."""
    for k in keys:
        for km in re.finditer(r"(?<![Α-ΩA-Z])" + re.escape(k) + r"(?![Α-ΩA-Z])", t):
            m = re.search(pattern, t[km.end():km.end() + span])
            if m:
                return k, m
    return None, None


def parse_bill(raw: str) -> dict | None:
    """
    Κείμενο ΕΝΟΣ λογαριασμού → {amount, due, issue, period, ident, key_word} ή None
    (αν δεν βρεθεί ποσό). `due`/`issue` μπορεί να είναι None.
    """
    t = norm_greek(raw or "")
    t = re.sub(r"[ \t ]+", " ", t)
    key_word, m = _after(t, AMOUNT_KEYS, _NUM, 90)
    amount = to_amount(m.group(1)) if m else None
    if not amount or amount <= 0:
        return None
    _k, dm = _after(t, DUE_KEYS, _DATE, 40)
    _k, im = _after(t, ISSUE_KEYS, _DATE, 160)
    per = re.search(r"ΠΕΡΙΟΔ\w*\s*:?\s*(?:ΑΠΟ\s*)?" + _DATE + r"\s*(?:-|–|ΕΩΣ)\s*" + _DATE, t)
    period = ""
    if per:
        a = date(int(per.group(3)), int(per.group(2)), int(per.group(1)))
        b = date(int(per.group(6)), int(per.group(5)), int(per.group(4)))
        period = f"{a:%d/%m}–{b:%d/%m/%Y}"
    rf = re.search(r"\bRF\s?\d{2}[\dA-Z ]{8,30}", (raw or "").upper())
    ident = re.sub(r"\s", "", rf.group(0)) if rf else ""
    return {"amount": round(amount, 2), "due": _date_of(dm), "issue": _date_of(im),
            "period": period, "ident": ident, "key_word": key_word}


def bill_record(name: str, bill: dict, sent: date | None, days: int,
                ident: str = "", subject: str = "") -> dict:
    """Λογαριασμός → εγγραφή «pagia» (είδος = όνομα παρόχου, μήνας = μήνας ΛΗΞΗΣ)."""
    base = bill.get("issue") or sent or date.today()
    due = bill.get("due") or (base + timedelta(days=max(int(days or 0), 0)))
    # Ταυτότητα = ΛΗΞΗ + κωδικός (RF/αρχείο). Ο RF της nrg είναι ΙΔΙΟΣ σε όλους τους
    # λογαριασμούς (κωδικός πελάτη) → μόνος του θα έκανε 20 λογαριασμούς έναν.
    ident = f"{due:%Y-%m-%d} " + (bill.get("ident") or ident or f"{bill['amount']:.2f}")
    parts = []
    if bill.get("period"):
        parts.append(f"περίοδος {bill['period']}")
    if bill.get("issue"):
        parts.append(f"έκδοση {bill['issue']:%d/%m/%Y}")
    if not bill.get("due"):
        parts.append(f"λήξη = έκδοση + {int(days or 0)} μέρες (δεν γράφει)")
    return {"kind": name, "ref": f"{due:%Y-%m}", "sub": BILL_PREFIX + ident[:60],
            "amount": bill["amount"], "pay_date": due, "detail": " · ".join(parts) or "λογαριασμός",
            "email_date": sent, "source": f"πάροχος · {subject[:80]}", "check": "", "_doc": "bill"}


def matches(provider: dict, text: str) -> bool:
    """«Μόνο αν περιέχει» (αν έχει δοθεί) — π.χ. «NOVA» μέσα στο email ή στο PDF."""
    must = norm_greek(str(provider.get("must") or "")).strip()
    return not must or must in norm_greek(text or "")
