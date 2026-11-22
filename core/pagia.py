"""
core/pagia.py — ΠΑΓΙΑ ΕΞΟΔΑ από τα email του λογιστή.

Ο λογιστής στέλνει ΠΑΝΤΑ από την ίδια διεύθυνση (PAGIA_EMAIL_SENDER), αλλά το
θέμα, η μορφή (PDF, CSV, φωτογραφία, κείμενο email) και το ΠΟΥ γράφονται τα
ποσά αλλάζουν. Γι' αυτό ΔΕΝ βασιζόμαστε στο θέμα: διαβάζουμε ΟΛΟ το email
(κείμενο + κάθε συνημμένο) και αναγνωρίζουμε το έγγραφο από το ΠΕΡΙΕΧΟΜΕΝΟ.

ΕΙΔΗ (όπως φαίνονται στην εφαρμογή)
  Μισθοδοσία        «Κατάσταση πληρωμής» (PDF) ή CSV πληρωμών — η μηνιαία
  Δώρα/Επιδόματα    ίδια μορφή, αλλά «Δώρο Χριστουγέννων / Πάσχα / Επίδομα Αδείας»
  Συμπληρωματική    «Απόδειξη πληρωμής αποδοχών» (αποχώρηση: μέρες + αναλογίες)
  ΕΦΚΑ/ΤΕΚΑ         εισφορές προσωπικού: στο ΚΕΙΜΕΝΟ του email (νέα μορφή) ή σε
                    PDF «Συνοδευτικό έντυπο Α.Π.Δ.» (παλιά μορφή) — ένα ΕΦΚΑ και
                    ένα ΤΕΚΑ ανά μήνα
  ΕΦΚΑ εταίρων      «Ειδοποίηση πληρωμής ασφαλιστικών εισφορών» (ελ. επαγγελματίες)
  ΑΑΔΕ              «Οφειλές προς το Δημόσιο» — ανά ημερομηνία λήξης

ΚΑΝΟΝΕΣ (βλ. key() και parse_message())
  1. ΙΔΙΟ ποσό από πολλά σημεία (κείμενο + PDF, PDF + CSV, επόμενο email)
     → μετράει ΜΙΑ φορά.
  2. ΔΙΑΦΟΡΕΤΙΚΕΣ πληρωμές στον ίδιο μήνα (κανονική + συμπληρωματική + δώρο)
     → αθροίζονται (η καθεμία είναι δική της εγγραφή).
  3. Σε ΕΝΑ email με «Κατάσταση πληρωμής» ΚΑΙ αποδείξεις → μόνο η Κατάσταση
     (οι αποδείξεις είναι η ανάλυσή της). Μόνες τους → συμπληρωματική.
  4. ΕΦΚΑ vs ΤΕΚΑ: από την Τ.Π.Τ.Ε. (ΤΕΚΑ = RF379177…) ή το όνομα αρχείου.

Κάθε εγγραφή: {"kind", "ref" (YYYY-MM), "sub", "amount", "pay_date", "detail"}
"""

from __future__ import annotations

import calendar
import io
import re
from datetime import date

from core.parsers import norm_greek

KIND_PAYROLL = "Μισθοδοσία"
KIND_BONUS = "Δώρα/Επιδόματα"
KIND_SUPPL = "Συμπληρωματική"
KIND_EFKA = "ΕΦΚΑ/ΤΕΚΑ"
KIND_PARTNERS = "ΕΦΚΑ εταίρων"
KIND_AADE = "ΑΑΔΕ"
KINDS = (KIND_PAYROLL, KIND_BONUS, KIND_SUPPL, KIND_EFKA, KIND_PARTNERS, KIND_AADE)

# Είδη που ΔΕΝ προβλέπονται για το μέλλον (έκτακτα) — βλ. metrics.pagia_events.
NOT_PROJECTED = (KIND_SUPPL,)
# Είδη που προβλέπονται ΜΟΝΟ από τον ίδιο μήνα πέρσι (εποχικά — όχι «όπως τελευταία»).
SEASONAL = (KIND_BONUS,)

