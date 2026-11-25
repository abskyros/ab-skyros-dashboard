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
  3. ΜΙΣΘΟΔΟΣΙΕΣ ΑΝΑ ΕΡΓΑΖΟΜΕΝΟ (κωδικός + ποσό): ίδιος εργαζόμενος με ίδιο ποσό
     σε πολλά αρχεία ή email = μία φορά· άλλοι εργαζόμενοι (δεύτερη τράπεζα,
     αυτός που έλειπε) ή άλλο ποσό (δεύτερη πληρωμή δώρου) = προστίθενται.
     Αποδείξεις μετράνε μόνο όταν δεν υπάρχει συνολική λίστα.
  5. ΕΛΕΓΧΟΙ: κάθε μισθοδοσία συγκρίνεται με τα σύνολα των αρχείων («check»).
  4. ΕΦΚΑ vs ΤΕΚΑ: από την Τ.Π.Τ.Ε. (ΤΕΚΑ = RF379177…) ή το όνομα αρχείου.

Κάθε εγγραφή: {"kind", "ref" (YYYY-MM), "sub", "amount", "pay_date", "detail",
              "emps" ({κωδικός εργαζομένου: ποσό} — μόνο μισθοδοσίες),
              "who" ({κωδικός: (IBAN, όνομα)}), "check" (αποτέλεσμα ελέγχων), "source"}
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
KIND_ACCOUNTANT = "Λογιστής"
KIND_VAT = "ΦΠΑ"
KINDS = (KIND_PAYROLL, KIND_BONUS, KIND_SUPPL, KIND_EFKA, KIND_PARTNERS, KIND_AADE, KIND_ACCOUNTANT,
         KIND_VAT)

# Είδη που ΔΕΝ προβλέπονται για το μέλλον (έκτακτα) — βλ. metrics.pagia_events.
NOT_PROJECTED = (KIND_SUPPL,)
# Είδη που έρχονται ως ΑΠΟΔΕΙΞΗ (ήδη πληρωμένα) — ποτέ στις «Επόμενες πληρωμές».
ALREADY_PAID = (KIND_SUPPL,)
# Είδη που προβλέπονται ΜΟΝΟ από τον ίδιο μήνα πέρσι (εποχικά — όχι «όπως τελευταία»).
SEASONAL = (KIND_BONUS, KIND_VAT)          # ΦΠΑ: ανά τρίμηνο → μόνο «ίδιος μήνας πέρσι»

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


def _ref_numeric(text: str) -> str | None:
    """«Μισθοδοσία 09/2026» / «9-2026» → «2026-09» (μήνας γραμμένος με αριθμούς)."""
    m = re.search(r"(?<![\d/.])(0?[1-9]|1[0-2])\s*[/.-]\s*(20\d\d)(?!\d)", text or "")
    return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}" if m else None


def _name_bonus(name: str) -> str | None:
    """Δώρο/επίδομα από το ΟΝΟΜΑ αρχείου («ΚΑΤ_ΕΠΙΔΟΜΑ_ΑΔΕΙΑΣ_072025.pdf» → Επίδομα Αδείας).
    Όχι αν το όνομα λέει και «μισθοδοσία» (τότε μπορεί να έχει και τα δύο)."""
    t = norm_greek(re.sub(r"[_\-.]+", " ", name or ""))
    if "ΜΙΣΘΟΔ" in t:
        return None
    return _bonus(t)


def _bonus(t: str) -> str | None:
    m = _BONUS_RE.search(t)
    return _BONUS_NAME.get(re.sub(r"\s+", " ", m.group(0))) if m else None


# ══════════════════════════════════════════════════════════════════════════════
# ΑΝΑΓΝΩΣΤΕΣ — ο καθένας ελέγχει ότι το κείμενο είναι ΤΟ ΔΙΚΟ ΤΟΥ έγγραφο
# ══════════════════════════════════════════════════════════════════════════════
# ── ΜΙΣΘΟΔΟΣΙΕΣ: «πηγές» ανά ΕΡΓΑΖΟΜΕΝΟ ─────────────────────────────────────
#
# Κάθε αρχείο μισθοδοσίας δίνει μία ή περισσότερες ΠΗΓΕΣ (μία ανά ΕΝΟΤΗΤΑ: η
# «Κατάσταση πληρωμής» έχει μία σελίδα ανά είδος — μισθοδοσία, δώρο, επίδομα
# άδειας…). Πηγή = {είδος, μήνας, πληρωμή, rows: [(ταυτότητα, ποσό, IBAN, όνομα)]}.
#
# Ταυτότητα εργαζομένου = ο ΚΩΔΙΚΟΣ λογιστηρίου (π.χ. «0018», ίδιος με το HR).
# Όπου το αρχείο δεν τον έχει (CSV, παλιά Excel), βρίσκεται από το IBAN — από τα
# άλλα αρχεία του ίδιου email ή από όσα ξέρουμε ήδη (`known`). Αλλιώς μένει
# «ΙΒΑΝ:…» / «ΛΟΓ:…» και αντιστοιχίζεται αργότερα (core.sheets.merge_misthodosies).
#
# ΕΛΕΓΧΟΙ (κάθε πηγή κρατά "warn" και "ok"):
#   • άθροισμα εργαζομένων = «ΣΥΝΟΛΑ» της ενότητας · πλήθος = «ΣΥΝΟΛΟ ΕΡΓΑΖΟΜΕΝΩΝ»
#   • άθροισμα ενοτήτων = «ΣΥΝΟΛΙΚΟ ΠΟΣΟ» του αρχείου · Excel: γραμμή συνόλου
#   • ίδιος εργαζόμενος σε δύο αρχεία του ίδιου email → ίδιο ποσό
#   • μισθοδοτική (ΜΚ) = άθροισμα της μισθοδοσίας από τις λίστες τράπεζας

_ROW = re.compile(r"(GR\d{25})\s+(.*?)\s+" + _AMOUNT + r"(\d{1,3})\s+(\d{4,6})\s+(\d{9})")
_ROW_OLD = re.compile(r"^\s*\d{1,3}\s+(GR\d{25})\s+(.+?)\s+" + _AMOUNT + r"\s*$", re.M)
_PERIOD = re.compile(r"\d{1,2}/\d{1,2}/20\d\d\s*-\s*(\d{1,2})/(\d{1,2})/(20\d\d)\s*-\s*([^\n]*)")
_SUPPL_RE = re.compile(r"ΑΠΟΧΩΡ|ΑΠΟΖΗΜΙΩΣ|ΣΥΜΠΛΗΡΩΜ|ΑΠΟΛΥΣ|ΛΥΣΗ ΣΥΜΒ")


def _cents(v: float) -> int:
    return int(round(float(v) * 100))


def _context(t: str) -> dict:
    """Είδος / μήνας από ένα κείμενο (περίοδος, περιγραφή CSV, θέμα email)."""
    bonus = _bonus(t)
    out = {"ref": _ref_month(t)}
    if bonus:
        out.update(kind=KIND_BONUS, sub=bonus)
    elif _SUPPL_RE.search(t):
        out.update(kind=KIND_SUPPL, sub="")
    elif "ΜΙΣΘΟΔΟΣ" in t or out["ref"]:
        out.update(kind=KIND_PAYROLL, sub="")
    return out


def _label_context(label: str, m: int, y: int) -> dict:
    """
    Η γραμμή «01/12/2025 - 31/12/2025 - ΕΠΙΔΟΜΑ ΑΔΕΙΑΣ 2» μιας ενότητας:
    μήνας ονομαστικά → μισθοδοσία· δώρο/επίδομα → δώρα (με τον αριθμό, αν έχει,
    ώστε «Επίδομα Αδείας» και «Επίδομα Αδείας 2» να είναι ΔΥΟ πληρωμές).
    """
    lab = norm_greek(label).strip()
    ctx = _context(lab)
    ctx["ref"] = ctx.get("ref") or f"{y:04d}-{m:02d}"
    if not ctx.get("kind"):
        ctx.update(kind=KIND_PAYROLL, sub="")
    if ctx["kind"] == KIND_BONUS:
        num = re.search(r"\s(\d{1,2})\s*$", lab)
        if num:
            ctx["sub"] = f"{ctx['sub']} {num.group(1)}"
    return ctx


