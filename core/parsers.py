"""
core/parsers.py — Διαβάζει τα αρχεία που έρχονται με email.

ΓΡΑΜΜΕΝΟ ΜΙΑ ΦΟΡΑ. Το χρησιμοποιούν και η εφαρμογή και τα GitHub Actions.
Πριν, η ίδια λογική ήταν αντιγραμμένη σε 3 αρχεία με μικροδιαφορές — και οι
μικροδιαφορές γίνονταν λάθη.

  • parse_invoices()   → Excel/CSV παραστατικών
  • parse_timologisi() → Excel τιμολόγησης (βρίσκει την επιταγή)
  • parse_sales_pdf()  → PDF ημερήσιας αναφοράς, μέσω OCR

Το OCR φορτώνεται LAZY. Στο Streamlit Cloud δεν υπάρχουν poppler/tesseract και
το import τους ρίχνει την εφαρμογή.
"""

from __future__ import annotations

import io
import re
from datetime import date, timedelta

import pandas as pd

from core.sheets import parse_number


# ══════════════════════════════════════════════════════════════════════════════
# ΠΑΡΑΣΤΑΤΙΚΑ (Excel / CSV)
# ══════════════════════════════════════════════════════════════════════════════
def parse_invoices(content: bytes, filename: str) -> list[dict]:
    """
    → [{"date", "type", "value", "number"}, ...]

    Το αρχείο του WeDoConnect έχει κεφαλίδα στη γραμμή 6 — από πάνω υπάρχουν
    στοιχεία αποστολέα/παραλήπτη. Την ψάχνουμε από το περιεχόμενο, όχι από τη θέση.

    Οι στήλες:
        ΤΥΠΟΣ ΠΑΡΑΣΤΑΤΙΚΟΥ      «ΤΙΜΟΛΟΓΙΟ (ΠΩΛΗΣΗ ΑΓΑΘΩΝ)» / «ΠΙΣΤΩΤΙΚΟ ΤΙΜΟΛΟΓΙΟ»
        ΣΕΙΡΑ ΠΑΡΑΣΤΑΤΙΚΟΥ      συνήθως κενή — αλλά μέρος της ταυτότητας
        ΑΡΙΘΜΟΣ ΠΑΡΑΣΤΑΤΙΚΟΥ    π.χ. 9315755320  ← Η ΤΑΥΤΟΤΗΤΑ
        ΗΜΕΡΟΜΗΝΙΑ ΠΑΡΑΣΤΑΤΙΚΟΥ
        ΣΥΝΟΛΙΚΗ ΑΞΙΑ

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΓΙΑΤΙ Ο ΑΡΙΘΜΟΣ ΕΙΝΑΙ ΤΟ ΠΑΝ                                           │
    │                                                                        │
    │ Δύο τιμολόγια των 213,51 € την ίδια μέρα από τον ίδιο προμηθευτή είναι │
    │ ΦΥΣΙΟΛΟΓΙΚΑ. Έχουν όμως διαφορετικούς αριθμούς.                        │
    │                                                                        │
    │   ίδιος αριθμός 2 φορές   → διπλοκαταχώρηση → σβήσε                    │
    │   άλλος αριθμός           → δύο τιμολόγια   → ΜΗΝ ΤΑ ΑΓΓΙΞΕΙΣ          │
    │                                                                        │
    │ Χωρίς τον αριθμό, μια αυτόματη διαγραφή αφαιρεί πραγματικά χρήματα.    │
    └────────────────────────────────────────────────────────────────────────┘
    """
    try:
        df_raw = _read_tabular(content, filename)
        if df_raw is None:
            return []

        header = _find_header(df_raw, must_have=("ΤΥΠΟΣ", "ΗΜΕΡΟΜΗΝΙΑ"))
        if header is None:
            return []

        df = df_raw.iloc[header + 1:].copy()
        df.columns = [str(h).strip().upper() for h in df_raw.iloc[header].values]
        df = df.loc[:, df.columns.notna()]
        df = df.loc[:, ~df.columns.str.contains("NAN|UNNAMED", case=False, na=False)]
        df = df.reset_index(drop=True)

        c_date   = _col(df, "ΗΜΕΡΟΜΗΝΙΑ")
        c_type   = _col(df, "ΤΥΠΟΣ")
        c_value  = _col(df, "ΑΞΙΑ", "ΣΥΝΟΛΟ")
        c_number = _col(df, "ΑΡΙΘΜΟΣ")
        c_series = _col(df, "ΣΕΙΡΑ")

        if not (c_date and c_type and c_value):
            return []

        records = []

        for _, r in df.iterrows():
            d = pd.to_datetime(r[c_date], errors="coerce")
            if pd.isna(d):
                continue

            t = str(r[c_type]).strip()
            if not t or t.lower() == "nan":
                continue

            number = _clean_number(r[c_number]) if c_number else ""
            series = _clean_number(r[c_series]) if c_series else ""
            full = f"{series}-{number}" if series and number else number

            records.append({
                "date":   d,
                "type":   t,
                "value":  parse_number(r[c_value]),
                "number": full,
            })

        return records

    except Exception:
        return []


