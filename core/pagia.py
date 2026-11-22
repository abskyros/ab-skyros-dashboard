"""
core/pagia.py — ΠΑΓΙΑ ΕΞΟΔΑ από τα email του λογιστή.

Ο λογιστής στέλνει ΠΑΝΤΑ από την ίδια διεύθυνση (PAGIA_EMAIL_SENDER), αλλά:
  • το θέμα αλλάζει («Μισθοδοσία…», «ΙΚΑ 10/2026 — …», «Υποχρεώσεις - Πληρωμές
    προς ΑΑΔΕ…») και μπορεί να έχει κι άλλες λέξεις,
  • τα ποσά μπορεί να είναι σε PDF, σε CSV, σε φωτογραφία, ή γραμμένα ΜΕΣΑ στο
    κείμενο του email.
Γι' αυτό ΔΕΝ βασιζόμαστε στο θέμα: διαβάζουμε ΟΛΟ το περιεχόμενο κάθε email
(κείμενο + κάθε συνημμένο) και αναγνωρίζουμε το έγγραφο από το ΤΙ ΓΡΑΦΕΙ.

Τρία είδη (ΚΑΙΝΟΣ = πώς φαίνεται στην εφαρμογή):

  ΜΙΣΘΟΔΟΣΙΑ  ← «Κατάσταση πληρωμής» της τράπεζας (ΚΑΤΑΣΤΑΣΗ.pdf):
                 Συνολικό Ποσό · Περίοδος (μήνας) · Ημ/νία Πληρωμής.
                 Εφεδρικά: το CSV πληρωμών («…;448,51;EUR;ΜΙΣΘΟΔΟΣΙΑ ΟΚΤΩΒΡΙΟΥ 2026»).
  ΕΦΚΑ/ΤΕΚΑ   ← «Στοιχεία Πληρωμής των Εισφορών ΕΦΚΑ & ΤΕΚΑ για τον Οκτώβριο 2026
                 με προθεσμία … έως 30.11.2026» + ΠΟΣΟ ΠΛΗΡΩΜΗΣ ανά φορέα.
  ΑΑΔΕ        ← «ΟΦΕΙΛΕΣ ΠΡΟΣ ΤΟ ΔΗΜΟΣΙΟ» (PartyDebts.pdf): γραμμές δόσεων
                 «1 30/11/2026 803,89 € 0,00 € 803,89 €» → ανά ημερομηνία λήξης.

Κάθε εγγραφή: {"kind", "ref" (YYYY-MM μήνας αναφοράς), "amount", "pay_date", "detail"}
"""

from __future__ import annotations

import io
import re
from datetime import date

from core.parsers import norm_greek

KIND_PAYROLL = "Μισθοδοσία"
KIND_EFKA = "ΕΦΚΑ/ΤΕΚΑ"
KIND_AADE = "ΑΑΔΕ"
KINDS = (KIND_PAYROLL, KIND_EFKA, KIND_AADE)

# Μήνες στη γενική/ονομαστική, χωρίς τόνους, ΚΕΦΑΛΑΙΑ (μετά το norm_greek).
_MONTHS = {
    "ΙΑΝΟΥΑΡ": 1, "ΦΕΒΡΟΥΑΡ": 2, "ΜΑΡΤ": 3, "ΑΠΡΙΛ": 4, "ΜΑΙ": 5, "ΜΑΪ": 5,
    "ΙΟΥΝ": 6, "ΙΟΥΛ": 7, "ΑΥΓΟΥΣΤ": 8, "ΣΕΠΤΕΜΒΡ": 9, "ΟΚΤΩΒΡ": 10,
    "ΝΟΕΜΒΡ": 11, "ΔΕΚΕΜΒΡ": 12,
}
_MONTH_RE = re.compile(r"(ΙΑΝΟΥΑΡ|ΦΕΒΡΟΥΑΡ|ΜΑΡΤ|ΑΠΡΙΛ|ΜΑΙ|ΙΟΥΝ|ΙΟΥΛ|ΑΥΓΟΥΣΤ|ΣΕΠΤΕΜΒΡ|ΟΚΤΩΒΡ|ΝΟΕΜΒΡ|ΔΕΚΕΜΒΡ)\w*\s+(20\d\d)")
_AMOUNT = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})"
_DATE = r"(\d{1,2})[./](\d{1,2})[./](20\d\d)"


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _date(m) -> date | None:
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except (ValueError, AttributeError):
        return None


def _ref_month(text: str) -> str | None:
    """«Οκτώβριος 2026» / «Οκτωβρίου 2026» / «ΟΚΤΩΒΡΙΟΥ 2026» → «2026-10»."""
    m = _MONTH_RE.search(text)
    if not m:
        return None
    month = _MONTHS[m.group(1)]
    return f"{int(m.group(2)):04d}-{month:02d}"