def src_statement(raw: str, name: str = "") -> list[dict]:
    """
    «Κατάσταση πληρωμής» για την τράπεζα — μία πηγή ΑΝΑ ΕΝΟΤΗΤΑ (σελίδες που
    κλείνουν με «ΣΥΝΟΛΑ : …»). Γραμμή: IBAN · όνομα · ποσό+Α/Α · κωδικός · ΑΦΜ.
    """
    t = norm_greek(raw)
    if "ΣΥΝΟΛΙΚΟ ΠΟΣΟ" not in t or "ΙΒΑΝ" not in t:   # IBAN → ΙΒΑΝ μετά το norm_greek
        return []
    pay = _date(re.search(r"ΗΜ/?ΝΙΑ ΠΛΗΡΩΜΗΣ\s*:?\s*" + _DATE, t))
    head = t[:t.find("ΙΒΑΝ ΟΝΟΜΑΤΕΠΩΝΥΜΟ")] if "ΙΒΑΝ ΟΝΟΜΑΤΕΠΩΝΥΜΟ" in t else ""
    g = re.search(_AMOUNT, head)
    grand = _num(g.group(1)) if g else None

    chunks, start = [], 0
    for m in re.finditer(r"ΣΥΝΟΛΑ\s*:\s*" + _AMOUNT, t):
        chunks.append((t[start:m.start()], _num(m.group(1))))
        start = m.end()
    if not chunks:                                   # χωρίς «ΣΥΝΟΛΑ» → όλο μαζί
        chunks = [(t, None)]

    out = []
    for chunk, declared in chunks:
        rows = _ROW.findall(chunk)
        if not rows:
            # ΠΑΛΙΑ μορφή (2024, «ΑΡΧΕΙΟ ΠΛΗΡΩΜΗΣ»): «Α/Α IBAN ΟΝΟΜΑ ΤΡΑΠΕΖΑ ποσό» — χωρίς
            # κωδικό/ΑΦΜ → ο εργαζόμενος αναγνωρίζεται από το IBAN (βλ. combine_payroll).
            rows = [(iban, " ".join(nm.split()[:2]), a, "", "ΙΒΑΝ:" + iban, "")
                    for iban, nm, a in _ROW_OLD.findall(chunk)]
        if not rows:
            continue
        per = _PERIOD.search(chunk)
        if per:
            ctx = _label_context(per.group(4), int(per.group(2)), int(per.group(3)))
            label = " ".join(norm_greek(per.group(4)).split())
        else:
            ctx, label = _context(chunk), ""
        tag = label or name
        warn, ok = [], 0
        total = round(sum(_num(r[2]) for r in rows), 2)
        if declared is None:
            warn.append(f"«{tag}»: δεν βρέθηκε «ΣΥΝΟΛΑ» για έλεγχο")
        elif _cents(total) != _cents(declared):
            warn.append(f"«{tag}»: εργαζόμενοι {_eur(total)} ≠ ΣΥΝΟΛΑ {_eur(declared)} "
                        f"(κάποια γραμμή δεν διαβάστηκε)")
        else:
            ok += 1
        cnt = re.search(r"ΣΥΝΟΛΟ ΕΡΓΑΖΟΜΕΝΩΝ\s*:[^\n]*?(\d{1,4})\s*$", chunk, re.M)
        if cnt:
            if int(cnt.group(1)) != len(rows):
                warn.append(f"«{tag}»: διαβάστηκαν {len(rows)} εργαζόμενοι, "
                            f"το αρχείο γράφει {cnt.group(1)}")
            else:
                ok += 1
        out.append({"src": "statement", **ctx, "name": name, "label": label, "pay_date": pay,
                    "warn": warn, "ok": ok,
                    "rows": [(code if code.startswith("ΙΒΑΝ:") else code.zfill(4), _num(a), iban,
                              " ".join(nm.split()))
                             for iban, nm, a, _aa, code, _afm in rows]})
    if out and grand is not None and all(c[1] is not None for c in chunks):
        decl = round(sum(c[1] for c in chunks), 2)
        if _cents(decl) != _cents(grand):
            out[0]["warn"].append(f"«{name}»: ενότητες {_eur(decl)} ≠ ΣΥΝΟΛΙΚΟ ΠΟΣΟ {_eur(grand)}")
        else:
            out[0]["ok"] += 1
    return out


def src_xls(df, name: str = "") -> list[dict]:
    """
    Excel πληρωμών (ένα φύλλο): κεφαλίδα με ΠΟΣΟ και ΚΩΔΙΚΟ ή IBAN ή ΛΟΓΑΡΙΑΣΜΟ
    (τα παλιά είχαν μόνο αριθμό λογαριασμού) · προαιρετικά ονοματεπώνυμο.
    Γραμμή χωρίς εργαζόμενο αλλά με ποσό = σύνολο → έλεγχος αθροίσματος.
    """
    import pandas as pd
    head = None
    for i in range(min(len(df), 12)):
        cells = [norm_greek(str(v)).strip() for v in df.iloc[i].values]
        has_amt = any(c.startswith(("ΠΟΣΟ", "ΠΛΗΡΩΤΕΟ")) for c in cells)   # 2024: «Πληρωτέο»
        has_id = any(c.startswith("ΚΩΔΙΚΟΣ") or "ΙΒΑΝ" in c or "ΛΟΓΑΡΙΑΣΜ" in c for c in cells)
        if has_amt and has_id:
            head = (i, cells)
            break
    if head is None:                     # χωρίς κεφαλίδα: IBAN · ποσό · EUR · περιγραφή (σαν το CSV)
        lines = []
        for _, r in df.iterrows():
            v = [str(x).strip() for x in r.values]
            amt = pd.to_numeric(r.iloc[1], errors="coerce") if len(v) >= 2 else float("nan")
            if v and re.fullmatch(r"GR\d{25}", v[0].upper().replace(" ", "")) and not pd.isna(amt):
                desc = v[3] if len(v) >= 4 and v[3].lower() not in ("nan", "none") else ""
                lines.append(f"{v[0]};{float(amt):.2f}".replace(".", ",") + f";EUR;{desc}")
        return src_csv("\n".join(lines), name) if lines else []
    i, cells = head

    def col(test):
        return next((k for k, c in enumerate(cells) if test(c)), None)

    c_code = col(lambda c: c.startswith("ΚΩΔΙΚΟΣ") and "ΤΡΑΠΕΖ" not in c)
    c_iban = col(lambda c: "ΙΒΑΝ" in c)
    if c_iban is None:
        c_iban = col(lambda c: "ΛΟΓΑΡΙΑΣΜ" in c)
    c_amt = col(lambda c: c.startswith("ΠΟΣΟ"))
    if c_amt is None:
        c_amt = col(lambda c: c.startswith("ΠΛΗΡΩΤΕΟ"))
    c_name = col(lambda c: "ΟΝΟΜΑΤΕΠ" in c or c.startswith("ΕΠΩΝΥΜ") or c.startswith("ΟΝΟΜΑ"))
    rows, footer = [], None
    for _, r in df.iloc[i + 1:].iterrows():
        amt = pd.to_numeric(r.iloc[c_amt], errors="coerce")
        if pd.isna(amt):
            continue
        code = str(r.iloc[c_code]).strip() if c_code is not None else ""
        code = code[:-2] if code.endswith(".0") else code
        acct = str(r.iloc[c_iban]).strip().upper().replace(" ", "") if c_iban is not None else ""
        acct = "" if acct in ("NAN", "NONE") else acct
        nm = str(r.iloc[c_name]).strip() if c_name is not None else ""
        nm = "" if nm.lower() in ("nan", "none") else " ".join(nm.split())
        digits = re.sub(r"\D", "", acct)
        if re.fullmatch(r"\d{1,6}", code):
            ident = code.zfill(4)
        elif re.fullmatch(r"GR\d{25}", acct):
            ident = "ΙΒΑΝ:" + acct
        elif len(digits) >= 8:
            ident, acct = "ΛΟΓ:" + digits, digits
        else:
            footer = round(float(amt), 2)            # γραμμή χωρίς εργαζόμενο = σύνολο
            continue
        rows.append((ident, round(float(amt), 2), acct, nm))
    if not rows:
        return []
    warn, ok = [], 0
    total = round(sum(r[1] for r in rows), 2)
    if footer is not None:
        if _cents(footer) != _cents(total):
            warn.append(f"«{name}»: εργαζόμενοι {_eur(total)} ≠ σύνολο αρχείου {_eur(footer)}")
        else:
            ok += 1
    return [{"src": "xls", "name": name, "pay_date": None, "rows": rows, "warn": warn, "ok": ok}]


