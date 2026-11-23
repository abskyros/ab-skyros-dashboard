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
  3. ΜΙΣΘΟΔΟΣΙΕΣ ΑΝΑ ΕΡΓΑΖΟΜΕΝΟ (κωδικός): ίδιος εργαζόμενος σε πολλά αρχεία ή
     email = μία φορά· άλλοι εργαζόμενοι (δεύτερη τράπεζα, αυτός που έλειπε) =
     προστίθενται. Αποδείξεις μετράνε μόνο όταν δεν υπάρχει συνολική λίστα.
  4. ΕΦΚΑ vs ΤΕΚΑ: από την Τ.Π.Τ.Ε. (ΤΕΚΑ = RF379177…) ή το όνομα αρχείου.

Κάθε εγγραφή: {"kind", "ref" (YYYY-MM), "sub", "amount", "pay_date", "detail",
              "emps" ({κωδικός εργαζομένου: ποσό} — μόνο μισθοδοσίες), "source"}
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
# ── ΜΙΣΘΟΔΟΣΙΕΣ: «πηγές» ανά ΕΡΓΑΖΟΜΕΝΟ ─────────────────────────────────────
#
# Κάθε αρχείο μισθοδοσίας γίνεται μια ΠΗΓΗ: {είδος, μήνας, πληρωμή, εργαζόμενοι}.
# Εργαζόμενος = ο ΚΩΔΙΚΟΣ του (π.χ. «0018» — ίδιος με το HR portal). Τα CSV έχουν
# μόνο IBAN· τον κωδικό τον βρίσκουμε από το XLS/την Κατάσταση του ίδιου email.
# Έτσι: ίδιος εργαζόμενος σε πολλά αρχεία = ΜΙΑ φορά· άλλοι εργαζόμενοι (δεύτερη
# τράπεζα, αυτός που έλειπε) = ΠΡΟΣΤΙΘΕΝΤΑΙ. Δεν αποθηκεύονται ονόματα/IBAN.

def _context(t: str) -> dict:
    """Είδος / μήνας από ένα κείμενο (περίοδος, περιγραφή CSV, θέμα email)."""
    bonus = _bonus(t)
    out = {"ref": _ref_month(t)}
    if bonus:
        out.update(kind=KIND_BONUS, sub=bonus)
    elif "ΜΙΣΘΟΔΟΣ" in t or out["ref"]:
        out.update(kind=KIND_PAYROLL, sub="")
    return out


def src_statement(raw: str, name: str = "") -> dict | None:
    """«Κατάσταση πληρωμής» για την τράπεζα: IBAN · ποσό · κωδικός ανά εργαζόμενο."""
    t = norm_greek(raw)
    if "ΣΥΝΟΛΙΚΟ ΠΟΣΟ" not in t or "ΙΒΑΝ" not in t:   # IBAN → ΙΒΑΝ μετά το norm_greek
        return None
    rows = re.findall(r"(GR\d{25})\s.*?\s" + _AMOUNT + r"\d{1,3}\s+(\d{4})\s+\d{9}", t)
    if not rows:
        return None
    ctx = _context(t)
    return {"src": "statement", **ctx, "name": name,
            "pay_date": _date(re.search(r"ΗΜ/?ΝΙΑ ΠΛΗΡΩΜΗΣ\s*:?\s*" + _DATE, t)),
            "emps": {code: _num(a) for _iban, a, code in rows},
            "iban": {iban: code for iban, _a, code in rows}}


def src_xls(df, name: str = "") -> dict | None:
    """XLS πληρωμών: Α/Α · Κωδικός · IBAN · Ονοματεπώνυμο · Ποσό (κεφαλίδα στην 1η γραμμή)."""
    import pandas as pd
    head = None
    for i in range(min(len(df), 6)):
        cells = [norm_greek(str(v)) for v in df.iloc[i].values]
        if any(c.startswith("ΚΩΔΙΚΟΣ") for c in cells) and any("ΙΒΑΝ" in c for c in cells) \
                and any(c.startswith("ΠΟΣΟ") for c in cells):
            head = (i, cells)
            break
    if head is None:
        return None
    i, cells = head
    c_code = next(k for k, c in enumerate(cells) if c.startswith("ΚΩΔΙΚΟΣ"))
    c_iban = next(k for k, c in enumerate(cells) if "ΙΒΑΝ" in c)
    c_amt = next(k for k, c in enumerate(cells) if c.startswith("ΠΟΣΟ"))
    emps, iban = {}, {}
    for _, r in df.iloc[i + 1:].iterrows():
        code = str(r.iloc[c_code]).strip()
        amt = pd.to_numeric(r.iloc[c_amt], errors="coerce")
        if not re.fullmatch(r"\d{1,6}", code) or pd.isna(amt):
            continue
        code = code.zfill(4)
        emps[code] = round(float(amt), 2)
        iban[str(r.iloc[c_iban]).strip().upper()] = code
    if not emps:
        return None
    return {"src": "xls", "name": name, "pay_date": None, "emps": emps, "iban": iban}


