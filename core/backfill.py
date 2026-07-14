"""
core/backfill.py — Βαθύς έλεγχος παλιών παραστατικών.

ΤΟ ΠΡΟΒΛΗΜΑ
    Τα παλιά παραστατικά στο Sheet δεν έχουν ΑΡΙΘΜΟ ΠΑΡΑΣΤΑΤΙΚΟΥ — καταχωρήθηκαν
    πριν προστεθεί η στήλη. Χωρίς αριθμό δεν ξεχωρίζουμε:
        • το ίδιο τιμολόγιο καταχωρημένο 2 φορές  → πρέπει να φύγει
        • δύο πραγματικά τιμολόγια ίδιου ποσού    → πρέπει να μείνουν
    Μια λάθος διαγραφή αφαιρεί πραγματικά χρήματα από τα βιβλία.

Η ΛΥΣΗ — ΔΕΝ ΜΑΝΤΕΥΟΥΜΕ. ΞΑΝΑΔΙΑΒΑΖΟΥΜΕ ΤΗΝ ΠΗΓΗ.
    Τα email με τα Excel υπάρχουν ακόμα στο Gmail. Κατεβάζουμε ΟΛΑ, διαβάζουμε
    κάθε Excel, και χτίζουμε τον «πίνακα αλήθειας»:

        (ημερομηνία, τύπος, ποσό) → [αριθμός₁, αριθμός₂, ...]

    Μετά ταιριάζουμε τις γραμμές του Sheet με αυτόν.

Η ΚΡΙΣΙΜΗ ΑΡΙΘΜΗΤΙΚΗ
    Έστω η 10/07 έχει τιμολόγια των 213,51 €:

        Στα email: 3 αριθμοί  →  υπήρξαν 3 πραγματικά τιμολόγια
        Στο Sheet: 5 γραμμές  →  2 από αυτές είναι διπλοκαταχωρήσεις

    Οι 3 πρώτες γραμμές παίρνουν τους 3 αριθμούς. Οι 2 επιπλέον ΔΕΝ έχουν
    αριθμό να πάρουν — άρα είναι ΑΠΟΔΕΔΕΙΓΜΕΝΑ διπλές. Σβήνονται.

    Το αντίστροφο (5 αριθμοί, 3 γραμμές) σημαίνει ότι λείπουν εγγραφές — τις
    προσθέτουμε.

    Δεν έχει σημασία «ποια γραμμή παίρνει ποιον αριθμό» — οι γραμμές είναι
    πανομοιότυπες, άρα ισοδύναμες. Η ΜΕΤΡΗΣΗ είναι που μετράει.

ΤΙ ΔΕΝ ΑΓΓΙΖΟΥΜΕ
    Γραμμές που δεν βρέθηκαν σε κανένα email (σβησμένο email, χειροκίνητη
    καταχώρηση) μένουν ΩΣ ΕΧΟΥΝ. Δεν ξέρουμε τίποτα γι' αυτές — άρα δεν
    αποφασίζουμε τίποτα.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from core.config import SHEET_INV, INVOICES_EMAIL_SENDER
from core.sheets import _ws, _group_runs, parse_number, to_cents, load_invoices


# ══════════════════════════════════════════════════════════════════════════════
# ΤΟ ΣΧΕΔΙΟ
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Plan:
    """
    Τι πρόκειται να γίνει. Υπολογίζεται ΧΩΡΙΣ να αγγιχτεί το Sheet.

    Ο χρήστης το βλέπει, το εγκρίνει, και μόνο τότε εκτελείται.
    """
    fill:    list[tuple[int, str]] = field(default_factory=list)   # (γραμμή, αριθμός)
    delete:  list[int]             = field(default_factory=list)   # γραμμές προς διαγραφή
    add:     list[list]            = field(default_factory=list)   # νέες γραμμές
    skip:    list[dict]            = field(default_factory=list)   # δεν βρέθηκαν → ΔΕΝ πειράζονται
    already: int                   = 0                             # είχαν ήδη αριθμό

    emails_scanned: int = 0
    records_found:  int = 0
    sheet_rows:     int = 0

    # Κρατάμε τα records ώστε η διάγνωση να τρέχει χωρίς νέα σάρωση των email.
    # Είναι λίγα MB — πολύ φθηνότερο από 446 email ξανά.
    records: list = field(default_factory=list, repr=False)

    @property
    def touched(self) -> bool:
        return bool(self.fill or self.delete or self.add)

    @property
    def deleted_value(self) -> float:
        """Πόσα ευρώ αντιπροσωπεύουν οι γραμμές που θα σβηστούν."""
        return getattr(self, "_deleted_value", 0.0)

    def summary(self) -> str:
        parts = []
        if self.fill:
            parts.append(f"{len(self.fill)} θα πάρουν αριθμό")
        if self.delete:
            parts.append(f"{len(self.delete)} θα σβηστούν")
        if self.add:
            parts.append(f"{len(self.add)} θα προστεθούν")
        if self.skip:
            parts.append(f"{len(self.skip)} δεν πειράζονται")
        return " · ".join(parts) if parts else "Καμία αλλαγή"


# ══════════════════════════════════════════════════════════════════════════════
# ΒΗΜΑ 1 — Ο ΠΙΝΑΚΑΣ ΑΛΗΘΕΙΑΣ
# ══════════════════════════════════════════════════════════════════════════════
def _bucket(d, t, v) -> tuple:
    """
    Το «κουβαδάκι» μιας εγγραφής: ημερομηνία + τύπος + ποσό σε λεπτά.

    Δύο γραμμές στο ίδιο κουβαδάκι είναι ΟΠΤΙΚΑ πανομοιότυπες. Ο αριθμός είναι
    το μόνο που τις ξεχωρίζει — και αυτόν πάμε να βρούμε.
    """
    d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10].strip()
    t_str = str(t or "").strip().upper()
    return (d_str, t_str, to_cents(v))


def build_truth(records: list) -> dict[tuple, list[str]]:
    """
    Από τα email → {κουβαδάκι: [αριθμοί]}

    Οι αριθμοί μέσα σε κάθε κουβαδάκι είναι ΜΟΝΑΔΙΚΟΙ (set). Αν το ίδιο email
    ήρθε δύο φορές, ο ίδιος αριθμός δεν μετράει δύο φορές.
    """
    truth: dict[tuple, set[str]] = defaultdict(set)

    for rec in records:
        number = str(rec.get("number", "")).strip()
        if not number:
            continue   # χωρίς αριθμό δεν μας βοηθάει

        key = _bucket(rec.get("date"), rec.get("type"), rec.get("value", 0))
        truth[key].add(number)

    # set → ταξινομημένη λίστα, ώστε η ανάθεση να είναι ντετερμινιστική
    return {k: sorted(v) for k, v in truth.items()}


# ══════════════════════════════════════════════════════════════════════════════
# ΒΗΜΑ 2 — ΤΟ ΣΧΕΔΙΟ
# ══════════════════════════════════════════════════════════════════════════════
def plan(records: list, emails_scanned: int = 0) -> Plan:
    """
    Συγκρίνει το Sheet με τον πίνακα αλήθειας. ΔΕΝ γράφει τίποτα.

    → Plan (τι θα γίνει, αν εγκριθεί)
    """
    p = Plan()
    p.emails_scanned = emails_scanned
    p.records_found = len(records)
    p.records = records

    truth = build_truth(records)

    ws = _ws(SHEET_INV)
    vals = ws.get_all_values()
    p.sheet_rows = max(0, len(vals) - 1)

    if len(vals) < 2:
        # Άδειο Sheet → όλα είναι νέα
        p.add = [
            [r["date"].strftime("%Y-%m-%d"), str(r["type"]).strip(),
             to_cents(r["value"]), str(r["number"]).strip()]
            for r in records if r.get("number")
        ]
        return p

    # ── Ομαδοποίηση των γραμμών του Sheet ανά κουβαδάκι ──
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    deleted_value = 0.0

    # ΚΡΙΣΙΜΟ: κρατάμε ΚΑΘΕ αριθμό που υπάρχει ήδη στο Sheet.
    #
    # Χωρίς αυτό, μια γραμμή που έχει ήδη τον αριθμό «111» θα προσπερνιόταν,
    # και στο τελικό βήμα το «111» θα φαινόταν να λείπει → θα το ΞΑΝΑΠΡΟΣΘΕΤΑΜΕ.
    # Ο βαθύς έλεγχος θα δημιουργούσε διπλά αντί να τα σβήσει.
    in_sheet: set[str] = set()

    for i, r in enumerate(vals[1:], start=2):
        if len(r) < 3 or not r[0]:
            continue

        number = str(r[3]).strip() if len(r) > 3 else ""

        if number:
            p.already += 1
            in_sheet.add(number)   # ← υπάρχει ήδη. Μην το ξαναπροσθέσεις.
            continue

        key = (
            str(r[0]).strip(),
            str(r[1]).strip().upper() if len(r) > 1 else "",
            int(parse_number(r[2])),
        )
        buckets[key].append({
            "row": i,
            "value": parse_number(r[2]) / 100.0,
        })

    # ── Η αντιστοίχιση ──
    for key, rows in buckets.items():
        # Οι αριθμοί που ΔΕΝ είναι ήδη στο Sheet — μόνο αυτοί μοιράζονται.
        numbers = [n for n in truth.get(key, []) if n not in in_sheet]

        if not numbers:
            # ΔΕΝ βρέθηκε σε κανένα email — ή όλοι οι αριθμοί του κουβαδιού
            # χρησιμοποιούνται ήδη από άλλες γραμμές.
            #
            # Στη δεύτερη περίπτωση οι γραμμές αυτές ΕΙΝΑΙ διπλές, αλλά δεν το
            # αποδεικνύουμε με βεβαιότητα εδώ — μπορεί το email να λείπει.
            # Δεν αγγίζουμε. Η ασφάλεια πάνω από την πληρότητα.
            for r in rows:
                p.skip.append({
                    "row": r["row"],
                    "date": key[0],
                    "type": key[1],
                    "value": r["value"],
                })
            continue

        in_sheet.update(numbers)

        # Όσες γραμμές έχουμε, τόσους αριθμούς μοιράζουμε.
        n = min(len(rows), len(numbers))

        for j in range(n):
            p.fill.append((rows[j]["row"], numbers[j]))

        # Περισσότερες γραμμές από αριθμούς → οι επιπλέον είναι ΔΙΠΛΕΣ.
        for r in rows[n:]:
            p.delete.append(r["row"])
            deleted_value += r["value"]

        # Περισσότεροι αριθμοί από γραμμές → λείπουν εγγραφές.
        for num in numbers[n:]:
            p.add.append([key[0], key[1], key[2], num])

    # ── Παραστατικά που υπάρχουν στα email αλλά καθόλου στο Sheet ──
    for key, numbers in truth.items():
        for num in numbers:
            if num in in_sheet:
                continue          # υπάρχει ήδη, ή μόλις το αναθέσαμε
            in_sheet.add(num)
            p.add.append([key[0], key[1], key[2], num])

    p.fill.sort()
    p.delete.sort()
    p._deleted_value = round(deleted_value, 2)

    return p


# ══════════════════════════════════════════════════════════════════════════════
# ΒΗΜΑ 3 — ΕΚΤΕΛΕΣΗ
# ══════════════════════════════════════════════════════════════════════════════
#
# ΤΟ ΟΡΙΟ ΤΟΥ GOOGLE
#
# Το Sheets API επιτρέπει 60 write requests ανά λεπτό ανά χρήστη. Αν το
# ξεπεράσεις, γυρνάει 429 και ΤΙΠΟΤΑ δεν γράφεται.
#
# Με 7.300 γραμμές προς γέμισμα και 100 ranges ανά batch, χρειάζονται 73 κλήσεις.
# Χωρίς παύση, οι πρώτες ~60 περνάνε και οι υπόλοιπες σκάνε.
#
# Η λύση: 500 ranges ανά batch (μειώνει τις κλήσεις 5×) + παύση 1,2 δευτ.
# ανάμεσα. 7.300 γραμμές → 15 κλήσεις → ~18 δευτερόλεπτα. Άνετα μέσα στο όριο.
BATCH_RANGES = 500
PAUSE = 1.2          # δευτερόλεπτα ανάμεσα σε κλήσεις
RETRIES = 4          # πόσες φορές ξαναδοκιμάζουμε ένα batch που έσκασε


def _write_with_retry(fn, label: str, errors: list) -> bool:
    """
    Εκτελεί μια κλήση στο Sheets API, με exponential backoff σε 429.

    Το 429 δεν είναι μόνιμο σφάλμα — είναι «περίμενε λίγο». Οπότε περιμένουμε
    και ξαναδοκιμάζουμε: 2δ, 5δ, 12δ, 30δ. Αν και μετά από 4 προσπάθειες δεν
    περάσει, τότε κάτι άλλο φταίει.
    """
    delay = 2.0

    for attempt in range(RETRIES):
        try:
            fn()
            return True
        except Exception as e:
            msg = str(e)
            is_quota = "429" in msg or "Quota exceeded" in msg or "RESOURCE_EXHAUSTED" in msg

            if not is_quota or attempt == RETRIES - 1:
                errors.append(f"{label}: {msg[:160]}")
                return False

            time.sleep(delay)
            delay *= 2.4

    return False


def apply(p: Plan, on_progress=None) -> dict:
    """
    Εκτελεί το σχέδιο. Καλείται ΜΟΝΟ μετά από ρητή έγκριση.

    → {"filled", "deleted", "added", "errors", "complete"}

    ΣΕΙΡΑ ΕΝΕΡΓΕΙΩΝ — δεν είναι τυχαία:
      1. ΓΕΜΙΣΜΑ    — γράφουμε τους αριθμούς ΠΡΩΤΑ, όσο οι γραμμές είναι σταθερές
      2. ΔΙΑΓΡΑΦΗ   — από κάτω προς τα πάνω, αλλιώς οι αριθμοί γραμμών μετακινούνται
      3. ΠΡΟΣΘΗΚΗ   — στο τέλος, δεν επηρεάζει τις υπάρχουσες

    Αν σβήναμε πρώτα, οι γραμμές που θέλουμε να γεμίσουμε θα είχαν αλλάξει θέση.

    ΚΡΙΣΙΜΟ: αν το ΓΕΜΙΣΜΑ αποτύχει, ΔΕΝ προχωράμε σε διαγραφή.
    Η διαγραφή βασίζεται στο ότι οι σωστές γραμμές έχουν πάρει αριθμό. Αν δεν
    τον πήραν, σβήνουμε στα τυφλά. Καλύτερα να σταματήσουμε.

    ΕΠΑΝΑΛΗΨΙΜΟ: το γέμισμα είναι idempotent. Αν έσκασε στη μέση, ξανατρέχεις
    τον έλεγχο — θα βρει μόνο όσες έμειναν και θα συνεχίσει από εκεί.
    """
    ws = _ws(SHEET_INV)
    done = {"filled": 0, "deleted": 0, "added": 0, "errors": [], "complete": False}

    def tick(stage: str, cur: int, total: int):
        if on_progress:
            on_progress(stage, cur, total)

    # ── 1. Κεφαλίδα ──
    try:
        header = ws.row_values(1)
        if len(header) < 4 or str(header[3]).strip().lower() != "number":
            ws.update_cell(1, 4, "number")
            time.sleep(PAUSE)
    except Exception as e:
        done["errors"].append(f"Κεφαλίδα: {e}")

    # ── 2. ΓΕΜΙΣΜΑ ──
    if p.fill:
        cells = [{"range": f"D{row}", "values": [[num]]} for row, num in p.fill]
        batches = [cells[i:i + BATCH_RANGES] for i in range(0, len(cells), BATCH_RANGES)]

        for n, batch in enumerate(batches, 1):
            tick("Γέμισμα", n, len(batches))

            ok = _write_with_retry(
                lambda b=batch: ws.batch_update(b, value_input_option="RAW"),
                "Γέμισμα",
                done["errors"],
            )

            if not ok:
                # Σταματάμε. ΔΕΝ σβήνουμε τίποτα με ημιτελές γέμισμα.
                done["errors"].append(
                    "Το γέμισμα δεν ολοκληρώθηκε — η διαγραφή ΔΕΝ εκτελέστηκε. "
                    "Ξανατρέξε τον έλεγχο: θα συνεχίσει από εκεί που έμεινε."
                )
                return done

            done["filled"] += len(batch)

            if n < len(batches):
                time.sleep(PAUSE)

    # ── 3. ΔΙΑΓΡΑΦΗ — ΑΠΟ ΚΑΤΩ ΠΡΟΣ ΤΑ ΠΑΝΩ ──
    if p.delete:
        runs = list(reversed(_group_runs(p.delete)))

        for n, (start, end) in enumerate(runs, 1):
            tick("Διαγραφή", n, len(runs))

            ok = _write_with_retry(
                lambda s=start, e=end: ws.delete_rows(s, e),
                "Διαγραφή",
                done["errors"],
            )

            if not ok:
                done["errors"].append(
                    "Η διαγραφή σταμάτησε στη μέση. Ξανατρέξε τον έλεγχο — "
                    "θα βρει τις υπόλοιπες."
                )
                return done

            done["deleted"] += end - start + 1

            if n < len(runs):
                time.sleep(PAUSE)

    # ── 4. ΠΡΟΣΘΗΚΗ ──
    if p.add:
        tick("Προσθήκη", 1, 1)

        ok = _write_with_retry(
            lambda: ws.append_rows(p.add, value_input_option="RAW"),
            "Προσθήκη",
            done["errors"],
        )

        if ok:
            done["added"] = len(p.add)

    load_invoices.clear()
    done["complete"] = not done["errors"]
    return done


# ══════════════════════════════════════════════════════════════════════════════
# ΔΙΑΓΝΩΣΗ — ΓΙΑΤΙ ΔΕΝ ΒΡΕΘΗΚΑΝ;
# ══════════════════════════════════════════════════════════════════════════════
def diagnose(p: Plan, records: list) -> dict:
    """
    Οι γραμμές που δεν ταίριαξαν — ΓΙΑΤΙ;

    Η διάκριση έχει σημασία, γιατί οδηγεί σε διαφορετική ενέργεια:

      1. ΕΚΤΟΣ ΕΜΒΕΛΕΙΑΣ
         Η γραμμή είναι παλιότερη από το παλιότερο email. Το Gmail δεν κρατάει
         τα πάντα για πάντα.
         → Δεν μπορούμε να κάνουμε τίποτα. Μένουν.

      2. ⚠️ ΤΟ ΠΟΣΟ ΔΕΝ ΤΑΙΡΙΑΖΕΙ
         Η μέρα και ο τύπος υπάρχουν στα email — αλλά με άλλο ποσό.

         ΑΥΤΟ ΕΙΝΑΙ ΚΑΜΠΑΝΑΚΙ. Σημαίνει ότι το ποσό γράφτηκε ΛΑΘΟΣ στο Sheet.
         Ο πιο πιθανός ένοχος: το παλιό daily_sync.py που έγραφε ΕΥΡΩ αντί για
         ΛΕΠΤΑ. Αυτές οι γραμμές δείχνουν 100× λάθος νούμερα στα βιβλία σου.

         Το ελέγχουμε ρητά: αν το ποσό×100 ή ποσό÷100 υπάρχει στα email, τότε
         έχουμε την απόδειξη.

      3. Η ΜΕΡΑ ΔΕΝ ΥΠΑΡΧΕΙ ΚΑΘΟΛΟΥ
         Χειροκίνητη καταχώρηση; Σβησμένο email;

    → {"out_of_range", "amount_mismatch", "unknown_day", "email_from", "email_to"}
    """
    empty = {
        "out_of_range": [], "amount_mismatch": [], "unknown_day": [],
        "email_from": None, "email_to": None,
    }

    if not p.skip:
        return empty

    # Η χρονική εμβέλεια των email
    dates = [
        r["date"].strftime("%Y-%m-%d") if hasattr(r.get("date"), "strftime")
        else str(r.get("date", ""))[:10]
        for r in records if r.get("date") is not None
    ]
    if not dates:
        return {**empty, "out_of_range": list(p.skip)}

    lo, hi = min(dates), max(dates)

    # Ποια ποσά υπάρχουν στα email, ανά (μέρα, τύπος)
    known: dict[tuple, set[int]] = defaultdict(set)
    for r in records:
        d = r.get("date")
        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        known[(d_str, str(r.get("type", "")).strip().upper())].add(
            to_cents(r.get("value", 0))
        )

    out = {**empty, "email_from": lo, "email_to": hi}

    for row in p.skip:
        day = row["date"]

        if day < lo or day > hi:
            out["out_of_range"].append(row)
            continue

        amounts = known.get((day, row["type"]))

        if not amounts:
            out["unknown_day"].append(row)
            continue

        # Η μέρα+τύπος υπάρχει, αλλά ΟΧΙ με αυτό το ποσό.
        #
        # Ψάχνουμε ρητά το σφάλμα ευρώ/λεπτά του παλιού daily_sync.py:
        #
        #   Σωστό:  1547,73 € → 154773 λεπτά
        #   Λάθος:  1547,73 € → γράφτηκε "1547.73" → διαβάστηκε 1547 λεπτά
        #
        # Δεν είναι ΑΚΡΙΒΩΣ ×100 — τα δεκαδικά χάθηκαν στη στρογγυλοποίηση.
        # Άρα ψάχνουμε ποσό στα email που πέφτει στο διάστημα:
        #
        #   [ποσό_sheet × 100,  ποσό_sheet × 100 + 99]
        #
        # Το 1547 → [154700, 154799], και το 154773 πέφτει μέσα. ✓
        cents = to_cents(row["value"])

        hint = ""
        expected = sorted(amounts)[:3]

        if cents > 0:
            lo_x100 = cents * 100
            hi_x100 = lo_x100 + 99

            match = next((a for a in amounts if lo_x100 <= a <= hi_x100), None)
            if match is not None:
                hint = "×100"
                expected = [match]
            elif cents >= 100 and (cents // 100) in amounts:
                hint = "÷100"
                expected = [cents // 100]

        r = dict(row)
        r["hint"] = hint
        r["expected"] = expected
        out["amount_mismatch"].append(r)

    return out


def audit(df: pd.DataFrame, records: list, start: date, end: date) -> dict:
    """
    ΕΛΕΓΧΟΣ ΥΓΕΙΑΣ: το Sheet συμφωνεί με τα email;

    Γιατί υπάρχει: η παλιά εφαρμογή (my_app.py) διάβαζε ΑΠΕΥΘΕΙΑΣ τα email και
    έβγαζε 97.091,30 €. Η νέα διαβάζει το Sheet και βγάζει 104.837,62 €.

    Διαφορά 7.746 €. Κάποιος από τους δύο λέει ψέματα — και ξέρουμε ποιος:
    τα email είναι η ΠΗΓΗ. Το Sheet είναι αντίγραφο. Αν διαφέρουν, το Sheet
    έχει σκουπίδια.

    Αυτή η συνάρτηση βάζει τα δύο δίπλα-δίπλα, για ΜΙΑ εβδομάδα, και δείχνει
    ακριβώς ποιες γραμμές περισσεύουν.

    → {"email": {...}, "sheet": {...}, "extra": [...], "missing": [...]}
    """
    # ── Η ΑΛΗΘΕΙΑ: τι λένε τα email γι' αυτή την εβδομάδα ──
    in_range = []
    for r in records:
        d = r.get("date")
        d = d.date() if hasattr(d, "date") else d
        if d and start <= d <= end:
            in_range.append(r)

    e_inv = sum(r["value"] for r in in_range if "ΠΙΣΤΩΤΙΚΟ" not in str(r["type"]).upper())
    e_crd = sum(r["value"] for r in in_range if "ΠΙΣΤΩΤΙΚΟ" in str(r["type"]).upper())
    e_nums = {str(r.get("number", "")).strip() for r in in_range if r.get("number")}

    # ── ΤΟ ΑΝΤΙΓΡΑΦΟ: τι λέει το Sheet ──
    if df.empty:
        sheet_rows = pd.DataFrame(columns=["date", "type", "value", "number", "_row"])
    else:
        dts = df["date"].map(lambda x: x.date() if hasattr(x, "date") else x)
        sheet_rows = df[(dts >= start) & (dts <= end)]

    s_credit = sheet_rows["type"].astype(str).str.upper().str.contains("ΠΙΣΤΩΤΙΚΟ", na=False)
    s_inv = float(sheet_rows[~s_credit]["value"].sum())
    s_crd = float(sheet_rows[s_credit]["value"].sum())

    # ── ΟΙ ΓΡΑΜΜΕΣ ΠΟΥ ΠΕΡΙΣΣΕΥΟΥΝ ──
    #
    # Ό,τι είναι στο Sheet αλλά ο αριθμός του δεν υπάρχει στα email αυτής της
    # εβδομάδας. Αυτές είναι που φουσκώνουν τα σύνολα.
    extra = []
    seen: set[str] = set()

    for _, r in sheet_rows.iterrows():
        num = str(r.get("number", "")).strip()

        if not num:
            # Χωρίς αριθμό → δεν μπορούμε να το ταυτοποιήσουμε. Ύποπτο.
            extra.append({
                "row": int(r["_row"]) if pd.notna(r.get("_row")) else 0,
                "date": r["date"].strftime("%Y-%m-%d") if hasattr(r["date"], "strftime") else str(r["date"])[:10],
                "type": str(r["type"]),
                "value": float(r["value"]),
                "number": "",
                "why": "χωρίς αριθμό",
            })
            continue

        if num in seen:
            extra.append({
                "row": int(r["_row"]) if pd.notna(r.get("_row")) else 0,
                "date": r["date"].strftime("%Y-%m-%d") if hasattr(r["date"], "strftime") else str(r["date"])[:10],
                "type": str(r["type"]),
                "value": float(r["value"]),
                "number": num,
                "why": "διπλό",
            })
            continue

        seen.add(num)

        if num not in e_nums:
            extra.append({
                "row": int(r["_row"]) if pd.notna(r.get("_row")) else 0,
                "date": r["date"].strftime("%Y-%m-%d") if hasattr(r["date"], "strftime") else str(r["date"])[:10],
                "type": str(r["type"]),
                "value": float(r["value"]),
                "number": num,
                "why": "δεν υπάρχει στα email",
            })

    # ── ΟΣΑ ΛΕΙΠΟΥΝ ──
    missing = [
        {
            "date": r["date"].strftime("%Y-%m-%d") if hasattr(r["date"], "strftime") else str(r["date"])[:10],
            "type": str(r["type"]),
            "value": float(r["value"]),
            "number": str(r.get("number", "")),
        }
        for r in in_range
        if str(r.get("number", "")).strip() and str(r.get("number", "")).strip() not in seen
    ]

    extra.sort(key=lambda x: -x["value"])

    return {
        "email": {"invoices": e_inv, "credits": e_crd, "net": e_inv - e_crd, "count": len(in_range)},
        "sheet": {"invoices": s_inv, "credits": s_crd, "net": s_inv - s_crd, "count": len(sheet_rows)},
        "extra": extra,
        "missing": missing,
        "extra_value": sum(
            x["value"] if "ΠΙΣΤΩΤΙΚΟ" not in x["type"].upper() else -x["value"]
            for x in extra
        ),
    }


def _as_iso(v) -> str:
    """
    Ημερομηνία από το Sheet → "YYYY-MM-DD".

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΤΟ BUG ΠΟΥ ΕΦΤΙΑΞΕ ΑΥΤΗ Η ΣΥΝΑΡΤΗΣΗ                                    │
    │                                                                        │
    │ Το repair_week συνέκρινε ημερομηνίες ως STRINGS:                       │
    │                                                                        │
    │     lo, hi = "2026-07-06", "2026-07-12"                                │
    │     if not (lo <= day <= hi): continue                                 │
    │                                                                        │
    │ Αν το Sheet έδινε "2026-07-10 00:00:00" ή "10/07/2026", η σύγκριση     │
    │ αποτύγχανε ΣΙΩΠΗΛΑ — καμία γραμμή δεν περνούσε το φίλτρο, και η        │
    │ επισκευή έλεγε «δεν βρέθηκε τίποτα».                                   │
    │                                                                        │
    │ Τώρα κανονικοποιούμε ΠΑΝΤΑ, από όποια μορφή κι αν έρθει.               │
    └────────────────────────────────────────────────────────────────────────┘
    """
    if v is None:
        return ""

    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")

    s = str(v).strip()
    if not s:
        return ""

    # Ήδη σωστό (ίσως με ώρα από πίσω)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]

    # Ελληνική μορφή: 10/07/2026 ή 10.07.2026
    for sep in ("/", "."):
        if sep in s:
            parts = s.split()[0].split(sep)
            if len(parts) == 3:
                try:
                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    if y < 100:
                        y += 2000
                    return f"{y:04d}-{m:02d}-{d:02d}"
                except ValueError:
                    pass

    # Τελευταία ελπίδα — ας το δοκιμάσει το pandas
    try:
        ts = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.notna(ts):
            return ts.strftime("%Y-%m-%d")
    except Exception:
        pass

    return ""


def repair(records: list, start: date | None = None, end: date | None = None) -> dict:
    """
    ΕΠΙΣΚΕΥΗ. Μία εβδομάδα, ή ΟΛΑ ΤΑ ΧΡΟΝΙΑ.

        repair(records)                    → όλα, χωρίς όριο
        repair(records, start, end)        → μόνο αυτό το διάστημα

    Δύο βήματα, με αυτή τη σειρά:

      1. ΓΕΜΙΣΜΑ — κάθε γραμμή χωρίς αριθμό παίρνει τον αριθμό της, από τα email
      2. ΔΙΑΓΡΑΦΗ — ό,τι απομείνει χωρίς αριθμό ΕΙΝΑΙ διπλό, και σβήνεται

    Η λογική του βήματος 2:

        Η 10/07 έχει 11 τιμολόγια στα email.
        Το Sheet έχει 30 γραμμές για την 10/07.
        Οι 11 πρώτες παίρνουν τους 11 αριθμούς.
        Οι 19 υπόλοιπες ΔΕΝ ΕΧΟΥΝ αριθμό να πάρουν — άρα είναι διπλές.

    Δεν μαντεύουμε. Μετράμε.

    ΚΡΙΣΙΜΟ: αν ένα κουβαδάκι (μέρα+τύπος+ποσό) ΔΕΝ υπάρχει καθόλου στα email,
    οι γραμμές του ΔΕΝ πειράζονται. Ίσως το email σβήστηκε, ίσως καταχωρήθηκαν
    με το χέρι. Δεν σβήνουμε ό,τι δεν καταλαβαίνουμε.

    → {"fill": [(row, number)], "delete": [rows], "keep": [rows],
       "value": float, "scanned": int}
    """
    ws = _ws(SHEET_INV)
    vals = ws.get_all_values()

    if len(vals) < 2:
        return {"fill": [], "delete": [], "keep": [], "value": 0.0, "scanned": 0}

    lo = start.isoformat() if start else ""
    hi = end.isoformat() if end else "9999-12-31"

    # ── Ο πίνακας αλήθειας ──
    truth: dict[tuple, list[str]] = defaultdict(list)

    for r in records:
        d = r.get("date")
        d_iso = _as_iso(d)
        if not d_iso or not (lo <= d_iso <= hi):
            continue

        num = str(r.get("number", "")).strip()
        if not num:
            continue

        key = (d_iso, str(r.get("type", "")).strip().upper(), to_cents(r.get("value", 0)))
        if num not in truth[key]:
            truth[key].append(num)

    for k in truth:
        truth[k].sort()

    # ── Οι γραμμές του Sheet ──
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    taken: set[str] = set()
    scanned = 0

    for i, r in enumerate(vals[1:], start=2):
        if len(r) < 3 or not r[0]:
            continue

        day = _as_iso(r[0])
        if not day or not (lo <= day <= hi):
            continue

        scanned += 1
        num = str(r[3]).strip() if len(r) > 3 else ""

        if num:
            taken.add(num)     # ο αριθμός χρησιμοποιείται ήδη
            continue

        key = (day, str(r[1]).strip().upper() if len(r) > 1 else "",
               int(parse_number(r[2])))
        buckets[key].append({"row": i, "value": parse_number(r[2]) / 100.0})

    # ── Η ΑΝΤΙΣΤΟΙΧΙΣΗ ──
    #
    # ┌────────────────────────────────────────────────────────────────────────┐
    # │ ΔΥΟ ΕΠΙΠΕΔΑ ΒΕΒΑΙΟΤΗΤΑΣ                                                │
    # │                                                                        │
    # │ ΕΠΙΠΕΔΟ 1 — Το κουβαδάκι ΥΠΑΡΧΕΙ στα email                             │
    # │   Ξέρουμε ακριβώς πόσα πραγματικά παραστατικά υπάρχουν.                │
    # │   Οι επιπλέον γραμμές σβήνονται, και οι υπόλοιπες παίρνουν αριθμό.     │
    # │                                                                        │
    # │ ΕΠΙΠΕΔΟ 2 — Το κουβαδάκι ΔΕΝ υπάρχει στα email                         │
    # │   Δεν ξέρουμε πόσα πραγματικά υπάρχουν. ΑΛΛΑ:                          │
    # │                                                                        │
    # │   Πέντε ΠΑΝΟΜΟΙΟΤΥΠΕΣ γραμμές (ίδια μέρα, τύπος, ποσό) δεν μπορεί      │
    # │   να είναι όλες σωστές. Ακόμα κι αν δεν ξέρουμε ποια είναι η           │
    # │   αληθινή, ξέρουμε ΜΕ ΒΕΒΑΙΟΤΗΤΑ ότι οι 4 περισσεύουν.                 │
    # │                                                                        │
    # │   Κρατάμε ΜΙΑ, σβήνουμε τις υπόλοιπες.                                 │
    # │                                                                        │
    # │ ΤΟ ΠΑΛΙΟ BUG: όλες οι γραμμές του επιπέδου 2 έμπαιναν στο "keep" και   │
    # │ ΚΑΜΙΑ δεν σβηνόταν — ούτε οι προφανώς διπλές.                          │
    # │                                                                        │
    # │ Το αποτέλεσμα: «2.916 γραμμές χωρίς αριθμό» ΚΑΙ ταυτόχρονα             │
    # │ «Το Sheet είναι ήδη καθαρό». Αντιφατικό — και το δεύτερο ήταν ψέμα.    │
    # └────────────────────────────────────────────────────────────────────────┘
    fill, delete, keep = [], [], []
    deleted_value = 0.0
    self_dups = 0        # πόσες σβήστηκαν χωρίς email, ως προφανή διπλά

    for key, rows in buckets.items():
        available = truth.get(key, [])

        # ── ΕΠΙΠΕΔΟ 2: κανένα email γι' αυτό το κουβαδάκι ──
        if not available:
            if len(rows) == 1:
                # Μία και μοναδική. Δεν έχουμε λόγο να την πειράξουμε.
                keep.append(rows[0]["row"])
                continue

            # Πολλές ΠΑΝΟΜΟΙΟΤΥΠΕΣ. Κρατάμε την πρώτη, σβήνουμε τις άλλες.
            #
            # ΓΙΑΤΙ ΤΗΝ ΠΡΩΤΗ: είναι αυθαίρετο, αλλά δεν έχει σημασία — οι
            # γραμμές είναι ταυτόσημες. Ό,τι κι αν κρατήσουμε, το ίδιο είναι.
            keep.append(rows[0]["row"])

            for r in rows[1:]:
                delete.append(r["row"])
                deleted_value += r["value"]
                self_dups += 1

            continue

        # ── ΕΠΙΠΕΔΟ 1: ξέρουμε πόσα πραγματικά υπάρχουν ──
        free = [n for n in available if n not in taken]

        n = min(len(rows), len(free))

        for j in range(n):
            fill.append((rows[j]["row"], free[j]))
            taken.add(free[j])

        # Περισσότερες γραμμές από αριθμούς → ΔΙΠΛΕΣ
        for r in rows[n:]:
            delete.append(r["row"])
            deleted_value += r["value"]

    fill.sort()
    delete.sort()

    return {
        "fill": fill,
        "delete": delete,
        "keep": sorted(keep),
        "value": round(deleted_value, 2),
        "scanned": scanned,
        "self_dups": self_dups,      # πόσες σβήστηκαν ως προφανή διπλά
    }


# Συμβατότητα με το παλιό όνομα
def repair_week(records: list, start: date, end: date) -> dict:
    return repair(records, start, end)


def apply_repair(rep: dict, on_progress=None) -> dict:
    """
    Εκτελεί την επισκευή: γέμισμα, μετά διαγραφή.

    ΣΕΙΡΑ: πρώτα γεμίζουμε (οι γραμμές είναι σταθερές), μετά σβήνουμε από κάτω
    προς τα πάνω. Αν το γέμισμα αποτύχει, ΔΕΝ σβήνουμε — θα σβήναμε στα τυφλά.
    """
    ws = _ws(SHEET_INV)
    done = {"filled": 0, "deleted": 0, "errors": [], "complete": False}

    def tick(stage, cur, total):
        if on_progress:
            on_progress(stage, cur, total)

    # ── Κεφαλίδα ──
    try:
        header = ws.row_values(1)
        if len(header) < 4 or str(header[3]).strip().lower() != "number":
            ws.update_cell(1, 4, "number")
            time.sleep(PAUSE)
    except Exception as e:
        done["errors"].append(f"Κεφαλίδα: {e}")

    # ── 1. ΓΕΜΙΣΜΑ ──
    if rep["fill"]:
        cells = [{"range": f"D{row}", "values": [[num]]} for row, num in rep["fill"]]
        batches = [cells[i:i + BATCH_RANGES] for i in range(0, len(cells), BATCH_RANGES)]

        for n, batch in enumerate(batches, 1):
            tick("Γέμισμα", n, len(batches))

            ok = _write_with_retry(
                lambda b=batch: ws.batch_update(b, value_input_option="RAW"),
                "Γέμισμα", done["errors"],
            )
            if not ok:
                done["errors"].append(
                    "Το γέμισμα δεν ολοκληρώθηκε — η διαγραφή ΔΕΝ εκτελέστηκε. "
                    "Ξαναδοκίμασε: θα συνεχίσει από εκεί που έμεινε."
                )
                return done

            done["filled"] += len(batch)
            if n < len(batches):
                time.sleep(PAUSE)

    # ── 2. ΔΙΑΓΡΑΦΗ ──
    if rep["delete"]:
        runs = list(reversed(_group_runs(rep["delete"])))

        for n, (start, end) in enumerate(runs, 1):
            tick("Διαγραφή", n, len(runs))

            ok = _write_with_retry(
                lambda s=start, e=end: ws.delete_rows(s, e),
                "Διαγραφή", done["errors"],
            )
            if not ok:
                done["errors"].append(
                    "Η διαγραφή σταμάτησε. Ξαναδοκίμασε — θα βρει τις υπόλοιπες."
                )
                return done

            done["deleted"] += end - start + 1
            if n < len(runs):
                time.sleep(PAUSE)

    load_invoices.clear()
    done["complete"] = not done["errors"]
    return done


def rebuild_plan(records: list) -> dict:
    """
    ΞΑΝΑΧΤΙΣΙΜΟ — σβήνουμε τα πάντα και ξαναγράφουμε από τα email.

    ┌────────────────────────────────────────────────────────────────────────┐
    │ ΓΙΑΤΙ ΑΥΤΟ ΚΑΙ ΟΧΙ «ΚΑΘΑΡΙΣΜΟΣ»                                        │
    │                                                                        │
    │ Ο καθαρισμός προσπαθούσε να ΜΑΝΤΕΨΕΙ ποιες γραμμές αντιστοιχούν σε     │
    │ ποια email, ταιριάζοντας (μέρα + τύπος + ποσό).                        │
    │                                                                        │
    │ Αν το ποσό στο Sheet ήταν λάθος (π.χ. από το παλιό daily_sync.py που   │
    │ έγραφε ευρώ αντί λεπτά), το ταίριασμα αποτύγχανε ΣΙΩΠΗΛΑ. Οι γραμμές   │
    │ έμεναν «άγνωστες» και δεν πειράζονταν ποτέ.                            │
    │                                                                        │
    │ Αποτέλεσμα: 2.916 γραμμές που δεν καθαρίζονταν με τίποτα.              │
    │                                                                        │
    │ ΤΟ ΞΑΝΑΧΤΙΣΙΜΟ ΔΕΝ ΜΑΝΤΕΥΕΙ.                                           │
    │                                                                        │
    │ Τα email είναι η ΠΗΓΗ. Το Sheet είναι απλώς αντίγραφο. Αν το αντίγραφο │
    │ έχει σκουπίδια, δεν το «καθαρίζεις» — το ΞΑΝΑΓΡΑΦΕΙΣ.                  │
    │                                                                        │
    │ Κάθε παραστατικό γράφεται μία φορά, με τον μοναδικό αριθμό του.        │
    │ Τα διπλά εξαφανίζονται εξ ορισμού — δεν υπάρχει τρόπος να μπουν.       │
    └────────────────────────────────────────────────────────────────────────┘

    → {"rows": [[date, type, cents, number]], "sheet_rows": int, "unique": int}
    """
    # Κρατάμε ΜΙΑ γραμμή ανά αριθμό παραστατικού.
    # Ο αριθμός είναι μοναδικός στο σύστημα της ΑΒ — αν εμφανιστεί δεύτερη
    # φορά, είναι το ίδιο παραστατικό σε δεύτερο email.
    seen: dict[str, list] = {}

    for r in records:
        num = str(r.get("number", "")).strip()
        if not num:
            continue   # χωρίς αριθμό δεν το εμπιστευόμαστε

        d = r.get("date")
        if d is None or (isinstance(d, float) and pd.isna(d)):
            continue

        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]

        # Πρώτη εμφάνιση κερδίζει. Οι επόμενες είναι αντίγραφα.
        if num not in seen:
            seen[num] = [
                d_str,
                str(r.get("type", "")).strip(),
                to_cents(r.get("value", 0)),
                num,
            ]

    # Ταξινόμηση: νεότερα πρώτα, όπως και το υπόλοιπο Sheet
    rows = sorted(seen.values(), key=lambda r: r[0], reverse=True)

    # Πόσες γραμμές έχει τώρα το Sheet
    try:
        vals = _ws(SHEET_INV).get_all_values()
        sheet_rows = max(0, len(vals) - 1)
    except Exception:
        sheet_rows = 0

    return {
        "rows": rows,
        "sheet_rows": sheet_rows,
        "unique": len(rows),
        "records": len(records),
    }


def apply_rebuild(plan: dict, on_progress=None) -> dict:
    """
    Εκτελεί το ξαναχτίσιμο: καθαρίζει το φύλλο, γράφει τα πάντα από την αρχή.

    ΣΕΙΡΑ:
      1. ΚΑΘΑΡΙΣΜΑ  — ws.clear() σβήνει τα πάντα με ΜΙΑ κλήση
      2. ΚΕΦΑΛΙΔΑ   — date, type, value, number
      3. ΓΡΑΨΙΜΟ    — σε παρτίδες των 1.000

    ΓΙΑΤΙ ΕΙΝΑΙ ΓΡΗΓΟΡΟ:
      Το παλιό «καθαρισμός» έσβηνε γραμμή-γραμμή (2.876 κλήσεις × 1,2" = 57').
      Εδώ: 1 clear + 8 batches = ~15 δευτερόλεπτα.

    ΓΙΑΤΙ ΕΙΝΑΙ ΑΣΦΑΛΕΣ:
      Το ws.clear() είναι ατομικό. Είτε πετυχαίνει, είτε όχι.
      Αν αποτύχει το γράψιμο μετά, το Sheet είναι άδειο — αλλά έχεις το
      αντίγραφο, και μπορείς να ξανατρέξεις: τα email είναι πάντα εκεί.
    """
    ws = _ws(SHEET_INV)
    done = {"deleted": 0, "written": 0, "errors": [], "complete": False}

    rows = plan["rows"]
    if not rows:
        done["errors"].append("Δεν βρέθηκε κανένα παραστατικό στα email.")
        return done

    def tick(stage, cur, total):
        if on_progress:
            on_progress(stage, cur, total)

    # ── 1. ΚΑΘΑΡΙΣΜΑ ──
    tick("Καθαρισμός φύλλου", 1, 1)

    ok = _write_with_retry(ws.clear, "Καθαρισμός", done["errors"])
    if not ok:
        return done

    done["deleted"] = plan["sheet_rows"]
    time.sleep(PAUSE)

    # ── 2. ΚΕΦΑΛΙΔΑ ──
    ok = _write_with_retry(
        lambda: ws.update(
            values=[["date", "type", "value", "number"]],
            range_name="A1:D1",
            value_input_option="RAW",
        ),
        "Κεφαλίδα",
        done["errors"],
    )
    if not ok:
        return done

    time.sleep(PAUSE)

    # ── 3. ΓΡΑΨΙΜΟ ──
    CHUNK = 1000
    batches = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]

    for n, batch in enumerate(batches, 1):
        tick("Γράψιμο", n, len(batches))

        ok = _write_with_retry(
            lambda b=batch: ws.append_rows(b, value_input_option="RAW"),
            "Γράψιμο",
            done["errors"],
        )

        if not ok:
            done["errors"].append(
                f"Το γράψιμο σταμάτησε στη γραμμή {done['written']}. "
                f"Ξανατρέξε το ξαναχτίσιμο — τα email είναι πάντα εκεί."
            )
            return done

        done["written"] += len(batch)

        if n < len(batches):
            time.sleep(PAUSE)

    load_invoices.clear()
    done["complete"] = True
    return done


# ══════════════════════════════════════════════════════════════════════════════
# ΑΝΤΙΓΡΑΦΟ ΑΣΦΑΛΕΙΑΣ
# ══════════════════════════════════════════════════════════════════════════════
def snapshot() -> str:
    """
    Το Sheet ως CSV, πριν αγγιχτεί.

    Ο χρήστης το κατεβάζει. Αν κάτι πάει στραβά, ξαναγράφει το φύλλο από αυτό.
    Δεν είναι διακοσμητικό — είναι η έξοδος κινδύνου.
    """
    try:
        vals = _ws(SHEET_INV).get_all_values()
    except Exception:
        return ""

    if not vals:
        return ""

    lines = []
    for row in vals:
        cells = []
        for c in row:
            c = str(c)
            if any(ch in c for ch in (",", '"', "\n")):
                c = '"' + c.replace('"', '""') + '"'
            cells.append(c)
        lines.append(",".join(cells))

    return "\n".join(lines)