def src_csv(raw: str, name: str = "") -> list[dict]:
    """
    CSV πληρωμών: IBAN;ποσό;EUR;περιγραφή (π.χ. «ΜΙΣΘΟΔΟΣΙΑ ΟΚΤΩΒΡΙΟΥ 2026»).
    Μία πηγή ΑΝΑ ΠΕΡΙΓΡΑΦΗ — αν το ίδιο αρχείο έχει μισθοδοσία ΚΑΙ δώρο, ο ίδιος
    IBAN εμφανίζεται δύο φορές και το ένα ΔΕΝ πρέπει να σβήσει το άλλο.
    """
    groups: dict[str, list] = {}
    for line in raw.splitlines():
        p = [x.strip() for x in line.split(";")]
        if len(p) >= 2 and p[0][:2].upper() == "GR" and re.fullmatch(_AMOUNT, p[1] or ""):
            desc = " ".join(norm_greek(p[3]).split()) if len(p) >= 4 else ""
            iban = p[0].upper().replace(" ", "")
            groups.setdefault(desc, []).append(("ΙΒΑΝ:" + iban, _num(p[1]), iban, ""))
    out = []
    for desc, rows in groups.items():
        ctx = _context(desc) if (desc and "?" not in desc) else {}   # χαλασμένη κωδικοποίηση → αγνοούμε
        out.append({"src": "csv", **ctx, "name": name, "label": desc, "pay_date": None,
                    "rows": rows, "warn": [], "ok": 0})
    return out


def src_mk(raw: str, name: str = "") -> list[dict]:
    """
    «Μισθοδοτική κατάσταση»: ΣΥΝΟΛΟ (από «Σύνολα Περιόδου») + κωδικός και
    «Πληρ. Ποσό» ανά εργαζόμενο (μόνο αν το άθροισμά τους = σύνολο).
    Ελέγχει τις λίστες της τράπεζας· μετράει μόνη της μόνο αν δεν υπάρχει λίστα.
    Τα ποσά ανά εργαζόμενο δίνουν κωδικό στις λίστες που έχουν ΜΟΝΟ IBAN.
    """
    t = norm_greek(raw)
    if "ΜΙΣΘΟΔΟΤΙΚΗ ΚΑΤΑΣΤΑΣΗ" not in t:
        return []
    m = re.search(r"ΣΥΝΟΛΑ ΠΕΡΙΟΔΟΥ([^:]*):\s*\d+\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)", t)
    if not m:
        return []
    ctx = _context(m.group(1))
    ctx["ref"] = ctx.get("ref") or (_ref_month(t))
    if not ctx.get("kind"):
        ctx.update(kind=KIND_PAYROLL, sub="")
    total = _num(m.group(4))
    return [{"src": "mk", **ctx, "name": name, "pay_date": None, "total": total,
             "pays": _mk_pays(t[:m.start()], total), "warn": [], "ok": 0}]


_MK_LINE = re.compile(r"\b\d{1,3} " + _AMOUNT + " " + _AMOUNT + " " + _AMOUNT + " " + _AMOUNT
                      + r"\s*[Α-ΩA-Z]")
_MK_CODE = re.compile(r"\b(\d{4,6})\s+(?:ΕΜΜΙΣΘΟΣ|ΗΜΕΡΟΜΙΣΘΙΟΣ|ΩΡΟΜΙΣΘΙΟΣ)")


def _mk_pays(t: str, total: float) -> dict:
    """
    {κωδικός: Πληρ. Ποσό}. Κάθε εργαζόμενος κλείνει με «ΣΥΝΕΡ:»· στην πρώτη του
    γραμμή «ημέρες · … · … · ΠΛΗΡ. ΠΟΣΟ · κόστος». Αν κάτι δεν βγει καθαρά
    (άθροισμα ≠ σύνολο, διπλός κωδικός) → {} (δεν μαντεύουμε).
    """
    pays = {}
    for chunk in t.split("ΣΥΝΕΡ:")[:-1]:
        line, code = _MK_LINE.search(chunk), _MK_CODE.search(chunk)
        if not (line and code):
            continue
        c = code.group(1).zfill(4)
        if c in pays:
            return {}
        pays[c] = _num(line.group(3))
    if not pays or _cents(sum(pays.values())) != _cents(total):
        return {}
    return pays


def src_receipts(raw: str, name: str = "") -> list[dict]:
    """
    «Απόδειξη πληρωμής αποδοχών» — μία σελίδα ανά πληρωμή (κωδικός · περίοδος ·
    «Υπόλοιπο πληρωτέων αποδοχών» · ημερομηνία). ΟΛΕΣ «Δώρο …/Επίδομα …» → δώρο·
    ανάμεικτες (αποχώρηση: αποδοχές + αναλογίες) → συμπληρωματική.
    """
    t = norm_greek(raw)
    if "ΑΠΟΔΕΙΞΗ ΠΛΗΡΩΜΗΣ ΑΠΟΔΟΧΩΝ" not in t:
        return []
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
        return []
    bonuses = [_bonus(p) for p in periods]
    if all(bonuses):
        ctx = {"kind": KIND_BONUS, "sub": bonuses[0]}
    elif len(emps) >= 3 and not (_SUPPL_RE.search(t) or "ΑΝΑΛΟΓΙ" in t):
        # Αποδείξεις ΟΛΟΥ του προσωπικού για έναν απλό μήνα (π.χ. «AP.pdf» 2024) =
        # η ΜΗΝΙΑΙΑ μισθοδοσία, όχι συμπληρωματική.
        ctx = {"kind": KIND_PAYROLL, "sub": ""}
    else:
        ctx = {"kind": KIND_SUPPL, "sub": ""}
    ctx["ref"] = next((r for r in (_ref_month(p) for p in periods) if r), None)
    return [{"src": "receipts", **ctx, "name": name, "pay_date": max(dates) if dates else None,
             "rows": [(c, a, "", "") for c, a in emps.items()], "warn": [], "ok": 0}]


def _is_code(ident: str) -> bool:
    return bool(re.fullmatch(r"\d{4,6}", ident or ""))


def _mk_match(srcs: list[dict], iban2code: dict) -> dict:
    """
    Λίστα τράπεζας με ΜΟΝΟ IBAN/λογαριασμό (παλιά Excel) + μισθοδοτική στο ίδιο
    email → {ταυτότητα: κωδικός} όπου το ποσό είναι ΜΟΝΑΔΙΚΟ και στις δύο.
    Ίδιο ποσό σε δύο εργαζόμενους → κανένα ταίριασμα (μένει κενό, όχι μάντεμα).
    """
    pays: dict[int, list] = {}
    for m in srcs:
        if m.get("src") == "mk":
            for code, amt in (m.get("pays") or {}).items():
                pays.setdefault(_cents(amt), []).append(code)
    if not pays:
        return {}
    rows: dict[int, set] = {}
    for s in srcs:
        for ident, amt, iban, _n in s.get("rows", []):
            if _is_code(ident) or (ident.startswith("ΙΒΑΝ:") and ident[5:] in iban2code):
                continue
            rows.setdefault(_cents(amt), set()).add(ident)
    out = {}
    for c, idents in rows.items():
        codes = pays.get(c, [])
        if len(idents) == 1 and len(codes) == 1:
            out[next(iter(idents))] = codes[0]
    return out