_MONTHS = {
    "ΙΑΝΟΥΑΡ": 1, "ΦΕΒΡΟΥΑΡ": 2, "ΜΑΡΤ": 3, "ΑΠΡΙΛ": 4, "ΜΑΙ": 5,
    "ΙΟΥΝ": 6, "ΙΟΥΛ": 7, "ΑΥΓΟΥΣΤ": 8, "ΣΕΠΤΕΜΒΡ": 9, "ΟΚΤΩΒΡ": 10,
    "ΝΟΕΜΒΡ": 11, "ΔΕΚΕΜΒΡ": 12,
}
_MONTH_RE = re.compile(r"(ΙΑΝΟΥΑΡ|ΦΕΒΡΟΥΑΡ|ΜΑΡΤ|ΑΠΡΙΛ|ΜΑΙ|ΙΟΥΝ|ΙΟΥΛ|ΑΥΓΟΥΣΤ|ΣΕΠΤΕΜΒΡ|ΟΚΤΩΒΡ|ΝΟΕΜΒΡ|ΔΕΚΕΜΒΡ)\w*\s+(20\d\d)")
_AMOUNT = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})"
_DATE = r"(\d{1,2})[./](\d{1,2})[./](20\d\d)"
_BONUS_RE = re.compile(r"ΔΩΡΟ\s+ΧΡΙΣΤΟΥΓΕΝΝΩΝ|ΔΩΡΟ\s+ΠΑΣΧΑ|ΕΠΙΔΟΜΑ\s+ΑΔΕΙΑΣ")
_BONUS_NAME = {"ΔΩΡΟ ΧΡΙΣΤΟΥΓΕΝΝΩΝ": "Δώρο Χριστουγέννων", "ΔΩΡΟ ΠΑΣΧΑ": "Δώρο Πάσχα",
               "ΕΠΙΔΟΜΑ ΑΔΕΙΑΣ": "Επίδομα Αδείας"}


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _date(m, base: int = 1) -> date | None:
    try:
        return date(int(m.group(base + 2)), int(m.group(base + 1)), int(m.group(base)))
    except (ValueError, AttributeError, TypeError):
        return None


def _ref_month(text: str) -> str | None:
    """«Οκτώβριος 2026» / «ΟΚΤΩΒΡΙΟΥ 2026» → «2026-10» (το πρώτο που βρίσκει)."""
    m = _MONTH_RE.search(text)
    if not m:
        return None
    return f"{int(m.group(2)):04d}-{_MONTHS[m.group(1)]:02d}"


def _eur(v: float) -> str:
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _month_end_after(ref: str) -> date:
    """Τελευταία μέρα του ΕΠΟΜΕΝΟΥ μήνα από το ref (προθεσμία ΕΦΚΑ αν δεν γράφεται)."""
    y, m = int(ref[:4]), int(ref[5:7]) + 1
    if m == 13:
        y, m = y + 1, 1
    return date(y, m, calendar.monthrange(y, m)[1])


def _bonus(t: str) -> str | None:
    m = _BONUS_RE.search(t)
    return _BONUS_NAME.get(re.sub(r"\s+", " ", m.group(0))) if m else None


# ══════════════════════════════════════════════════════════════════════════════
# ΑΝΑΓΝΩΣΤΕΣ — ο καθένας ελέγχει ότι το κείμενο είναι ΤΟ ΔΙΚΟ ΤΟΥ έγγραφο
# ══════════════════════════════════════════════════════════════════════════════
def parse_payroll(raw: str, name: str = "") -> list[dict]:
    """
    «Κατάσταση πληρωμής» μισθοδοσίας για την τράπεζα (π.χ. ΚΑΤΑΣΤΑΣΗ.pdf):
    Συνολικό Ποσό · Περίοδος · Ημ/νία Πληρωμής · λίστα IBAN.
    Αν η περίοδος είναι δώρο/επίδομα → «Δώρα/Επιδόματα».
    """
    t = norm_greek(raw)
    if "ΣΥΝΟΛΙΚΟ ΠΟΣΟ" not in t or "ΠΛΗΡΩΜΗΣ" not in t or "ΙΒΑΝ" not in t:   # IBAN → ΙΒΑΝ (norm_greek)
        return []
    pay = _date(re.search(r"ΗΜ/?ΝΙΑ ΠΛΗΡΩΜΗΣ\s*:?\s*" + _DATE, t))
    tot = re.findall(r"ΣΥΝΟΛΑ\s*:?\s*" + _AMOUNT, t) or re.findall(r"ΣΥΝΟΛΙΚΟ ΠΟΣΟ\s*:?\s*" + _AMOUNT, t)
    if not tot:
        return []
    bonus = _bonus(t)
    ref = _ref_month(t) or (f"{pay:%Y-%m}" if pay else None)
    if not ref:
        return []
    if bonus:
        return [{"kind": KIND_BONUS, "ref": ref, "sub": bonus, "amount": _num(tot[-1]),
                 "pay_date": pay, "detail": f"{bonus} (κατάσταση πληρωμής)", "_doc": "statement"}]
    return [{"kind": KIND_PAYROLL, "ref": ref, "sub": "", "amount": _num(tot[-1]),
             "pay_date": pay, "detail": "Καθαρές αποδοχές (κατάσταση πληρωμής)", "_doc": "statement"}]