def src_csv(raw: str, name: str = "") -> dict | None:
    """CSV πληρωμών: IBAN;ποσό;EUR;περιγραφή (π.χ. «ΜΙΣΘΟΔΟΣΙΑ ΟΚΤΩΒΡΙΟΥ 2026»)."""
    by_iban, desc = {}, ""
    for line in raw.splitlines():
        p = [x.strip() for x in line.split(";")]
        if len(p) >= 2 and p[0][:2].upper() == "GR" and re.fullmatch(_AMOUNT, p[1] or ""):
            by_iban[p[0].upper()] = _num(p[1])
            if len(p) >= 4 and not desc:
                desc = norm_greek(p[3])
    if not by_iban:
        return None
    ctx = _context(desc) if ("?" not in desc) else {}      # χαλασμένη κωδικοποίηση → αγνοούμε
    return {"src": "csv", **ctx, "name": name, "pay_date": None, "by_iban": by_iban}


def src_mk(raw: str, name: str = "") -> dict | None:
    """
    «Μισθοδοτική κατάσταση»: μόνο ΣΥΝΟΛΟ (καθαρές αποδοχές από «Σύνολα Περιόδου»).
    Χρησιμοποιείται μόνο όταν δεν υπάρχει λίστα ανά εργαζόμενο στο ίδιο email.
    """
    t = norm_greek(raw)
    if "ΜΙΣΘΟΔΟΤΙΚΗ ΚΑΤΑΣΤΑΣΗ" not in t:
        return None
    m = re.search(r"ΣΥΝΟΛΑ ΠΕΡΙΟΔΟΥ([^:]*):\s*\d+\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", t)
    if not m:
        return None
    ctx = _context(m.group(1))
    ctx["ref"] = ctx.get("ref") or (_ref_month(t))
    if not ctx.get("kind"):
        ctx.update(kind=KIND_PAYROLL, sub="")
    return {"src": "mk", **ctx, "name": name, "pay_date": None, "total": _num(m.group(4))}


def src_receipts(raw: str, name: str = "") -> dict | None:
    """
    «Απόδειξη πληρωμής αποδοχών» — μία σελίδα ανά πληρωμή (κωδικός · περίοδος ·
    «Υπόλοιπο πληρωτέων αποδοχών» · ημερομηνία). ΟΛΕΣ «Δώρο …/Επίδομα …» → δώρο·
    ανάμεικτες (αποχώρηση: αποδοχές + αναλογίες) → συμπληρωματική.
    """
    t = norm_greek(raw)
    if "ΑΠΟΔΕΙΞΗ ΠΛΗΡΩΜΗΣ ΑΠΟΔΟΧΩΝ" not in t:
        return None
    emps, periods, dates = {}, [], []
    for page in t.split("ΑΠΟΔΕΙΞΗ ΠΛΗΡΩΜΗΣ ΑΠΟΔΟΧΩΝ")[1:]:
        code = re.search(r"ΚΩΔΙΚΟΣ\s*:\s*(\d{1,6})", page)
        amt = re.search(r"ΥΠΟΛΟΙΠΟ ΠΛΗΡΩΤΕΩΝ ΑΠΟΔΟΧΩΝ\s+" + _AMOUNT, page)
        per = re.search(r"ΠΕΡΙΟΔΟΣ\s*:?\s*([^\n]+)", page)
        if not (code and amt):
            continue
        c = code.group(1).zfill(4)
        emps[c] = round(emps.get(c, 0.0) + _num(amt.group(1)), 2)
        periods.append(per.group(1) if per else "")
        dates += [d for d in (_date(m) for m in re.finditer(_DATE, page)) if d]
    if not emps:
        return None
    bonuses = [_bonus(p) for p in periods]
    if all(bonuses):
        ctx = {"kind": KIND_BONUS, "sub": bonuses[0]}
    else:
        ctx = {"kind": KIND_SUPPL, "sub": ""}
    ctx["ref"] = next((r for r in (_ref_month(p) for p in periods) if r), None)
    return {"src": "receipts", **ctx, "name": name, "pay_date": max(dates) if dates else None,
            "emps": emps}