def combine_payroll(srcs: list[dict], subject: str, sent: date | None,
                    known: dict | None = None) -> tuple[list[dict], list[str]]:
    """
    Οι πηγές ΕΝΟΣ email → εγγραφές πληρωμής (μία ανά είδος + μήνα + δώρο), η
    καθεμία με τους εργαζόμενούς της.

      • Πηγές ΜΕ είδος (ενότητες Κατάστασης, CSV με περιγραφή) ορίζουν τις πληρωμές.
      • Πηγές ΧΩΡΙΣ είδος (Excel, CSV χωρίς περιγραφή): γραμμή που υπάρχει ήδη ίδια
        (εργαζόμενος + ποσό) = επιβεβαίωση· οι υπόλοιπες (π.χ. δεύτερη τράπεζα)
        πάνε στη μισθοδοσία του email.
      • Μισθοδοτική → έλεγχος της μισθοδοσίας· μόνη της μόνο αν δεν υπάρχει λίστα.
      • Αποδείξεις → μόνο αν δεν υπάρχει τίποτα από τα παραπάνω.
    """
    notes: list[str] = []
    if not srcs:
        return [], notes
    iban2code = dict(known or {})
    for s in srcs:
        for ident, _a, iban, _n in s.get("rows", []):
            if _is_code(ident) and iban.startswith("GR"):
                iban2code[iban] = ident

    by_amount = _mk_match(srcs, iban2code)

    def ident_of(ident: str) -> str:
        if ident in by_amount:
            return by_amount[ident]
        if ident.startswith("ΙΒΑΝ:"):
            return iban2code.get(ident[5:], ident)
        return ident

    # Αρχείο που ΔΕΝ λέει μόνο του ότι είναι δώρο/επίδομα (π.χ. κατάσταση με περίοδο
    # «Ιούλιος 2025», CSV με χαλασμένη περιγραφή) αλλά το ΟΝΟΜΑ του το λέει → δώρο.
    for s in srcs:
        nb = _name_bonus(s.get("name", ""))
        if nb and s.get("kind") in (None, KIND_PAYROLL):
            s.update(kind=KIND_BONUS, sub=nb)

    subj = _context(norm_greek(subject or ""))
    pay_all = next((s["pay_date"] for s in srcs if s.get("pay_date") and s["src"] == "statement"), None)
    when = pay_all or sent
    mk_refs = {m.get("ref") for m in srcs if m["src"] == "mk" and m.get("ref")}
    # Μήνας για όσα δεν τον γράφουν: θέμα (λέξεις) → θέμα (αριθμοί, «09/2026») →
    # η μισθοδοτική του ίδιου email → ο μήνας πληρωμής (τελευταία λύση).
    default_ref = (subj.get("ref") or _ref_numeric(subject or "")
                   or (next(iter(mk_refs)) if len(mk_refs) == 1 else None)
                   or (f"{when:%Y-%m}" if when else None))
    files = ", ".join(sorted({s["name"] for s in srcs if s.get("name")}))[:140]

    groups: dict[tuple, dict] = {}

    def group(kind, ref, sub):
        k = (kind, ref or default_ref, sub or "")
        return groups.setdefault(k, {"emps": {}, "who": {}, "warn": [], "ok": 0, "total": None,
                                     "pay": None, "labels": []})

    def add_rows(g, s, rows=None):
        for ident, amt, iban, nm in (s["rows"] if rows is None else rows):
            ident = ident_of(ident)
            have = g["emps"].get(ident)
            if have is None:
                g["emps"][ident] = amt
                g["who"][ident] = (iban, nm)
            elif _cents(have) != _cents(amt):
                g["warn"].append(f"εργαζόμενος {ident}: {_eur(have)} σε ένα αρχείο, "
                                 f"{_eur(amt)} στο «{s.get('name', '')}»")
            else:
                old_iban, old_nm = g["who"][ident]
                g["who"][ident] = (old_iban or iban, old_nm or nm)
        g["warn"] += s.get("warn", [])
        g["ok"] += s.get("ok", 0)
        g["pay"] = g["pay"] or s.get("pay_date")
        if s.get("label"):
            g["labels"].append(s["label"])

    lists = [s for s in srcs if s["src"] in ("statement", "csv", "xls")]
    with_ctx = [s for s in lists if s.get("kind")]
    no_ctx = [s for s in lists if not s.get("kind")]
    # Ενότητες Κατάστασης πρώτα (κωδικός + ημερομηνία πληρωμής), μετά CSV.
    for s in sorted(with_ctx, key=lambda x: x["src"] != "statement"):
        add_rows(group(s["kind"], s.get("ref"), s.get("sub")), s)

    for s in sorted(no_ctx, key=lambda x: x["src"] != "xls"):
        if not groups:
            add_rows(group(subj.get("kind") or KIND_PAYROLL, None, subj.get("sub")), s)
            continue
        main_k = next((k for k in groups if k[0] == KIND_PAYROLL), None) \
            or max(groups, key=lambda k: len(groups[k]["emps"]))
        rest = [row for row in s["rows"]
                if not any(_cents(g["emps"].get(ident_of(row[0]), -1)) == _cents(row[1])
                           for g in groups.values())]   # ίδιο σε άλλη λίστα = επιβεβαίωση
        # Τα IBAN/ονόματα του Excel συμπληρώνουν όσους ήδη ξέρουμε από άλλη λίστα.
        for ident, _amt, iban, nm in s["rows"]:
            for g in groups.values():
                w = g["who"].get(ident_of(ident))
                if w is not None:
                    g["who"][ident_of(ident)] = (w[0] or iban, w[1] or nm)
        add_rows(groups[main_k], s, rest)

    # Μισθοδοτική ΔΩΡΟΥ με σύνολο ΙΔΙΟ με μια «μισθοδοσία» του email (που δεν
    # αναγνωρίστηκε ως δώρο) → αυτή η μισθοδοσία ΕΙΝΑΙ το δώρο (όχι δύο πληρωμές).
    for m in [s for s in srcs if s["src"] == "mk" and s.get("kind") == KIND_BONUS]:
        k = (m["kind"], m.get("ref") or default_ref, m.get("sub") or "")
        if groups.get(k, {}).get("emps"):
            continue
        cand = [x for x in groups if x[0] == KIND_PAYROLL and groups[x]["emps"]
                and _cents(sum(groups[x]["emps"].values())) == _cents(m["total"])]
        if len(cand) == 1:
            g = groups.pop(cand[0])
            old = groups.pop(k, None)
            if old:
                g["warn"] += old["warn"]
                g["ok"] += old["ok"]
            groups[k] = g

    for m in [s for s in srcs if s["src"] == "mk"]:
        k = (m["kind"], m.get("ref") or default_ref, m.get("sub") or "")
        if lists:
            g = groups.get(k) or next((groups[x] for x in groups if x[:2] == k[:2]), None)
            if g is None:
                g = group(*k)
            if g["emps"]:
                tot = round(sum(g["emps"].values()), 2)
                if _cents(tot) != _cents(m["total"]):
                    g["warn"].append(f"μισθοδοτική {_eur(m['total'])} ≠ λίστες τράπεζας {_eur(tot)} "
                                     f"(λείπει αρχείο τράπεζας ή εργαζόμενος;)")
                else:
                    g["ok"] += 1
            elif g["total"] is None:
                g["total"] = m["total"]
        else:
            g = group(*k)
            g["total"] = m["total"]
            g["labels"].append("σύνολο μισθοδοτικής (χωρίς λίστα ανά εργαζόμενο)")

    if not groups:
        for r in [s for s in srcs if s["src"] == "receipts"]:
            g = group(r["kind"], r.get("ref"), r.get("sub"))
            for ident, amt, *_ in r["rows"]:
                g["emps"][ident] = round(g["emps"].get(ident, 0.0) + amt, 2)
                g["who"].setdefault(ident, ("", ""))
            # Απόδειξη = ΗΔΗ πληρωμένο. Η μεγαλύτερη ημερομηνία του PDF είναι συχνά το
            # τέλος της περιόδου (π.χ. 30/11) → ποτέ μετά την αποστολή του email.
            p = r.get("pay_date")
            if p and sent and p > sent:
                p = sent
            g["pay"] = g["pay"] or p
            g["labels"].append("αποδείξεις πληρωμής")

    out = []
    for (kind, ref, sub), g in groups.items():
        if not kind:
            notes.append("μισθοδοσία χωρίς είδος/μήνα — δεν καταχωρήθηκε")
            continue
        pay = g["pay"] or pay_all or sent           # δεν γράφεται στο αρχείο → ημερομηνία email
        ref = ref or (f"{pay:%Y-%m}" if pay else None)
        if not ref:
            continue
        amount = round(sum(g["emps"].values()), 2) if g["emps"] else g["total"]
        if not amount:
            continue
        unresolved = [i for i in g["emps"] if not _is_code(i)]
        warns = list(dict.fromkeys(g["warn"]))
        check = ("⚠ " + " · ".join(warns)) if warns else \
            (f"✓ {g['ok']} έλεγχοι σωστοί" if g["ok"] else "— χωρίς σύνολα για έλεγχο")
        what = f"{len(g['emps'])} εργαζόμενοι" if g["emps"] else (g["labels"][0] if g["labels"] else "")
        if unresolved:                              # όχι λάθος: αντιστοιχίζονται από IBAN/όνομα
            what += f" ({len(unresolved)} χωρίς κωδικό στο αρχείο)"
        out.append({"kind": kind, "ref": ref, "sub": sub, "amount": amount, "pay_date": pay,
                    "emps": dict(g["emps"]), "who": dict(g["who"]), "check": check[:400],
                    "detail": f"{sub + ' · ' if sub else ''}{what}",
                    "source": f"{(subject or '')[:60]} · {files}", "_doc": "payroll"})
        if warns:
            notes.append(f"{kind} {ref} {sub}: " + " · ".join(warns))
    return out, notes


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
    if "ΣΥΝΟΔΕΥΤΙΚΟ ΕΝΤΥΠΟ" in t and "ΟΙΚΟΔΟΜΟΤΕΧΝΙΚΟΥ ΕΡΓΟΥ" in t:
        # ΑΠΔ ΟΙΚΟΔΟΜΙΚΟΥ ΕΡΓΟΥ (κατασκευή καταστήματος 2023–24): γραμμή
        # «/01 2024 51 2.191,20 1.651,56» = μήνας · ημέρες · αποδοχές · ΕΙΣΦΟΡΕΣ.
        r = re.search(r"/\s*(\d{1,2})\s+(20\d\d)\s+\d+\s+" + _AMOUNT + r"\s+" + _AMOUNT, t)
        if not r:
            return []
        amt = _num(r.group(4))
        return [{"kind": KIND_EFKA, "ref": f"{int(r.group(2)):04d}-{int(r.group(1)):02d}",
                 "sub": "ΕΦΚΑ οικοδομικού έργου", "amount": amt, "pay_date": None,
                 "detail": f"Οικοδομικό έργο (ΑΠΔ) {_eur(amt)}", "_doc": "efka"}]
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
    # ΠΑΛΙΑ μορφή: «ΠΛΗΡΩΤΕΟ ΠΟΣΟ x» + «ΕΜΠΡΟΘΕΣΜΗΣ ΠΛΗΡΩΜΗΣ 10/2026 30/11/2026».
    amt = re.search(r"ΠΛΗΡΩΤΕΟ ΠΟΣΟ\s*" + _AMOUNT, t)
    per = re.search(r"ΕΜΠΡΟΘΕΣΜΗΣ ΠΛΗΡΩΜΗΣ\s*(\d{1,2})/(20\d\d)\s+" + _DATE, t)
    # ΝΕΑ μορφή (από 2026): «ΑΝΑΛΥΣΗ ΜΗΝΙΑΙΑΣ ΕΙΣΦΟΡΑΣ (10/2026) ΕΜΠΡΟΘΕΣΜΗ ΠΛΗΡΩΜΗ ΕΩΣ:
    # 30/11/2026» · ποσό = «ΣΥΝΟΛΟ:» της ενότητας «Δ. ΠΟΣΑ ΠΡΟΣ ΕΞΟΦΛΗΣΗ» (τρέχουσες +
    # καθυστερούμενες), αλλιώς «ΣΥΝΟΛΟ ΜΗΝΙΑΙΑΣ ΕΙΣΦΟΡΑΣ».
    if not per:
        per = re.search(r"ΜΗΝΙΑΙΑΣ ΕΙΣΦΟΡΑΣ\s*\(\s*(\d{1,2})/(20\d\d)\s*\)\s*ΕΜΠΡΟΘΕΣΜΗ ΠΛΗΡΩΜΗ"
                        r"\s*ΕΩΣ\s*:?\s*" + _DATE, t)
    if not amt:
        i = t.find("ΠΟΣΑ ΠΡΟΣ ΕΞΟΦΛΗΣΗ")
        amt = (re.search(r"ΣΥΝΟΛΟ\s*:\s*" + _AMOUNT, t[i:i + 600]) if i >= 0 else None) \
            or re.search(r"ΣΥΝΟΛΟ ΜΗΝΙΑΙΑΣ ΕΙΣΦΟΡΑΣ\s*:\s*" + _AMOUNT, t)
    if not (amt and per):
        return []
    ref = f"{int(per.group(2)):04d}-{int(per.group(1)):02d}"
    due = _date(per, base=3)
    # ΑΦΜ του ΕΤΑΙΡΟΥ — ΟΧΙ του ΕΦΚΑ (997072577, γράφεται πρώτος στη νέα μορφή).
    afms = [a for a in re.findall(r"ΑΦΜ\s*:\s*(\d{9})", t) if a != "997072577"]
    sub = f"…{afms[0][-4:]}" if afms else ""
    return [{"kind": KIND_PARTNERS, "ref": ref, "sub": sub, "amount": _num(amt.group(1)),
             "pay_date": due, "detail": f"Εταίρος ΑΦΜ {sub}", "_doc": "partners"}]


