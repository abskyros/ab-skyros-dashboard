#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/data_sync.py — Παραστατικά & Τιμολογήσεις.
Τρέχει κάθε 2 ώρες μέσω GitHub Actions.

Idempotent: προσθέτει μόνο ό,τι λείπει. Μπορεί να τρέξει 100 φορές χωρίς κίνδυνο.

Secrets: GOOGLE_KEY_JSON, EMAIL_PASS
"""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mail import fetch_invoices, fetch_timologiseis
from core.sheets import (
    merge_invoices, merge_timologiseis,
    purge_duplicate_invoices, purge_duplicate_timologiseis,
)

INVOICE_LIMIT = 60
TIMOL_LIMIT = 200


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1

    # Παραστατικά → abf.skyros@gmail.com  (EMAIL_PASS)
    password = os.environ.get("EMAIL_PASS", "")
    if not password:
        print("✗ Λείπει το EMAIL_PASS")
        return 1

    # Τιμολογήσεις → ftoulisgm@gmail.com  (SALES_EMAIL_PASS)
    # Άλλαξε το mailbox παραλαβής, άρα χρειάζεται ο κωδικός ΕΚΕΙΝΟΥ του
    # λογαριασμού. Fallback στο EMAIL_PASS ώστε να μη σπάσει αν λείπει.
    timol_pw = os.environ.get("SALES_EMAIL_PASS", "") or password

    print(f"▶ Παραστατικά & Τιμολογήσεις — {datetime.now():%Y-%m-%d %H:%M}")

    failed = False

    # ── ΠΑΡΑΣΤΑΤΙΚΑ ──
    print("\n· Παραστατικά")
    records, errors = fetch_invoices(password, limit=INVOICE_LIMIT)

    if errors:
        print(f"  ✗ {errors[0]}")
        failed = True
    else:
        saved = merge_invoices(records)
        print(f"  ✓ {saved} νέα (από {len(records)} εγγραφές)" if saved
              else f"  · Κανένα νέο ({len(records)} εγγραφές, όλες γνωστές)")

    # ── ΤΙΜΟΛΟΓΗΣΕΙΣ ──
    print("\n· Τιμολογήσεις")
    records, errors = fetch_timologiseis(timol_pw, limit=TIMOL_LIMIT)

    if errors:
        # Το «κανένα email δεν ταιριάζει» δεν είναι σφάλμα — απλώς δεν ήρθε τίποτα.
        print(f"  ! {errors[0]}")
    else:
        saved = merge_timologiseis(records)
        print(f"  ✓ {saved} νέες (από {len(records)} που βρέθηκαν)" if saved
              else f"  · Καμία νέα ({len(records)} βρέθηκαν, όλες γνωστές)")

    # ── ΑΥΤΟΜΑΤΟΣ ΚΑΘΑΡΙΣΜΑΣ ──
    # Σβήνει ΜΟΝΟ όσα έχουν τον ΙΔΙΟ ΑΡΙΘΜΟ ΠΑΡΑΣΤΑΤΙΚΟΥ. Τα δύο πραγματικά
    # τιμολόγια ίδιου ποσού (διαφορετικός αριθμός) μένουν άθικτα.
    print("\n· Καθαρισμός")

    killed, kept, skipped = purge_duplicate_invoices()
    if killed:
        print(f"  ✓ Παραστατικά: σβήστηκαν {killed} διπλοκαταχωρήσεις, έμειναν {kept}")
    else:
        print(f"  · Παραστατικά: καθαρά ({kept} μοναδικά)")
    if skipped:
        print(f"    ({skipped} παλιά χωρίς αριθμό — δεν πειράχτηκαν)")

    killed, kept = purge_duplicate_timologiseis()
    print(f"  ✓ Τιμολογήσεις: σβήστηκαν {killed}, έμειναν {kept}" if killed
          else f"  · Τιμολογήσεις: καθαρές ({kept} εγγραφές)")

    print("\n✓ Ολοκληρώθηκε.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
