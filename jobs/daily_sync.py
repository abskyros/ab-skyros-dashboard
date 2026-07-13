#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/daily_sync.py — Πρωινός συγχρονισμός ασφαλείας (08:00).

Τι κάνει: τρέχει ΚΑΙ τις τρεις ροές μαζί, μια φορά τη μέρα.
Γιατί υπάρχει: δίχτυ ασφαλείας. Αν χθες βράδυ έπεσε το GitHub Actions ή το
Gmail δεν απάντησε, το πρωί το πιάνουμε.

┌────────────────────────────────────────────────────────────────────────────┐
│ ΔΙΟΡΘΩΜΕΝΟ BUG                                                             │
│                                                                            │
│ Η παλιά έκδοση αυτού του script έγραφε τα ποσά σε ΕΥΡΩ:                    │
│     round(float(rec["net_sales"]), 2)   →  1547.73                        │
│                                                                            │
│ Ενώ τα data_sync.py / sales_sync.py γράφουν σε ΛΕΠΤΑ:                      │
│     round(rec["net_sales"] * 100)       →  154773                         │
│                                                                            │
│ Η εφαρμογή διαβάζει πάντα /100. Άρα ό,τι έγραφε αυτό το script φαινόταν    │
│ 100 φορές μικρότερο: 1547,73 € → 15,48 €.                                 │
│                                                                            │
│ Τώρα καλεί το core/sheets.py, που κάνει τη μετατροπή μία φορά, σωστά.      │
└────────────────────────────────────────────────────────────────────────────┘

Secrets: GOOGLE_KEY_JSON, EMAIL_PASS, SALES_EMAIL_PASS
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mail import fetch_invoices, fetch_timologiseis, fetch_sales
from core.sheets import merge_invoices, merge_timologiseis, merge_sales
from core.parsers import ocr_available

SALES_LOOKBACK = 7


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1

    inv_pw = os.environ.get("EMAIL_PASS", "")
    sales_pw = os.environ.get("SALES_EMAIL_PASS", "") or inv_pw

    print(f"▶ Πρωινός συγχρονισμός — {datetime.now():%Y-%m-%d %H:%M}")

    # ── ΠΑΡΑΣΤΑΤΙΚΑ ──
    print("\n· Παραστατικά")
    if inv_pw:
        records, errors = fetch_invoices(inv_pw, limit=40)
        if errors:
            print(f"  ✗ {errors[0]}")
        else:
            n = merge_invoices(records)
            print(f"  ✓ {n} νέα" if n else "  · Κανένα νέο")
    else:
        print("  ! Λείπει το EMAIL_PASS — παράλειψη")

    # ── ΤΙΜΟΛΟΓΗΣΕΙΣ ──
    print("\n· Τιμολογήσεις")
    if inv_pw:
        records, errors = fetch_timologiseis(inv_pw, limit=100)
        if errors:
            print(f"  ! {errors[0]}")
        else:
            n = merge_timologiseis(records)
            print(f"  ✓ {n} νέες" if n else "  · Καμία νέα")
    else:
        print("  ! Λείπει το EMAIL_PASS — παράλειψη")

    # ── ΠΩΛΗΣΕΙΣ ──
    print("\n· Πωλήσεις")
    if not sales_pw:
        print("  ! Λείπει το SALES_EMAIL_PASS — παράλειψη")
    elif not ocr_available():
        print("  ! Το OCR δεν φορτώνει — παράλειψη")
    else:
        since = date.today() - timedelta(days=SALES_LOOKBACK)
        records, errors, seen = fetch_sales(sales_pw, since=since, limit=50)
        if errors:
            print(f"  ✗ {errors[0]}")
        else:
            n = merge_sales(records)
            print(f"  ✓ {n} νέες ημέρες (από {seen} email)" if n
                  else f"  · Καμία νέα ({seen} email)")

    print("\n✓ Ολοκληρώθηκε.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