def parse_payroll_csv(raw: str, name: str = "") -> list[dict]:
    """CSV πληρωμών: IBAN;ποσό;EUR;ΜΙΣΘΟΔΟΣΙΑ <ΜΗΝΑΣ> <ΕΤΟΣ> (ή ΔΩΡΟ …) → άθροισμα."""
    total, desc = 0.0, ""
    for line in raw.splitlines():
        p = [x.strip() for x in line.split(";")]
        if len(p) >= 4 and p[0][:2].upper() == "GR" and re.fullmatch(_AMOUNT, p[1] or ""):
            total += _num(p[1])
            desc = desc or norm_greek(p[3])
    if not total or not desc:
        return []
    bonus = _bonus(desc)
    ref = _ref_month(desc)
    if not (bonus or "ΜΙΣΘΟΔΟΣ" in desc) or not ref:
        return []
    kind, sub = (KIND_BONUS, bonus) if bonus else (KIND_PAYROLL, "")
    return [{"kind": kind, "ref": ref, "sub": sub, "amount": round(total, 2), "pay_date": None,
             "detail": (bonus or "Καθαρές αποδοχές") + " (αρχείο πληρωμών)", "_doc": "statement"}]


def parse_receipts(raw: str, name: str = "") -> list[dict]:
    """
    «Απόδειξη πληρωμής αποδοχών» (μία σελίδα ανά πληρωμή — π.χ. αποχώρηση:
    αποδοχές μήνα + δώρο + επίδομα + αποζημίωση αδείας). Άθροισμα των
    «Υπόλοιπο πληρωτέων αποδοχών» = ό,τι πληρώθηκε πραγματικά.
    """
    t = norm_greek(raw)
    if "ΑΠΟΔΕΙΞΗ ΠΛΗΡΩΜΗΣ ΑΠΟΔΟΧΩΝ" not in t:
        return []
    amounts = [_num(a) for a in re.findall(r"ΥΠΟΛΟΙΠΟ ΠΛΗΡΩΤΕΩΝ ΑΠΟΔΟΧΩΝ\s+" + _AMOUNT, t)]
    if not amounts:
        return []
    per = re.search(r"ΠΕΡΙΟΔΟΣ\s*:?\s*([^\n]+)", t)
    ref = _ref_month(per.group(1)) if per else _ref_month(t)
    dates = [d for d in (_date(m) for m in re.finditer(_DATE, t)) if d]
    pay = max(dates) if dates else None
    ref = ref or (f"{pay:%Y-%m}" if pay else None)
    if not ref:
        return []
    return [{"kind": KIND_SUPPL, "ref": ref, "sub": "", "amount": round(sum(amounts), 2),
             "pay_date": pay, "detail": f"{len(amounts)} αποδείξεις πληρωμής", "_doc": "receipts"}]


def parse_efka_body(raw: str, name: str = "") -> list[dict]:
    """
    ΝΕΑ μορφή (κείμενο email): «… Εισφορών ΕΦΚΑ & ΤΕΚΑ για τον Οκτώβριο 2026 με
    προθεσμία … έως 30.11.2026» + «1η ΠΛΗΡΩΜΗ • ΕΦΚΑ · ΠΟΣΟ ΠΛΗΡΩΜΗΣ 5.450,15 €».
    → μία εγγραφή ΑΝΑ ΦΟΡΕΑ (ΕΦΚΑ, ΤΕΚΑ) — ποτέ άθροισμα ίδιων ποσών.
    """
    t = norm_greek(raw)
    if "ΕΦΚΑ" not in t or "ΠΟΣΟ ΠΛΗΡΩΜΗΣ" not in t:
        return []
    ref = _ref_month(t)
    due = _date(re.search(r"ΕΩΣ\s*" + _DATE, t))
    parts: dict[str, float] = {}
    for who, amt in re.findall(r"ΠΛΗΡΩΜΗ\W+(ΕΦΚΑ|ΤΕΚΑ)\W+ΠΟΣΟ ΠΛΗΡΩΜΗΣ\W+" + _AMOUNT, t):
        parts.setdefault(who, _num(amt))                  # πρώτο που βρίσκει, όχι άθροισμα
    if not (ref and parts):
        return []
    return [{"kind": KIND_EFKA, "ref": ref, "sub": who, "amount": amt, "pay_date": due,
             "detail": f"{who} {_eur(amt)}", "_doc": "efka"} for who, amt in parts.items()]


