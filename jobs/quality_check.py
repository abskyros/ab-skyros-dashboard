#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/quality_check.py — Ημερήσιος έλεγχος ποιότητας (10:00).

ΔΕΝ ΣΒΗΝΕΙ ΤΙΠΟΤΑ. Μόνο αναφέρει.

Ο λόγος: ένα script δεν ξέρει ποια από δύο διπλές εγγραφές είναι η σωστή.
Ο άνθρωπος ξέρει. Το script δείχνει τι βρήκε, και η διόρθωση γίνεται από την
εφαρμογή, με το κουμπί δίπλα στη σωστή γραμμή.

Secrets: GOOGLE_KEY_JSON
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import SHEET_SALES, SHEET_INV, SHEET_TIMOL
from core.sheets import check_quality, load_sales


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1

    print(f"▶ Έλεγχος ποιότητας — {datetime.now():%Y-%m-%d %H:%M}")

    problems = 0

    for sheet, label in (
        (SHEET_SALES, "Πωλήσεις"),
        (SHEET_INV, "Παραστατικά"),
        (SHEET_TIMOL, "Τιμολογήσεις"),
    ):
        print(f"\n· {label}")
        result = check_quality(sheet)

        if result.get("error"):
            print(f"  ✗ {result['error']}")
            continue

        dups = result["duplicates"]
        gaps = result["gaps"]

        # Διπλά — δείχνουμε μόνο τα πρόσφατα, τα παλιά τα ξέρουμε ήδη
        recent = _recent(dups, days=30)
        if recent:
            problems += len(recent)
            for d in recent:
                rows = ", ".join(f"γρ.{e['row']}" for e in d["entries"])
                print(f"  ⚠ Διπλό {d['date']} — {rows}")
        else:
            print("  ✓ Καμία πρόσφατη διπλοεγγραφή")

        # Κενά
        if sheet == SHEET_TIMOL:
            recent_gaps = [g for g in gaps if _is_recent(g["before"], days=60)]
            for g in recent_gaps:
                problems += 1
                print(f"  ⚠ Κενό {g['after']} → {g['before']} "
                      f"(~{g['approx_missing']} εβδομάδες)")
            if not recent_gaps:
                print("  ✓ Καμία εβδομάδα δεν λείπει")
        else:
            recent_gaps = [g for g in gaps if _is_recent(g, days=14)]
            for g in recent_gaps:
                problems += 1
                print(f"  ⚠ Λείπει η {g}")
            if not recent_gaps:
                print("  ✓ Καμία πρόσφατη μέρα δεν λείπει")

    # Ειδικός έλεγχος: ήρθε η χθεσινή αναφορά πωλήσεων;
    print("\n· Χθεσινή αναφορά")
    yesterday = date.today() - timedelta(days=1)
    df = load_sales()
    have = not df.empty and (df["date"].dt.date == yesterday).any()

    if have:
        print(f"  ✓ Η {yesterday:%d/%m} υπάρχει")
    else:
        problems += 1
        print(f"  ⚠ Η {yesterday:%d/%m} ΔΕΝ έχει έρθει")

    # ── ΣΥΝΟΨΗ ──
    print("\n" + "─" * 56)
    if problems:
        print(f"⚠ {problems} πράγματα θέλουν ματιά.")
        print("  Άνοιξε την εφαρμογή → «Έλεγχος δεδομένων» στη σχετική σελίδα.")
    else:
        print("✓ Όλα καθαρά.")

    # Πάντα 0 — ο έλεγχος δεν «αποτυγχάνει» επειδή βρήκε πρόβλημα.
    # Αν επιστρέφαμε 1, το GitHub θα έστελνε email κάθε μέρα και θα το αγνοούσες.
    return 0


def _recent(dups: list, days: int) -> list:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [d for d in dups if d["date"] >= cutoff]


def _is_recent(iso: str, days: int) -> bool:
    return iso >= (date.today() - timedelta(days=days)).isoformat()


if __name__ == "__main__":
    sys.exit(main())