# ══════════════════════════════════════════════════════════════════════════════
# ΑΝΑΓΝΩΡΙΣΗ ΕΓΓΡΑΦΟΥ ΑΠΟ ΤΟ ΚΕΙΜΕΝΟ ΤΟΥ (όχι από το θέμα)
# ══════════════════════════════════════════════════════════════════════════════
def parse_payroll(raw: str) -> list[dict]:
    """Κατάσταση πληρωμής μισθοδοσίας: Συνολικό Ποσό + Περίοδος + Ημ/νία Πληρωμής."""
    t = norm_greek(raw)
    if "ΣΥΝΟΛΙΚΟ ΠΟΣΟ" not in t or "ΠΛΗΡΩΜΗΣ" not in t or "ΙΒΑΝ" not in t:   # IBAN → ΙΒΑΝ μετά το norm_greek
        return []
    ref = _ref_month(t)
    pay = _date(re.search(r"ΗΜ/?ΝΙΑ ΠΛΗΡΩΜΗΣ\s*:?\s*" + _DATE, t))
    # Το σύνολο: «Σύνολα : 16.384,07» στο τέλος — πιο αξιόπιστο από το πάνω μέρος,
    # όπου το PDF κολλάει το ποσό με το όνομα της τράπεζας.
    tot = re.findall(r"ΣΥΝΟΛΑ\s*:?\s*" + _AMOUNT, t)
    if not tot:
        tot = re.findall(r"ΣΥΝΟΛΙΚΟ ΠΟΣΟ\s*:?\s*" + _AMOUNT, t)
    if not (ref and tot):
        return []
    return [{"kind": KIND_PAYROLL, "ref": ref, "amount": _num(tot[-1]),
             "pay_date": pay, "detail": "Καθαρές αποδοχές (κατάσταση πληρωμής)"}]


def parse_payroll_csv(raw: str) -> list[dict]:
    """CSV πληρωμών: IBAN;ποσό;EUR;ΜΙΣΘΟΔΟΣΙΑ <ΜΗΝΑΣ> <ΕΤΟΣ> → άθροισμα."""
    total, ref = 0.0, None
    for line in raw.splitlines():
        p = [x.strip() for x in line.split(";")]
        if len(p) >= 4 and p[0][:2].upper() == "GR" and re.fullmatch(_AMOUNT, p[1] or ""):
            total += _num(p[1])
            ref = ref or _ref_month(norm_greek(p[3]))
    if not total or not ref or "ΜΙΣΘΟΔΟΣ" not in norm_greek(raw):
        return []
    return [{"kind": KIND_PAYROLL, "ref": ref, "amount": round(total, 2),
             "pay_date": None, "detail": "Καθαρές αποδοχές (αρχείο πληρωμών)"}]


def parse_efka(raw: str) -> list[dict]:
    """
    Εισφορές ΕΦΚΑ & ΤΕΚΑ: μήνας αναφοράς, προθεσμία, ποσό ανά φορέα.
    Τα αθροίζουμε σε μία εγγραφή «ΕΦΚΑ/ΤΕΚΑ» (πληρώνονται την ίδια προθεσμία).
    """
    t = norm_greek(raw)
    if "ΕΦΚΑ" not in t or "ΠΟΣΟ ΠΛΗΡΩΜΗΣ" not in t:
        return []
    ref = _ref_month(t)
    due = _date(re.search(r"(?:ΕΩΣ|ΠΡΟΘΕΣΜΙΑ[^0-9]{0,40})\s*" + _DATE, t))
    parts = {}
    for who, amt in re.findall(r"ΠΛΗΡΩΜΗ\W+(ΕΦΚΑ|ΤΕΚΑ)\W+ΠΟΣΟ ΠΛΗΡΩΜΗΣ\W+" + _AMOUNT, t):
        parts[who] = parts.get(who, 0.0) + _num(amt)
    if not parts:                                     # άλλη διάταξη: «ΕΦΚΑ … 5.450,15 €»
        for who, amt in re.findall(r"(ΕΦΚΑ|ΤΕΚΑ)[^€\d]{0,120}?" + _AMOUNT + r"\s*€", t):
            parts.setdefault(who, _num(amt))
    if not (ref and parts):
        return []
    detail = " + ".join(f"{k} {v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
                        for k, v in sorted(parts.items()))
    return [{"kind": KIND_EFKA, "ref": ref, "amount": round(sum(parts.values()), 2),
             "pay_date": due, "detail": detail}]