def parse_apd(raw: str, name: str = "") -> list[dict]:
    """
    ΠΑΛΙΑ μορφή: «Συνοδευτικό έντυπο Α.Π.Δ.» (ένα PDF ανά φορέα).
    Μήνας από «ΑΠΟ ΜΗΝΑ/ΕΤΟΣ» · ποσό = ΚΑΤΑΒΛΗΘΕΙΣΕΣ ΕΙΣΦΟΡΕΣ της γραμμής
    «ΣΥΝΟΛΑ (χωρίς 18,74,116,123)» · ΤΕΚΑ αν η Τ.Π.Τ.Ε. είναι RF379177… ή το
    αρχείο λέει «ΤΕΚΑ». Η προθεσμία είναι στο κείμενο του email (parse_message).
    """
    t = norm_greek(raw)
    if "ΣΥΝΟΔΕΥΤΙΚΟ ΕΝΤΥΠΟ" not in t or "ΚΑΤΑΒΛΗΘΕΙΣΩΝ" not in t:
        return []
    m = re.search(r"ΣΥΝΟΛΑ\s*\(ΧΩΡΙΣ[^)]*\)\s*" + _AMOUNT + r"\s+" + _AMOUNT, t)
    p = re.search(r"/\s*(\d{1,2})\s+(20\d\d)", t)
    if not (m and p):
        return []
    ref = f"{int(p.group(2)):04d}-{int(p.group(1)):02d}"
    compact = re.sub(r"\s+", "", t)
    who = "ΤΕΚΑ" if ("RF379177" in compact.replace("ΡΦ", "RF") or "ΤΕΚΑ" in norm_greek(name)) else "ΕΦΚΑ"
    amt = _num(m.group(2))
    return [{"kind": KIND_EFKA, "ref": ref, "sub": who, "amount": amt, "pay_date": None,
             "detail": f"{who} {_eur(amt)}", "_doc": "efka"}]


def parse_partners(raw: str, name: str = "") -> list[dict]:
    """
    «Ειδοποίηση πληρωμής ασφαλιστικών εισφορών» — εισφορές ΕΤΑΙΡΩΝ (ελεύθεροι
    επαγγελματίες). Ένα έγγραφο ανά πρόσωπο: μήνας, προθεσμία, πληρωτέο ποσό.
    sub = τα 4 τελευταία ψηφία του ΑΦΜ (να ξεχωρίζουν οι εταίροι, όχι προσωπικά στοιχεία).
    """
    t = norm_greek(raw)
    if "ΕΙΔΟΠΟΙΗΣΗ ΠΛΗΡΩΜΗΣ ΑΣΦΑΛΙΣΤΙΚΩΝ ΕΙΣΦΟΡΩΝ" not in t:
        return []
    amt = re.search(r"ΠΛΗΡΩΤΕΟ ΠΟΣΟ\s*" + _AMOUNT, t)
    per = re.search(r"ΕΜΠΡΟΘΕΣΜΗΣ ΠΛΗΡΩΜΗΣ\s*(\d{1,2})/(20\d\d)\s+" + _DATE, t)
    afm = re.search(r"ΑΦΜ\s*:\s*(\d{9})", t)
    if not (amt and per):
        return []
    ref = f"{int(per.group(2)):04d}-{int(per.group(1)):02d}"
    due = _date(per, base=3)
    sub = f"…{afm.group(1)[-4:]}" if afm else ""
    return [{"kind": KIND_PARTNERS, "ref": ref, "sub": sub, "amount": _num(amt.group(1)),
             "pay_date": due, "detail": f"Εταίρος ΑΦΜ {sub}", "_doc": "partners"}]


def parse_aade(raw: str, name: str = "") -> list[dict]:
    """Οφειλές προς ΑΑΔΕ: γραμμές δόσεων «Α/Α λήξη υπόλοιπο προσαυξήσεις σύνολο» → ανά λήξη."""
    t = norm_greek(raw)
    if "ΟΦΕΙΛΕΣ ΠΡΟΣ ΤΟ ΔΗΜΟΣΙΟ" not in t and "ΑΑΔΕ" not in t:
        return []
    by_due: dict[date, float] = {}
    for m in re.finditer(r"\b\d{1,3}\s+" + _DATE + r"\s+" + _AMOUNT + r"\s*€\s+" + _AMOUNT
                         + r"\s*€\s+" + _AMOUNT + r"\s*€", t):
        due = _date(m)
        if due:
            by_due[due] = by_due.get(due, 0.0) + _num(m.group(6))
    return [{"kind": KIND_AADE, "ref": f"{due:%Y-%m}", "sub": "", "amount": round(amt, 2),
             "pay_date": due, "detail": "Οφειλές προς ΑΑΔΕ (λήξη)", "_doc": "aade"}
            for due, amt in sorted(by_due.items()) if amt > 0]