_AADE_ROW = re.compile(r"\b\d{1,3}\s+" + _DATE + r"\s+" + _AMOUNT + r"\s*€\s+" + _AMOUNT
                       + r"\s*€\s+" + _AMOUNT + r"\s*€")


def _aade_label(title: str) -> str:
    """Τίτλος οφειλής → σύντομο όνομα (για τις λεπτομέρειες της δόσης)."""
    if "ΜΙΣΘΩΤ" in title:
        return "ΦΜΥ"
    if "ΑΜΟΙΒ" in title:
        return "Παρακράτηση αμοιβών"
    if "ΡΥΘΜΙΣ" in title or "ΔΟΣΕ" in title:
        return "Ρύθμιση"
    for k, v in (("Φ.Π.Α", "ΦΠΑ"), ("ΦΠΑ", "ΦΠΑ"), ("ΕΝΦΙΑ", "ΕΝΦΙΑ"), ("ΕΙΣΟΔΗΜ", "Φόρος εισοδήματος"),
                 ("ΤΕΛΗ ΚΥΚΛΟΦ", "Τέλη κυκλοφορίας"), ("ΤΕΛΟΣ ΕΠΙΤΗΔ", "Τέλος επιτηδεύματος")):
        if k in title:
            return v
    return " ".join(title.split())[:40] or "Οφειλή"


def parse_aade(raw: str, name: str = "") -> list[dict]:
    """
    «Οφειλές προς το Δημόσιο» (PartyDebts): ΦΩΤΟΓΡΑΦΙΑ ΤΗΣ ΣΤΙΓΜΗΣ στην «Ημερομηνία
    Πληροφόρησης» (`snap`). Δόσεις «Α/Α λήξη υπόλοιπο προσαυξήσεις σύνολο» → μία
    εγγραφή ανά λήξη, με ανάλυση (π.χ. «ΦΜΥ 803,89 € + Παρακράτηση αμοιβών 80,00 €»).
    Η ΝΕΟΤΕΡΗ κατάσταση αντικαθιστά τις παλιότερες (βλ. sheets.merge_pagia).
    `debt` = συνολική οφειλή (εκτός/εντός ρύθμισης). Χωρίς δόσεις → μία εγγραφή-σημάδι
    με ποσό 0 (ώστε να σβηστούν οι παλιές δόσεις).
    """
    t = norm_greek(raw)
    if "ΟΦΕΙΛΕΣ ΠΡΟΣ ΤΟ ΔΗΜΟΣΙΟ" not in t and "ΑΑΔΕ" not in t:
        return []
    info = re.search(r"ΗΜΕΡΟΜΗΝΙΑ ΠΛΗΡΟΦΟΡΗΣΗΣ\s*:?\s*" + _DATE, t)
    snap = _date(info) if info else None
    debt = None
    i = t.find("ΣΥΝΟΛΙΚΟ ΠΟΣΟ ΟΦΕΙΛΗΣ ΕΝΤΟΣ ΚΙ ΕΚΤΟΣ")
    if i >= 0:
        j = t.find("ΟΦΕΙΛΕΣ ", i + 40)
        v = [_num(x) for x in re.findall(_AMOUNT + r"\s*€", t[i:j if j > i else i + 1500])]
        if len(v) >= 9 and _cents(v[3] + v[7]) == _cents(v[8]):
            debt = {"total": v[8], "out": v[3], "in": v[7]}

    by_due: dict[date, float] = {}
    parts: dict[date, dict] = {}
    title, prev = "", ""
    for ln in t.splitlines():
        s = ln.strip()
        if re.fullmatch(r"\d{9}-\d+-\d+", s):
            title = prev
        for m in _AADE_ROW.finditer(ln):
            due = _date(m)
            if due:
                amt = _num(m.group(6))
                by_due[due] = by_due.get(due, 0.0) + amt
                lab = _aade_label(title)
                parts.setdefault(due, {})[lab] = parts.get(due, {}).get(lab, 0.0) + amt
        if s:
            prev = s
    if not by_due:                         # παλιά διάταξη: γραμμές σπασμένες σε πολλές σειρές
        for m in _AADE_ROW.finditer(t):
            due = _date(m)
            if due:
                by_due[due] = by_due.get(due, 0.0) + _num(m.group(6))
    out = []
    for due, amt in sorted(by_due.items()):
        if amt <= 0:
            continue
        p = parts.get(due) or {}
        detail = (" + ".join(f"{k} {_eur(v)}" for k, v in sorted(p.items(), key=lambda x: -x[1]))
                  if p else "Οφειλές προς ΑΑΔΕ (λήξη)")
        out.append({"kind": KIND_AADE, "ref": f"{due:%Y-%m}", "sub": "", "amount": round(amt, 2),
                    "pay_date": due, "detail": detail, "_doc": "aade", "snap": snap, "debt": debt})
    if not out and snap:
        out.append({"kind": KIND_AADE, "ref": f"{snap:%Y-%m}", "sub": "", "amount": 0.0,
                    "pay_date": None, "detail": "Καμία δόση", "_doc": "aade", "snap": snap,
                    "debt": debt, "_marker": True})
    return out