def combine_payroll(srcs: list[dict], subject: str, sent: date | None) -> tuple[list[dict], list[str]]:
    """
    Οι πηγές ΕΝΟΣ email → μία εγγραφή πληρωμής με τους εργαζόμενούς της.

      • Συνολικές λίστες (Κατάσταση, XLS, CSV) → ΕΝΩΣΗ εργαζομένων: ίδιος = μία
        φορά, άλλοι (δεύτερη τράπεζα) = προστίθενται.
      • Μισθοδοτική (μόνο σύνολο) → μόνο αν δεν υπάρχει λίστα ανά εργαζόμενο.
      • Αποδείξεις → μόνο αν δεν υπάρχει τίποτα από τα παραπάνω (αλλιώς είναι η
        ανάλυση της ίδιας πληρωμής).
    Είδος/μήνας: Κατάσταση → Μισθοδοτική → CSV → αποδείξεις → θέμα email → ημ/νία email.
    """
    notes: list[str] = []
    if not srcs:
        return [], notes
    lists = [s for s in srcs if s["src"] in ("statement", "xls", "csv")]
    mk = [s for s in srcs if s["src"] == "mk"]
    rec = [s for s in srcs if s["src"] == "receipts"]

    def pick(key):
        for group in ([s for s in srcs if s["src"] == "statement"], mk,
                      [s for s in srcs if s["src"] == "csv"], rec):
            for s in group:
                if s.get(key):
                    return s[key]
        return None

    subj = _context(norm_greek(subject or ""))
    kind = pick("kind") or subj.get("kind")
    sub = pick("sub") if pick("kind") else subj.get("sub", "")
    ref = pick("ref") or subj.get("ref")
    pay = pick("pay_date")

    if lists:
        iban2code = {}
        for s in lists:
            iban2code.update(s.get("iban", {}))
        emps: dict[str, float] = {}
        for s in sorted(lists, key=lambda x: {"statement": 0, "xls": 1, "csv": 2}[x["src"]]):
            for code, amt in s.get("emps", {}).items():
                emps.setdefault(code, amt)
            for iban, amt in s.get("by_iban", {}).items():
                emps.setdefault(iban2code.get(iban) or f"IBAN…{iban[-4:]}", amt)
        kind = kind or KIND_PAYROLL
        detail = f"{len(emps)} εργαζόμενοι"
    elif mk:
        m = mk[0]
        kind, sub, ref = m.get("kind") or kind, m.get("sub", sub), m.get("ref") or ref
        emps = {}
        total = m["total"]
        detail = "σύνολο μισθοδοτικής (χωρίς λίστα ανά εργαζόμενο)"
    elif rec:
        r = rec[0]
        kind, sub, ref = r["kind"], r.get("sub", ""), r.get("ref") or ref
        emps = {}
        for s in rec:
            for code, amt in s["emps"].items():
                emps[code] = round(emps.get(code, 0.0) + amt, 2)
        pay = pay or r.get("pay_date")
        detail = f"αποδείξεις πληρωμής · {len(emps)} εργαζόμενοι"
    else:
        return [], notes

    if not kind:
        notes.append("μισθοδοσία χωρίς είδος/μήνα — δεν καταχωρήθηκε")
        return [], notes
    pay = pay or sent                       # δεν γράφεται στο αρχείο → ημερομηνία email
    ref = ref or (f"{pay:%Y-%m}" if pay else None)
    if not ref:
        return [], notes
    amount = round(sum(emps.values()), 2) if emps else total
    files = ", ".join(sorted({s["name"] for s in srcs if s.get("name")}))[:120]
    return [{"kind": kind, "ref": ref, "sub": sub or "", "amount": amount, "pay_date": pay,
             "emps": emps, "detail": f"{sub + ' · ' if sub else ''}{detail}",
             "source": f"{(subject or '')[:60]} · {files}", "_doc": "payroll"}], notes


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


PARSERS = (parse_efka_body, parse_apd, parse_partners, parse_aade)
SOURCES = (src_statement, src_mk, src_receipts)        # PDF/κείμενο → πηγές μισθοδοσίας


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


