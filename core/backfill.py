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