def parse_accountant(raw: str, name: str = "") -> list[dict]:
    """
    ΑΜΟΙΒΗ ΛΟΓΙΣΤΗ — δύο μορφές:
      • ΝΕΑ: «Τιμολόγιο Παροχής Υπηρεσιών» (PDF) → ΠΛΗΡΩΤΕΟ ΠΟΣΟ (μετά την
        παρακράτηση, που πάει στην ΑΑΔΕ) στον μήνα του «Αφορά Περίοδο: ΙΟΥΛΙΟΥ 2025».
        Σύνολα στη σειρά: αξία · ΦΠΑ · σύνολο · παρακράτηση · πληρωτέο
        (αξία + ΦΠΑ = σύνολο, σύνολο − παρακράτηση = πληρωτέο).
      • ΠΑΛΙΑ: κείμενο email «… από 01.04.2024 έως 31.07.2024 … το Σύνολο είναι
        355,00 ευρώ» → στον μήνα του «έως».
    """
    t = norm_greek(raw)
    if "ΤΙΜΟΛΟΓΙΟ ΠΑΡΟΧΗΣ ΥΠΗΡΕΣΙΩΝ" in t and "ΛΟΓΙΣΤΙΚ" in t and "ΠΛΗΡΩΤΕΟ ΠΟΣΟ" in t:
        nums = [_num(x) for x in re.findall(_AMOUNT, t[t.index("ΠΛΗΡΩΤΕΟ ΠΟΣΟ"):])]
        pay = None
        for i in range(len(nums) - 4):
            a, v, tot, wh, net = nums[i:i + 5]
            if _cents(a + v) == _cents(tot) and _cents(tot - wh) == _cents(net) and net > 0:
                pay, parts = net, (a, v, wh)
                break
        if pay is None:
            return []
        per = re.search(r"ΑΦΟΡΑ ΠΕΡΙΟΔΟ\s*:?\s*([^\n]+)", t)
        ref = _ref_month(per.group(1)) if per else None
        inv = re.search(r"ΤΙΜΟΛΟΓΙΟ ΠΑΡΟΧΗΣ ΥΠΗΡΕΣΙΩΝ\s+(\d+)\s+" + _DATE, t)
        when = _date(inv, 2) if inv else None
        ref = ref or (f"{when:%Y-%m}" if when else None)
        if not ref:
            return []
        no = f"Τιμολόγιο {inv.group(1)} · " if inv else ""
        return [{"kind": KIND_ACCOUNTANT, "ref": ref, "sub": "", "amount": round(pay, 2),
                 "pay_date": None, "_doc": "accountant",
                 "detail": f"{no}{_eur(parts[0])} + ΦΠΑ {_eur(parts[1])} − παρακράτηση {_eur(parts[2])}"}]
    m = re.search(r"ΤΟ ΣΥΝΟΛΟ ΕΙΝΑΙ\s*" + _AMOUNT + r"\s*(?:ΕΥΡΩ|€)", t)
    if m and ("ΥΠΗΡΕΣΙΕΣ" in t or "ΑΜΟΙΒ" in t or "ΛΟΓΙΣΤΙΚ" in t):
        upto = list(re.finditer(r"ΕΩΣ\s*" + _DATE, t))
        end = _date(upto[0]) if upto else None
        if not end:
            return []
        return [{"kind": KIND_ACCOUNTANT, "ref": f"{end:%Y-%m}", "sub": "", "amount": _num(m.group(1)),
                 "pay_date": None, "_doc": "accountant", "detail": "Αμοιβή λογιστή (χρεώσεις)"}]
    return []


def parse_taxis_slip(raw: str, name: str = "") -> list[dict]:
    """
    TAXISnet «Σημείωμα για Πληρωμή» (2023–24, πριν τις καταστάσεις «Οφειλές προς το
    Δημόσιο»): ΦΜΥ, παρακράτηση εργοληπτών κ.λπ. → ΑΑΔΕ στον μήνα λήξης.
    Ταυτότητα = «Ταυτότητα Οφειλής» (η ίδια οφειλή σε δύο email = μία φορά).
    """
    t = norm_greek(raw)
    if "ΣΗΜΕΙΩΜΑ ΓΙΑ ΠΛΗΡΩΜΗ" not in t:
        return []
    inst = re.search(r"ΠΟΣΟ ΔΟΣΗΣ ΔΗΛΩΣΗΣ ΤΗΣ\s*" + _DATE + r"\s*" + _AMOUNT, t)
    tot = re.search(r"ΣΥΝΟΛΙΚΟ ΠΟΣΟ ΟΦΕΙΛΗΣ ΔΗΛΩΣΗΣ\s*" + _AMOUNT, t)
    due = _date(inst) if inst else _date(re.search(r"ΜΕΧΡΙ ΤΙΣ\s*" + _DATE, t))
    amt = _num(inst.group(4)) if inst else (_num(tot.group(1)) if tot else None)
    if not (due and amt):
        return []
    kind_m = re.search(r"ΕΙΔΟΣ ΦΟΡΟΥ\s*([^\n]+)", t)
    title = kind_m.group(1).strip() if kind_m else ""
    label = "Παρακράτηση εργοληπτών" if "ΕΡΓΟΛΗΠΤ" in title else _aade_label(title)
    per = re.search(r"ΗΜΕΡΟΛΟΓΙΑΚΗ ΠΕΡΙΟΔΟΣ\s*" + _DATE + r"\s*-\s*" + _DATE, t)
    per_s = f" {per.group(2)}/{per.group(3)}" if per else ""
    ident = re.search(r"ΤΑΥΤΟΤΗΤΑ ΟΦΕΙΛΗΣ\s*([\d ]{12,40})", t)
    sub = "№ " + re.sub(r"\s", "", ident.group(1)) if ident else f"№ {label} {due:%Y-%m-%d} {amt:.2f}"
    return [{"kind": KIND_AADE, "ref": f"{due:%Y-%m}", "sub": sub, "amount": round(amt, 2),
             "pay_date": due, "detail": f"{label}{per_s} {_eur(amt)} (σημείωμα πληρωμής)", "_doc": "aade_slip"}]


def parse_elpk(raw: str, name: str = "") -> list[dict]:
    """«Ειδικός Λογαριασμός Παιδικών Κατασκηνώσεων» (ΕΛΠΚ) — εισφορά ΕΦΚΑ μία φορά τον χρόνο."""
    t = norm_greek(raw)
    if "ΠΑΙΔΙΚΩΝ ΚΑΤΑΣΚΗΝΩΣΕΩΝ" not in t:
        return []
    ref = _ref_month(t)
    a = re.search(_AMOUNT, t)
    if not (ref and a):
        return []
    amt = _num(a.group(1))
    return [{"kind": KIND_EFKA, "ref": ref, "sub": "ΕΛΠΚ", "amount": amt, "pay_date": None,
             "detail": f"Παιδικές κατασκηνώσεις (ΕΛΠΚ) {_eur(amt)}", "_doc": "efka"}]


def _cents_all(t: str) -> list[int]:
    return [_cents(_num(x)) for x in re.findall(_AMOUNT, t)]


