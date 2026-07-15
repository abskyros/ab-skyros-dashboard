#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/sales_precheck.py — Αξίζει να τρέξουμε;

ΓΙΑΤΙ ΥΠΑΡΧΕΙ

Το job τρέχει κάθε 10 λεπτά, όλη τη νύχτα. Οι περισσότερες εκτελέσεις δεν έχουν
τίποτα να κάνουν:

  • Είναι πολύ νωρίς (πριν τις 15:00 ώρα Ελλάδας)
  • Η αναφορά έχει ήδη βρεθεί και καταχωρηθεί

Το OCR όμως χρειάζεται `apt-get install tesseract poppler` — **40 δευτερόλεπτα**
σε κάθε εκτέλεση. Σε 50 εκτελέσεις τη νύχτα, αυτό είναι **33 λεπτά** runner time
τζάμπα, κάθε βράδυ.

Αυτό το script ελέγχει σε **2 δευτερόλεπτα** αν αξίζει, ΧΩΡΙΣ να εγκαταστήσει
τίποτα. Το workflow το ρωτάει πρώτα, και μόνο αν πει «ναι» στήνει το OCR.

ΤΙ ΔΕΝ ΚΑΝΕΙ

Δεν ανοίγει Gmail. Δεν κάνει OCR. Διαβάζει μόνο το Sheet (μία κλήση) και το
ρολόι.

ΕΞΟΔΟΣ

  0 → ναι, τρέξε
  1 → όχι, τίποτα να κάνω

Το workflow το διαβάζει ως `if: steps.check.outputs.work == 'yes'`.

Secrets: GOOGLE_KEY_JSON
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.metrics import now_greece, sales_window_open
from core.sheets import load_sales


def main() -> int:
    now = now_greece()
    tz = now.tzname() or "EET/EEST"

    # ── 1. ΩΡΑ ──
    open_, why = sales_window_open(now)

    if not open_:
        print(f"⏸  {why}")
        print("   Δεν εγκαθιστώ OCR.")
        return 1

    print(f"▶ {now:%H:%M} ώρα Ελλάδας ({tz}) — παράθυρο ανοιχτό")

    # ── 2. ΥΠΑΡΧΕΙ ΗΔΗ Η ΑΝΑΦΟΡΑ; ──
    if not os.environ.get("GOOGLE_KEY_JSON"):
        # Χωρίς credentials δεν μπορούμε να ξέρουμε — ας τρέξει και ας δούμε.
        print("  ! Λείπει το GOOGLE_KEY_JSON — αφήνω το κύριο script να αποφασίσει.")
        return 0

    # Η νεότερη μέρα προς αναζήτηση:
    #   Δευτέρα 23:00 → Δευτέρα
    #   Τρίτη   01:00 → ακόμα Δευτέρα
    newest_target = now.date() if now.hour >= 12 else now.date() - timedelta(days=1)

    try:
        df = load_sales()
    except Exception as e:
        print(f"  ! Δεν διάβασα το Sheet ({e}) — αφήνω το κύριο script να δοκιμάσει.")
        return 0

    if df.empty:
        print(f"  Το Sheet είναι άδειο. Ψάχνω από την {newest_target:%d/%m} και πίσω.")
        return 0

    have = {d.date() if hasattr(d, "date") else d for d in df["date"]}

    # Λείπει ΚΑΠΟΙΑ μέρα μέσα στο πρόσφατο παράθυρο; (όχι μόνο η χθεσινή)
    # Πρέπει να συμφωνεί με το LOOKBACK_DAYS του sales_sync.py.
    LOOKBACK_DAYS = 21
    window = [newest_target - timedelta(days=i) for i in range(LOOKBACK_DAYS + 1)]
    missing = [d for d in window if d not in have]

    if not missing:
        print(f"  ✓ Δεν λείπει καμία μέρα (έως {newest_target:%d/%m}).")
        print("   Δεν εγκαθιστώ OCR.")
        return 1

    print(f"  ⟳ Λείπουν {len(missing)} ημέρες (παλαιότερη: {min(missing):%d/%m}). "
          f"Εγκαθιστώ OCR και ψάχνω.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