def parse_aade(raw: str) -> list[dict]:
    """
    Οφειλές προς ΑΑΔΕ: κάθε γραμμή δόσης «Α/Α λήξη υπόλοιπο προσαυξήσεις σύνολο».
    Αθροίζουμε ανά ημερομηνία λήξης — αυτό είναι που φεύγει από το ταμείο τη μέρα εκείνη.
    """
    t = norm_greek(raw)
    if "ΔΗΜΟΣΙΟ" not in t and "ΑΑΔΕ" not in t:
        return []
    by_due: dict[date, float] = {}
    for m in re.finditer(r"\b\d{1,3}\s+" + _DATE + r"\s+" + _AMOUNT + r"\s*€\s+" + _AMOUNT
                         + r"\s*€\s+" + _AMOUNT + r"\s*€", t):
        due = _date(m)
        if due:
            by_due[due] = by_due.get(due, 0.0) + _num(m.group(6))
    out = []
    for due, amt in sorted(by_due.items()):
        if amt > 0:
            out.append({"kind": KIND_AADE, "ref": f"{due:%Y-%m}", "amount": round(amt, 2),
                        "pay_date": due, "detail": "Οφειλές προς ΑΑΔΕ (λήξη)"})
    return out


PARSERS = (parse_payroll, parse_efka, parse_aade, parse_payroll_csv)


def parse_text(raw: str) -> list[dict]:
    """Δοκιμάζει ΟΛΑ τα είδη πάνω σε ένα κείμενο (email, PDF, CSV, OCR)."""
    out = []
    for fn in PARSERS:
        try:
            out.extend(fn(raw or ""))
        except Exception:                             # ένα χαλασμένο έγγραφο δεν ρίχνει τα άλλα
            continue
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ΚΕΙΜΕΝΟ ΑΠΟ ΚΑΘΕ ΜΟΡΦΗ
# ══════════════════════════════════════════════════════════════════════════════
def pdf_text(payload: bytes) -> str:
    """Κείμενο PDF (pypdf). Αν είναι σκαναρισμένο (χωρίς κείμενο) → OCR, όπου υπάρχει."""
    text = ""
    try:
        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(payload)).pages)
    except Exception:
        text = ""
    if len(text.strip()) >= 40:
        return text
    return _ocr_pdf(payload) or text


def _ocr_pdf(payload: bytes) -> str:
    from core.parsers import _load_ocr
    convert, tess = _load_ocr()
    if convert is None:
        return ""
    try:
        pages = convert(payload, dpi=250, first_page=1, last_page=4)
        return "\n".join(tess.image_to_string(p, lang="ell+eng") for p in pages)
    except Exception:
        return ""


def image_text(payload: bytes) -> str | None:
    """Φωτογραφία → OCR. None = δεν υπάρχει OCR εδώ (π.χ. Streamlit Cloud)."""
    from core.parsers import _load_ocr
    _convert, tess = _load_ocr()
    if tess is None:
        return None
    try:
        from PIL import Image
        return tess.image_to_string(Image.open(io.BytesIO(payload)), lang="ell+eng")
    except Exception:
        return ""


def html_to_text(html: str) -> str:
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|td|th|li|h\d)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&euro;", "€")
    return re.sub(r"[ \t]+", " ", t)


def _decode(payload: bytes) -> str:
    for enc in ("utf-8-sig", "cp1253", "iso-8859-7"):
        try:
            return payload.decode(enc)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", "ignore")


def parse_message(msg) -> tuple[list[dict], list[str]]:
    """
    → (εγγραφές, σημειώσεις) για ΕΝΑ email: κείμενο + κάθε συνημμένο.

    Από ίδιο email μπορεί να βγουν ίδια ποσά δύο φορές (π.χ. PDF ΚΑΙ CSV μισθοδοσίας)
    — τα διπλά φεύγουν στο dedupe() με κλειδί είδος+μήνας.
    """
    recs, notes = [], []
    body = (msg.text or "") + "\n" + html_to_text(msg.html or "")
    recs += parse_text(body)

    for att in getattr(msg, "attachments", []) or []:
        name = (att.filename or "").lower()
        payload = att.payload or b""
        if name.endswith(".pdf"):
            recs += parse_text(pdf_text(payload))
        elif name.endswith((".csv", ".txt")):
            recs += parse_text(_decode(payload))
        elif name.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")):
            t = image_text(payload)
            if t is None:
                notes.append(f"φωτογραφία «{att.filename}»: θέλει OCR (τρέχει στον αυτόματο "
                             f"συγχρονισμό του GitHub)")
            else:
                recs += parse_text(t)
    return dedupe(recs), notes


def dedupe(recs: list[dict]) -> list[dict]:
    """
    Ένα ποσό ανά είδος+μήνα (ΑΑΔΕ: ανά ημερομηνία λήξης).
    Προτιμάμε την εγγραφή που έχει ημερομηνία πληρωμής (π.χ. το PDF πάνω από το CSV).
    """
    best: dict[tuple, dict] = {}
    for r in recs:
        k = key(r)
        cur = best.get(k)
        if cur is None or (cur.get("pay_date") is None and r.get("pay_date") is not None):
            best[k] = r
    return list(best.values())


def key(r: dict) -> tuple:
    if r["kind"] == KIND_AADE and r.get("pay_date"):
        return (r["kind"], r["pay_date"].isoformat())
    return (r["kind"], r["ref"])