def _sources(text: str, name: str) -> list[dict]:
    out = []
    for fn in SOURCES:
        try:
            s = fn(text, name)
        except Exception:
            s = None
        if s:
            out.append(s)
    return out


def parse_message(msg) -> tuple[list[dict], list[str]]:
    """
    → (εγγραφές, σημειώσεις) για ΕΝΑ email: κείμενο + κάθε συνημμένο.

    Το κείμενο του email υπάρχει συνήθως ΔΥΟ φορές (απλό + HTML): τα διαβάζουμε
    χωριστά και τα ίδια ποσά τα ενώνει το dedupe() — ΠΟΤΕ άθροισμα.
    """
    import pandas as pd

    recs, notes, srcs = [], [], []
    body_plain = msg.text or ""
    body_html = html_to_text(msg.html or "")
    for body in (body_plain, body_html):
        recs += parse_text(body)

    for att in getattr(msg, "attachments", []) or []:
        name = att.filename or ""
        low = name.lower()
        payload = att.payload or b""
        text = None
        if low.endswith(".pdf"):
            text = pdf_text(payload)
        elif low.endswith((".csv", ".txt")):
            text = _decode(payload)
            s = src_csv(text, name)
            if s:
                srcs.append(s)
        elif low.endswith((".xls", ".xlsx")):
            try:
                s = src_xls(pd.read_excel(io.BytesIO(payload), header=None), name)
            except Exception:
                s = None
            if s:
                srcs.append(s)
        elif low.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")):
            text = image_text(payload)
            if text is None:
                notes.append(f"φωτογραφία «{name}»: θέλει OCR (τη διαβάζει ο αυτόματος "
                             f"συγχρονισμός του GitHub)")
        if text:
            recs += parse_text(text, name)
            srcs += _sources(text, name)

    sent = None
    try:
        sent = msg.date.date() if msg.date else None
    except Exception:
        sent = None
    pay_recs, pay_notes = combine_payroll(srcs, msg.subject or "", sent)
    recs += pay_recs
    notes += pay_notes

    # Προθεσμία ΕΦΚΑ/ΤΕΚΑ: από το κείμενο («… έως 31.01.2025»), αλλιώς τέλος επόμενου μήνα.
    body = norm_greek(body_plain + "\n" + body_html)
    due = None
    if "ΕΦΚΑ" in body or "ΤΕΚΑ" in body:
        due = _date(re.search(r"ΕΩΣ\s*" + _DATE, body))
    for r in recs:
        if r["kind"] == KIND_EFKA and r.get("pay_date") is None:
            r["pay_date"] = due or _month_end_after(r["ref"])
        r.setdefault("source", f"{(msg.subject or '')[:60]}")
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
    emps = r.get("emps")
    if emps:                                   # ίδιοι εργαζόμενοι = ίδια πληρωμή
        return (kind, r["ref"], r.get("sub", ""), ",".join(sorted(emps)))
    return (kind, r["ref"], f"{float(r['amount']):.2f}")


def dedupe(recs: list[dict]) -> list[dict]:
    """
    Ένα ανά key(). Προτιμάμε την εγγραφή με ημερομηνία πληρωμής (π.χ. PDF πάνω από CSV).

    Μισθοδοσίες με εργαζόμενους: με τη σειρά των email, για κάθε πληρωμή (είδος +
    μήνας + δώρο) κρατάμε ΜΟΝΟ τους εργαζόμενους που δεν έχουν ήδη μετρηθεί —
    ο ίδιος εργαζόμενος σε επόμενο email δεν ξαναμετράει, ένας καινούργιος προστίθεται.
    """
    with_emps = [r for r in recs if r.get("emps")]
    others = [r for r in recs if not r.get("emps")]

    best: dict[tuple, dict] = {}
    for r in others:
        k = key(r)
        cur = best.get(k)
        if cur is None or (cur.get("pay_date") is None and r.get("pay_date") is not None):
            best[k] = r
    out = list(best.values())

    seen: dict[tuple, set] = {}
    for r in sorted(with_emps, key=lambda x: (str(x.get("email_date") or ""), str(x.get("pay_date") or ""))):
        k = (r["kind"], r["ref"], r.get("sub", ""))
        done = seen.setdefault(k, set())
        new = {c: a for c, a in r["emps"].items() if c not in done}
        if not new:
            continue
        done.update(new)
        out.append({**r, "emps": new, "amount": round(sum(new.values()), 2)})
    return out