def parse_vat(raw: str, name: str = "") -> list[dict]:
    """
    ΔΗΛΩΣΗ ΦΠΑ (PDF της ΑΑΔΕ: «…_Φ2_2026_3ο_Αρχική.pdf», «…_ΦΠΑ_2025_4ο.pdf»,
    «…_fpa_2024_01_10_2024_31_12_2024_Αρχική_….pdf»). Το έντυπο έχει ΜΟΝΟ αριθμούς
    (χωρίς ετικέτες) και η διάταξή τους αλλάζει, άρα δουλεύουμε με ΑΡΙΘΜΗΤΙΚΗ:
      D = ΦΠΑ εκροών − ΦΠΑ εισροών της περιόδου (γράφεται μετά τον ΑΦΜ)
      C = πιστωτικό υπόλοιπο προηγούμενης περιόδου, N = πιστωτικό που μεταφέρεται
      • C − D = N  ή  C + D = N  → ΠΙΣΤΩΤΙΚΗ: τίποτα για πληρωμή (εγγραφή 0 € —
        φαίνεται στην αναφορά, δεν μετράει)
      • D − C = P  → πληρωτέο P (το πιστωτικό κάλυψε μέρος)
      • χωρίς πιστωτικό, D = εκροές − εισροές (εκροές > εισροές) → πληρωτέο D
      • αλλιώς ΤΙΠΟΤΑ (καλύτερα κενό από λάθος — ✎ διόρθωση)
    Πληρωμή: τελευταία εργάσιμη του επόμενου μήνα από τη λήξη της περιόδου.
    Τροποποιητικές: ΔΕΝ μετράνε αυτόματα (μπορεί να ξαναγράφουν το αρχικό ποσό).
    """
    import unicodedata
    up = "".join(ch for ch in unicodedata.normalize("NFD", (name or "").upper())
                 if not unicodedata.combining(ch))
    if not re.search(r"(?:^|[_ ])(?:Φ2|ΦΠΑ|FPA)_", up) or "ΤΡΟΠΟΠΟΙΗΤΙΚ" in up:
        return []
    t = raw or ""
    dates = re.findall(r"\b(\d{2})/(\d{2})/(\d{2})\b", t)
    try:
        start, period_end = (date(2000 + int(y), int(mo), int(d)) for d, mo, y in dates[:2])
    except ValueError:
        return []
    if period_end <= start:
        return []
    vals = _cents_all(t)
    if not vals:
        return []
    first = {}
    for i, v in enumerate(vals):
        first.setdefault(v, i)
    # Ποσά ΣΤΟ ΜΕΓΕΘΟΣ ΤΟΥ ΦΠΑ: ≥ 100 € και < μισό του μεγαλύτερου (εκεί είναι οι
    # αξίες πωλήσεων/αγορών — αυτές δίνουν «τυχαία» αθροίσματα).
    cap = max(vals) / 2
    vat = {v for v in first if 10000 <= v < cap}
    afm = list(re.finditer(r"(?m)^\s*\d{9}\s*$", t))
    tail = _cents_all(t[afm[-1].end():]) if afm else []
    def is_sum(v: int) -> bool:
        """Σύνολο στήλης: ίσο με το άθροισμα των 2–4 ποσών ακριβώς πριν (π.χ. ΦΠΑ εκροών)."""
        i = first[v]
        return any(i >= k and sum(vals[i - k:i]) == v for k in (2, 3, 4))

    pay = credit = None
    for d in sorted({v for v in tail if v in vat}, reverse=True):   # η διαφορά = το μεγαλύτερο
        pairs = [(c, n) for c in vat for n in vat if d not in (c, n) and first[c] < first[n]
                 and (c - d == n or c + d == n)]
        # εκροές − D = εισροές: ΚΑΙ τα δύο είναι σύνολα στηλών → ο υπολογισμός του ΦΠΑ
        calc = [(c, n) for c, n in pairs if c - d == n and is_sum(c) and is_sum(n)]
        # πιστωτικό ΠΡΙΝ (C) → πιστωτικό ΜΕΤΑ (N): ΟΧΙ σύνολα στηλών
        chain = [(c, n) for c, n in pairs if not (is_sum(c) and is_sum(n))]
        if chain:
            credit, pay = max(chain, key=lambda cn: first[cn[0]])[1], 0
            break
        if calc:                                 # χρεωστική χωρίς πιστωτικό → πληρωτέο D
            part = [p for c in vat for p in first if 0 < p < d and c not in (d,) + calc[0]
                    and not is_sum(c) and d - c == p]
            pay = part[0] if part else d         # μέρος καλύφθηκε από πιστωτικό → P
            break
    if pay is None:          # δεν βγαίνει με βεβαιότητα → τίποτα (φαίνεται στην αναφορά, ✎ διόρθωση)
        return []
    y, mo = (period_end.year + 1, 1) if period_end.month == 12 else (period_end.year, period_end.month + 1)
    due = date(y, mo, calendar.monthrange(y, mo)[1])
    while due.weekday() >= 5:                       # Σάββατο/Κυριακή → Παρασκευή
        due = date.fromordinal(due.toordinal() - 1)
    per = f"{start:%d/%m}–{period_end:%d/%m/%Y}"
    detail = (f"Δήλωση ΦΠΑ {per} · ΠΙΣΤΩΤΙΚΗ — τίποτα για πληρωμή · πιστωτικό υπόλοιπο {_eur(credit / 100)}"
              if credit is not None else f"Δήλωση ΦΠΑ {per} · ποσό για καταβολή")
    return [{"kind": KIND_VAT, "ref": f"{due:%Y-%m}", "sub": f"№ ΦΠΑ {start:%Y-%m-%d}–{period_end:%Y-%m-%d}",
             "amount": pay / 100, "pay_date": due, "_doc": "vat", "detail": detail,
             "check": "✓ εκροές − εισροές − πιστωτικό"}]


PARSERS = (parse_efka_body, parse_apd, parse_partners, parse_aade, parse_accountant, parse_vat,
           parse_taxis_slip, parse_elpk)
SOURCES = (src_statement, src_mk, src_receipts)        # PDF/κείμενο → πηγές μισθοδοσίας


# ══════════════════════════════════════════════════════════════════════════════
# ΑΣΧΕΤΑ ΣΥΝΗΜΜΕΝΑ — ο λογιστής στέλνει και πολλά που ΔΕΝ είναι πάγια (υπογραφές,
# συμβάσεις, προσωπικά φορολογικά…). Στην αναφορά: «δεν χρειάζεται», όχι «χάθηκε».
# ══════════════════════════════════════════════════════════════════════════════
_IGNORE = (
    # (λέξεις στο ΟΝΟΜΑ αρχείου, κανονικοποιημένο) → λόγος
    (("MYDATA",), "myDATA εξόδων"),
    (("ΑΠΟΔΕΙΞΕΙΣ ΜΙΣΘΟΔΟΣΙΑΣ", "ΑΠΟΔΕΙΞΕΙΣ_ΜΙΣΘΟΔΟΣΙΑΣ"), "αποδείξεις (ίδια ποσά με τις λίστες)"),
    (("ΣΥΜΒ", "SYMB", "ΤΡΟΠ", "ΑΠΟΛΥΣ", "ΑΠΟΧ", "ΛΥΣΗ", "ΛΗΞΗ", "ΟΙΚΕΙΟΘ", "ΠΡΟΓΡΑΜΜΑ",
      "ΠΡΟΣΛΗΨ", "ΕΝΤΥΠΟ_"), "σύμβαση / πρόσληψη / αποχώρηση"),
    (("QR", "ΒΕΒΑΙΩΣ", "ΒΕΒ.", "ΠΙΣΤΟΠΟΙΗΤ", "IBAN", "ΑΦΜ", "ΣΤΟΙΧΕΙΑ ΕΠΙΧΕΙΡΗΣΗΣ", "ΚΩΔΙΚΟΙ"),
     "βεβαίωση / στοιχεία"),
    (("ΕΚΚΑΘΑΡΙΣΤΙΚΟ", "_Ε1", "_Ε2", "_Ε3", "Ε3_", "ΕΝΦΙΑ", "ΠΕΡΙΟΥΣΙΑΚΗ", "Φ.Ε.Ν.Π", "ΤΕΛΗ ΚΥΚΛΟΦΟΡΙΑΣ",
      "ΔΗΛΩΣ"), "φορολογικό έγγραφο (όχι πάγιο)"),
    (("PRINTINVOICE", "ΤΙΜΟΛΟΓ", "INVOICE", "_Β_", "ANAKOINWSH", "EKTIMISI", "ΕΚΠΤΩΣΗ", "ΜΕΤΑΦΟΡΙΚΟ",
      "ΠΡΟΣΩΡΙΝ", "DOCUMENT"), "άλλο έγγραφο (όχι πάγιο)"),
)
_IMG_GENERIC = re.compile(r"^(IMAGE|ΕΙΚΟΝΑ|IMG|OUTLOOK|LOGO|SIGNATURE|ΥΠΟΓΡΑΦΗ)[\w\- ()]*\.(PNG|JPE?G|GIF|BMP)$")


def ignore_reason(filename: str) -> str | None:
    """Συνημμένο που ΔΕΝ είναι πάγιο → σύντομος λόγος· αλλιώς None (= αν δεν διαβάστηκε, χάθηκε)."""
    t = norm_greek(filename or "").strip()
    if "Φ2" in t and "ΤΡΟΠΟΠΟΙΗΤΙΚΗ" in t:
        return "τροποποιητική ΦΠΑ — αν άλλαξε το ποσό: ✎ διόρθωση"
    import unicodedata
    raw = "".join(ch for ch in unicodedata.normalize("NFD", (filename or "").upper().strip())
                  if not unicodedata.combining(ch))         # χωρίς «λατινικά → ελληνικά»
    if _IMG_GENERIC.match(raw) or raw.endswith(".GIF"):
        return "εικόνα (υπογραφή/στιγμιότυπο)"
    if raw.endswith((".ZIP", ".7Z", ".RAR")) and "ΑΠΟΔΕΙΞ" not in t:
        return "συμπιεσμένο αρχείο (δεν ανοίγεται)"
    for words, why in _IGNORE:
        if any(norm_greek(w) in t for w in words):
            return why
    return None


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
            out.extend(s)
    return out


