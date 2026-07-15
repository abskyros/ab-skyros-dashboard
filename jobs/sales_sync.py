#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/sales_sync.py — Πωλήσεις (OCR).
Τρέχει κάθε 10 λεπτά, από τις 15:00 ώρα Ελλάδας ώσπου να βρεθεί η αναφορά.

Η αναφορά πωλήσεων μπορεί να έρθει οποιαδήποτε ώρα μέσα σε αυτό το παράθυρο.
Το script είναι idempotent — μόλις καταχωρηθεί η μέρα, οι επόμενες εκτελέσεις
δεν κάνουν τίποτα.

ΓΙΑΤΙ ΕΔΩ ΚΑΙ ΟΧΙ ΣΤΗΝ ΕΦΑΡΜΟΓΗ: το OCR θέλει tesseract + poppler, που δεν
υπάρχουν στο Streamlit Cloud. Εδώ τα εγκαθιστούμε στο workflow.

Secrets: GOOGLE_KEY_JSON, SALES_EMAIL_PASS
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mail import fetch_sales
from core.sheets import merge_sales, load_sales
from core.parsers import ocr_available
from core.metrics import now_greece, sales_window_open

LOOKBACK_DAYS = 10
EMAIL_LIMIT = 80


def main() -> int:
    # ── Ο ΕΛΕΓΧΟΣ ΩΡΑΣ, ΠΡΩΤΟΣ ΑΠ' ΟΛΑ ──
    #
    # Το cron τρέχει ευρέως (καλύπτει χειμώνα και καλοκαίρι). Εδώ ελέγχουμε την
    # ΠΡΑΓΜΑΤΙΚΗ ώρα Ελλάδας και βγαίνουμε αμέσως αν είναι νωρίς.
    #
    # Γίνεται ΠΡΙΝ από κάθε τι άλλο: πριν το Gmail, πριν το Sheet, πριν το OCR.
    # Μια πρόωρη εκτέλεση τελειώνει σε 1 δευτερόλεπτο.
    now = now_greece()
    open_, why = sales_window_open(now)

    if not open_:
        print(f"⏸  {why}")
        return 0

    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1

    password = os.environ.get("SALES_EMAIL_PASS", "")
    if not password:
        print("✗ Λείπει το SALES_EMAIL_PASS")
        return 1

    if not ocr_available():
        print("✗ Το OCR δεν φορτώνει — λείπει tesseract ή poppler.")
        return 1

    print(f"▶ Πωλήσεις — {now:%Y-%m-%d %H:%M} ώρα Ελλάδας ({now.tzname() or 'EET/EEST'})")

    known = load_sales()

    # Οι μέρες που ΗΔΗ έχουμε. Περνιούνται στο fetch_sales ώστε να ΜΗΝ κάνει OCR
    # σε PDF που δεν έχουν τίποτα νέο.
    #
    # Το job τρέχει κάθε 10 λεπτά όλη τη νύχτα. Χωρίς αυτό, θα έκανε OCR στα ίδια
    # PDF δεκάδες φορές. Με αυτό, μόλις βρεθεί η μέρα, οι υπόλοιπες εκτελέσεις
    # τελειώνουν σε δευτερόλεπτα.
    have = set()
    if not known.empty:
        have = {
            d.date() if hasattr(d, "date") else d
            for d in known["date"]
        }

    print(f"  Ήδη καταχωρημένες: {len(have)} ημέρες")

    # ── ΠΟΙΑ ΜΕΡΑ ΨΑΧΝΟΥΜΕ; ──
    #
    # Η αναφορά αφορά ΤΗ ΜΕΡΑ ΠΟΥ ΠΕΡΑΣΕ (ή τη σημερινή, αν είναι απόγευμα).
    #
    #   Δευτέρα 23:00  → ψάχνουμε τη ΔΕΥΤΕΡΑ
    #   Τρίτη   01:00  → ψάχνουμε ακόμα τη ΔΕΥΤΕΡΑ (μεταμεσονύκτια εκτέλεση)
    #
    # Αν το μπερδέψουμε, θα λέμε «όλα εντάξει» ενώ λείπει η χθεσινή.
    target = now.date() if now.hour >= 12 else now.date() - timedelta(days=1)

    if target in have:
        print(f"  ✓ Η αναφορά της {target:%d/%m} υπάρχει ήδη. Τίποτα να κάνω.")
        return 0

    print(f"  ⟳ Ψάχνω την αναφορά της {target:%d/%m}…")

    since = target - timedelta(days=LOOKBACK_DAYS)
    records, errors, seen = fetch_sales(
        password, since=since, limit=EMAIL_LIMIT, skip_dates=have
    )

    if errors:
        print(f"✗ {errors[0]}")
        return 1

    if seen == 0:
        print("\n· Κανένα νέο email. Τίποτα να κάνω.")
        return 0

    saved = merge_sales(records)

    if saved:
        for r in records:
            print(f"  + {r['date']:%Y-%m-%d}  {r['net_sales']:,.2f} €")
        print(f"\n✓ {saved} νέες ημέρες (OCR σε {seen} PDF).")
    else:
        print(f"\n· Καμία νέα ημέρα (OCR σε {seen} PDF, όλες γνωστές).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