PARSERS = (parse_payroll, parse_payroll_csv, parse_receipts, parse_efka_body,
           parse_apd, parse_partners, parse_aade)


def parse_text(raw: str, name: str = "") -> list[dict]:
    """Δοκιμάζει ΟΛΟΥΣ τους αναγνώστες πάνω σε ένα κείμενο (email, PDF, CSV, OCR)."""
    out = []
    for fn in PARSERS:
        try:
            out.extend(fn(raw or "", name))
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
        pages = convert(payload, dpi=250, first_page=1, last_page=6)
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

    Το κείμενο του email υπάρχει συνήθως ΔΥΟ φορές (απλό + HTML): τα διαβάζουμε
    χωριστά και τα ίδια ποσά τα ενώνει το dedupe() — ΠΟΤΕ άθροισμα.
    """
    recs, notes = [], []
    body_plain = msg.text or ""
    body_html = html_to_text(msg.html or "")
    for body in (body_plain, body_html):
        recs += parse_text(body)

    for att in getattr(msg, "attachments", []) or []:
        name = att.filename or ""
        low = name.lower()
        payload = att.payload or b""
        if low.endswith(".pdf"):
            recs += parse_text(pdf_text(payload), name)
        elif low.endswith((".csv", ".txt")):
            recs += parse_text(_decode(payload), name)
        elif low.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")):
            t = image_text(payload)
            if t is None:
                notes.append(f"φωτογραφία «{name}»: θέλει OCR (τη διαβάζει ο αυτόματος "
                             f"συγχρονισμός του GitHub)")
            else:
                recs += parse_text(t, name)

    # Κανόνας 3: Κατάσταση πληρωμής + αποδείξεις στο ΙΔΙΟ email → μόνο η Κατάσταση.
    if any(r["_doc"] == "statement" for r in recs):
        recs = [r for r in recs if r["_doc"] != "receipts"]

    # Προθεσμία ΕΦΚΑ/ΤΕΚΑ: από το κείμενο («… έως 31.01.2025»), αλλιώς τέλος επόμενου μήνα.
    body = norm_greek(body_plain + "\n" + body_html)
    due = None
    if "ΕΦΚΑ" in body or "ΤΕΚΑ" in body:
        due = _date(re.search(r"ΕΩΣ\s*" + _DATE, body))
    for r in recs:
        if r["kind"] == KIND_EFKA and r.get("pay_date") is None:
            r["pay_date"] = due or _month_end_after(r["ref"])
    return dedupe(recs), notes


# ══════════════════════════════════════════════════════════════════════════════
# ΔΙΠΛΑ — ένα ποσό μετράει μία φορά, διαφορετικές πληρωμές αθροίζονται
# ══════════════════════════════════════════════════════════════════════════════
def key(r: dict) -> tuple:
    """
    Ταυτότητα μιας πληρωμής:
      ΑΑΔΕ                     → λήξη
      ΕΦΚΑ/ΤΕΚΑ, ΕΦΚΑ εταίρων  → μήνας + φορέας/εταίρος (ένα ποσό ο καθένας)
      μισθοδοσίες/δώρα/συμπλ.  → μήνας + ΠΟΣΟ (ίδιο ποσό = ίδια πληρωμή,
                                 άλλο ποσό = άλλη πληρωμή που προστίθεται)
    """
    kind = r["kind"]
    if kind == KIND_AADE:
        pay = r.get("pay_date")
        return (kind, pay.isoformat() if hasattr(pay, "isoformat") else str(pay))
    if kind in (KIND_EFKA, KIND_PARTNERS):
        return (kind, r["ref"], r.get("sub", ""))
    return (kind, r["ref"], f"{float(r['amount']):.2f}")


def dedupe(recs: list[dict]) -> list[dict]:
    """Ένα ανά key(). Προτιμάμε την εγγραφή με ημερομηνία πληρωμής (π.χ. PDF πάνω από CSV)."""
    best: dict[tuple, dict] = {}
    for r in recs:
        k = key(r)
        cur = best.get(k)
        if cur is None or (cur.get("pay_date") is None and r.get("pay_date") is not None):
            best[k] = r
    return list(best.values())