def _describe(new_recs: list, new_srcs: list) -> str:
    """Τι βγήκε από ένα συνημμένο — για την αναφορά ανάκτησης."""
    out = []
    for s in new_srcs:
        what = {"statement": "κατάσταση", "csv": "λίστα τράπεζας", "xls": "λίστα τράπεζας",
                "mk": "μισθοδοτική", "receipts": "αποδείξεις"}.get(s["src"], s["src"])
        ctx = " ".join(x for x in (s.get("kind") or "", s.get("ref") or "", s.get("sub") or "") if x)
        if s["src"] == "mk":
            out.append(f"{what} {ctx} σύνολο {_eur(s['total'])}"
                       + (f" ({len(s.get('pays') or {})} εργαζ.)" if s.get("pays") else ""))
        else:
            rows = s.get("rows") or []
            out.append(f"{what}{' ' + ctx if ctx else ''}: {len(rows)} εργαζ. "
                       f"{_eur(round(sum(r[1] for r in rows), 2))}")
    for r in new_recs:
        out.append(f"{r['kind']} {r['ref']}{' ' + r['sub'] if r.get('sub') else ''} {_eur(r['amount'])}")
    return " · ".join(out)


def parse_message(msg, known: dict | None = None,
                  report: dict | None = None) -> tuple[list[dict], list[str]]:
    """
    → (εγγραφές, σημειώσεις) για ΕΝΑ email: κείμενο + κάθε συνημμένο.
    `report` (προαιρετικό): γεμίζει report["files"] = [«αρχείο: τι βγήκε»].

    Το κείμενο του email υπάρχει συνήθως ΔΥΟ φορές (απλό + HTML): τα διαβάζουμε
    χωριστά και τα ίδια ποσά τα ενώνει το dedupe() — ΠΟΤΕ άθροισμα.
    """
    import pandas as pd

    recs, notes, srcs = [], [], []
    body_plain = msg.text or ""
    body_html = html_to_text(msg.html or "")
    for body in (body_plain, body_html):
        recs += parse_text(body)

    files = []
    for att in getattr(msg, "attachments", []) or []:
        name = att.filename or ""
        low = name.lower()
        payload = att.payload or b""
        text = None
        n_recs, n_srcs = len(recs), len(srcs)
        if low.endswith(".pdf"):
            text = pdf_text(payload)
        elif low.endswith((".csv", ".txt")):
            text = _decode(payload)
            srcs += src_csv(text, name)
        elif low.endswith((".xls", ".xlsx")):
            try:                                    # ΟΛΑ τα φύλλα του Excel
                sheets = pd.read_excel(io.BytesIO(payload), header=None, sheet_name=None)
            except Exception as e:
                sheets = {}
                notes.append(f"Excel «{name}» δεν διαβάστηκε: {e}")
            for df in sheets.values():
                srcs += src_xls(df, name)
        elif low.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")):
            text = image_text(payload)
            if text is None:
                notes.append(f"φωτογραφία «{name}»: θέλει OCR (τη διαβάζει ο αυτόματος "
                             f"συγχρονισμός του GitHub)")
        if text:
            recs += parse_text(text, name)
            srcs += _sources(text, name)
        files.append(f"{name}: {_describe(recs[n_recs:], srcs[n_srcs:]) or 'δεν αναγνωρίστηκε'}")
    if report is not None:
        report["files"] = files

    sent = None
    try:
        sent = msg.date.date() if msg.date else None
    except Exception:
        sent = None
    pay_recs, pay_notes = combine_payroll(srcs, msg.subject or "", sent, known)
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
    if str(r.get("sub") or "").startswith("№ "):   # λογαριασμός παρόχου (core.bills): RF/αριθμός
        return (kind, str(r["sub"]))
    if kind == KIND_AADE:
        pay = r.get("pay_date")
        snap = r.get("snap")
        return (kind, pay.isoformat() if hasattr(pay, "isoformat") else str(pay),
                snap.isoformat() if hasattr(snap, "isoformat") else str(snap or ""))
    if kind in (KIND_EFKA, KIND_PARTNERS):
        return (kind, r["ref"], r.get("sub", ""))
    emps = r.get("emps")
    if emps:                                   # ίδιοι εργαζόμενοι με ίδια ποσά = ίδια πληρωμή
        return (kind, r["ref"], r.get("sub", ""), ",".join(sorted(emp_tokens(emps))))
    return (kind, r["ref"], f"{float(r['amount']):.2f}")


def emp_tokens(emps: dict) -> set:
    """{κωδικός: ποσό} → {"0018:42132", …} — ο εργαζόμενος ΜΑΖΙ με το ποσό του σε λεπτά."""
    return {f"{c}:{_cents(a)}" for c, a in emps.items()}


def dedupe(recs: list[dict]) -> list[dict]:
    """
    Ένα ανά key(). Προτιμάμε την εγγραφή με ημερομηνία πληρωμής (π.χ. PDF πάνω από CSV).

    Μισθοδοσίες με εργαζόμενους: με τη σειρά των email, για κάθε πληρωμή (είδος +
    μήνας + δώρο) κρατάμε ΜΟΝΟ ό,τι δεν έχει ήδη μετρηθεί — ΙΔΙΟΣ εργαζόμενος με
    ΙΔΙΟ ποσό = το ίδιο email ξανά (δεν μετράει)· καινούργιος εργαζόμενος ή άλλο
    ποσό (π.χ. δεύτερη πληρωμή δώρου) = προστίθεται.
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
        new = {c: a for c, a in r["emps"].items() if f"{c}:{_cents(a)}" not in done}
        if not new:
            continue
        done.update(emp_tokens(new))
        out.append({**r, "emps": new, "amount": round(sum(new.values()), 2)})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ΧΕΙΡΟΚΙΝΗΤΑ ΠΑΓΙΑ — ΦΠΑ, ενοίκιο, ρεύμα, ασφάλειες… (φύλλο «pagia_manual»)
# ══════════════════════════════════════════════════════════════════════════════
# Επανάληψη → κάθε πόσους μήνες (0 = μία φορά).
FREQS = {"Μία φορά": 0, "Κάθε μήνα": 1, "Κάθε 2 μήνες": 2, "Κάθε 3 μήνες": 3,
         "2 φορές τον χρόνο": 6, "1 φορά τον χρόνο": 12}


def expand_manual(items: list[dict], until: date) -> list[dict]:
    """
    Χειροκίνητα πάγια → μία εγγραφή ανά μήνα πληρωμής, ίδια μορφή με τα αυτόματα
    (kind = το όνομα, π.χ. «ΦΠΑ» → δική του στήλη). Από τον «πρώτο μήνα» ως τον
    «τελευταίο» (ή ως `until`). Μέρα πληρωμής: η «μέρα» (ή η τελευταία του μήνα).
    """
    import calendar
    out = []
    for it in items:
        name = str(it.get("name") or "").strip()
        try:
            amount = float(it.get("amount") or 0)
            y, m = (int(x) for x in str(it.get("start") or "").split("-")[:2])
        except (ValueError, TypeError):
            continue
        if not name or amount <= 0 or not 1 <= m <= 12:
            continue
        step = FREQS.get(str(it.get("freq") or ""), 0)
        end = str(it.get("end") or "").strip()
        try:
            ey, em = (int(x) for x in end.split("-")[:2]) if end else (until.year, until.month)
        except ValueError:
            ey, em = until.year, until.month
        last = min((ey, em), (until.year, until.month))
        try:
            day = int(it.get("day") or 0)
        except (ValueError, TypeError):
            day = 0
        note = str(it.get("note") or "").strip()
        while (y, m) <= last:
            dim = calendar.monthrange(y, m)[1]
            out.append({"kind": name, "ref": f"{y:04d}-{m:02d}", "sub": "", "amount": round(amount, 2),
                        "pay_date": date(y, m, min(day, dim) if day > 0 else dim),
                        "detail": "χειροκίνητο" + (f" · {note}" if note else ""),
                        "email_date": None, "emps": "", "source": "χειροκίνητο", "check": "",
                        "manual_id": str(it.get("id") or "")})
            if not step:
                break
            m += step
            y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return out