def _clean_number(v) -> str:
    """
    Ο αριθμός παραστατικού → καθαρό string.

    Το Excel τον δίνει ως string με κενά ('9080492340 '). Αν όμως το pandas
    μαντέψει ότι είναι αριθμός, τον δίνει ως float (9080492340.0). Και τα δύο
    πρέπει να καταλήξουν στο ίδιο: '9080492340'.

    Αλλιώς το ίδιο παραστατικό βγάζει δύο διαφορετικά κλειδιά και ξαναγράφεται
    — ακριβώς το bug που δημιούργησε τα 496 διπλά.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""

    if isinstance(v, float) and v == int(v):
        return str(int(v))

    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


# ══════════════════════════════════════════════════════════════════════════════
# ΤΙΜΟΛΟΓΗΣΗ (Excel)
# ══════════════════════════════════════════════════════════════════════════════
_CHECK_RE  = re.compile(r"ΠΛΗΡΩΜΗ\s+ΜΕ\s+ΕΠΙΤΑΓΗ\s+(\d{1,2})[./](\d{1,2})[./](\d{4})", re.IGNORECASE)
_PERIOD_RE = re.compile(r"ΠΕΡΙΟΔΟΥ?\s*([\d.]+\s*-\s*[\d.]+)")

AMOUNT_COL = 8  # «Ποσό Χρέωσης/Πίστωσης»


def parse_timologisi(content: bytes) -> dict | None:
    """
    → {"check_date", "period", "amount"} ή None

    Ψάχνει ΑΠΟ ΚΑΤΩ ΠΡΟΣ ΤΑ ΠΑΝΩ. Η γραμμή της επιταγής είναι το σύνολο και
    βρίσκεται στο τέλος — αν ψάχναμε από πάνω θα πιάναμε ενδιάμεσα αθροίσματα.
    """
    try:
        df = pd.read_excel(io.BytesIO(content), header=None)
    except Exception:
        return None

    for i in range(len(df) - 1, -1, -1):
        row = df.iloc[i]
        text = " ".join(str(x) for x in row.values if pd.notna(x))

        m = _CHECK_RE.search(text)
        if not m:
            continue

        try:
            check_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue

        amount = _extract_amount(row)
        if amount is None:
            continue

        period_m = _PERIOD_RE.search(text)

        return {
            "check_date": check_date,
            "period": period_m.group(1).strip() if period_m else "",
            "amount": round(abs(amount), 2),
        }

    return None


def _extract_amount(row: pd.Series) -> float | None:
    """Το ποσό είναι στη στήλη 8. Αν λείπει, παίρνουμε την πρώτη δεκαδική τιμή."""
    vals = list(row.values)

    if len(vals) > AMOUNT_COL:
        v = vals[AMOUNT_COL]
        if isinstance(v, (int, float)) and pd.notna(v) and v != 0:
            return float(v)
        parsed = parse_number(v)
        if parsed:
            return parsed

    # Fallback: πρώτος δεκαδικός (οι ακέραιοι είναι κωδικοί, όχι ποσά)
    for v in vals:
        if isinstance(v, float) and pd.notna(v) and v != int(v):
            return float(v)

    return None


# ══════════════════════════════════════════════════════════════════════════════
# ΠΩΛΗΣΕΙΣ (PDF + OCR)
# ══════════════════════════════════════════════════════════════════════════════
_OCR = None


def ocr_available() -> bool:
    return _load_ocr() != (None, None)


def _load_ocr():
    """
    Lazy import. Στο Streamlit Cloud λείπουν poppler/tesseract — αν κάνουμε
    import στην κορυφή, η εφαρμογή πεθαίνει με segmentation fault.
    Το OCR τρέχει κανονικά μόνο στο GitHub Actions.
    """
    global _OCR
    if _OCR is not None:
        return _OCR

    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        _OCR = (convert_from_bytes, pytesseract)
    except Exception:
        _OCR = (None, None)

    return _OCR


# Το OCR μπερδεύει O↔0, I↔1, S↔5 — γι' αυτό τα μοτίβα είναι «χαλαρά».
_RE_RUN_ON = re.compile(r"Run\s+[Oo0]n\s*[:\s]+(\d{1,2})[/.](\d{1,2})[/.](\d{4})", re.IGNORECASE)
_RE_FOR    = re.compile(r"\bFor\s+(\d{1,2})[/.](\d{1,2})[/.](\d{4})", re.IGNORECASE)
_RE_NET    = re.compile(r"Net[Dd]ay[Ss]al[Dd][i1][s5]\s+([\d.,]+)", re.IGNORECASE)
_RE_NET_2  = re.compile(r"Ne[t7][Dd]ay\S+\s+([\d.,]+)", re.IGNORECASE)
_RE_CUST   = re.compile(r"Num[O0]fCus\s+([\d.,]+)", re.IGNORECASE)
_RE_BASKET = re.compile(r"Avg[Ss]al[Cc]us\s+([\d.,]+)", re.IGNORECASE)

# Λογικά όρια — μια μέρα δεν κάνει 3 ευρώ ούτε 900.000.
LIMITS = {
    "net_sales":  (500, 500_000),
    "customers":  (10, 5_000),
    "avg_basket": (1, 1_000),
}


def parse_sales_pdf(content: bytes, dpi: int = 300) -> dict:
    """
    → {"date", "net_sales", "customers", "avg_basket"} — τιμές None αν δεν βρέθηκαν.

    Η αναφορά τυπώνεται σε landscape. Γυρνάμε τη σελίδα 90° πριν το OCR.
    """
    empty = {"date": None, "net_sales": None, "customers": None, "avg_basket": None}

    convert, tess = _load_ocr()
    if convert is None:
        return empty

    try:
        images = convert(content, dpi=dpi, first_page=1, last_page=1)
        if not images:
            return empty

        text = tess.image_to_string(
            images[0].rotate(90, expand=True),
            lang="ell+eng",
            config="--psm 6 --oem 3",
        )
    except Exception:
        return empty

    r = dict(empty)
    r["date"]       = _ocr_date(text)
    r["net_sales"]  = _ocr_num(text, _RE_NET, "net_sales") or _ocr_num(text, _RE_NET_2, "net_sales")
    r["customers"]  = _ocr_int(text, _RE_CUST, "customers")
    r["avg_basket"] = _ocr_num(text, _RE_BASKET, "avg_basket")

    # Αν λείπει το καλάθι αλλά έχουμε τα άλλα δύο, το βγάζουμε μόνοι μας.
    if r["net_sales"] and r["customers"] and not r["avg_basket"]:
        basket = r["net_sales"] / r["customers"]
        lo, hi = LIMITS["avg_basket"]
        if lo < basket < hi:
            r["avg_basket"] = round(basket, 2)

    return r


def _ocr_date(text: str) -> date | None:
    """
    «Run On» = πότε τυπώθηκε η αναφορά → αυτή είναι η μέρα των πωλήσεων.
    «For»    = για ποια μέρα ισχύει → τυπώνεται την ΕΠΟΜΕΝΗ, άρα −1 μέρα.
    """
    m = _RE_RUN_ON.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    m = _RE_FOR.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) - timedelta(days=1)
        except ValueError:
            pass

    return None


def _ocr_num(text: str, pattern: re.Pattern, kind: str) -> float | None:
    m = pattern.search(text)
    if not m:
        return None

    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        v = float(raw)
    except ValueError:
        return None

    lo, hi = LIMITS[kind]
    return round(v, 2) if lo < v < hi else None


def _ocr_int(text: str, pattern: re.Pattern, kind: str) -> int | None:
    m = pattern.search(text)
    if not m:
        return None

    try:
        v = int(re.sub(r"[.,]", "", m.group(1).split()[0]))
    except ValueError:
        return None

    lo, hi = LIMITS[kind]
    return v if lo < v < hi else None


# ══════════════════════════════════════════════════════════════════════════════
# ΒΟΗΘΗΤΙΚΑ
# ══════════════════════════════════════════════════════════════════════════════
def _read_tabular(content: bytes, filename: str) -> pd.DataFrame | None:
    """Excel ή CSV — και τα ελληνικά CSV έρχονται συχνά σε cp1253."""
    if filename.lower().endswith((".xlsx", ".xls")):
        try:
            return pd.read_excel(io.BytesIO(content), header=None)
        except Exception:
            return None

    for enc in (None, "cp1253", "utf-8-sig"):
        try:
            return pd.read_csv(
                io.BytesIO(content), header=None, sep=None,
                engine="python", encoding=enc,
            )
        except Exception:
            continue

    return None


def _find_header(df: pd.DataFrame, must_have: tuple[str, ...], scan: int = 40) -> int | None:
    """Βρίσκει τη γραμμή που περιέχει όλα τα ζητούμενα κείμενα."""
    for i in range(min(scan, len(df))):
        row = " ".join(str(x).upper() for x in df.iloc[i].values if pd.notna(x))
        if all(k in row for k in must_have):
            return i
    return None


def _col(df: pd.DataFrame, *keywords: str) -> str | None:
    """Πρώτη στήλη που περιέχει κάποια από τις λέξεις-κλειδιά."""
    for c in df.columns:
        if any(k in str(c) for k in keywords):
            return c
    return None
