#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/duplicate_scan.py — Βαθιά σάρωση για διπλά παραστατικά (2 έτη).

ΤΙ ΨΑΧΝΕΙ
    Παραστατικά με τον ΙΔΙΟ αριθμό που ήρθαν σε ΔΥΟ ή περισσότερα
    ΔΙΑΦΟΡΕΤΙΚΑ email. Δύο περιπτώσεις:

      • Ίδιος αριθμός + ίδιο ποσό  → το τιμολόγιο κόπηκε/στάλθηκε δύο φορές.
        Πιθανή ΔΙΠΛΗ ΧΡΕΩΣΗ — θέλει έλεγχο και τηλέφωνο στον προμηθευτή.
      • Ίδιος αριθμός + άλλο ποσό  → ακύρωση/επανέκδοση ή λάθος. Επίσης ύποπτο.

ΤΙ ΚΑΝΕΙ ΜΕ ΟΣΑ ΒΡΕΙ
    Τα καταγράφει στο φύλλο «dipla» (upsert — το ξανατρέξιμο δεν φτιάχνει
    διπλές εγγραφές). Τα βλέπεις στην εφαρμογή, στη σελίδα «Παραστατικά».

    ΔΕΝ ΣΒΗΝΕΙ ΤΙΠΟΤΑ. Ούτε από το Sheet, ούτε από το mail.
    Είναι μητρώο υπόπτων — η απόφαση είναι δική σου.

ΓΙΑΤΙ ΣΑΡΩΝΕΙ ΤΟ MAIL ΚΑΙ ΟΧΙ ΤΟ SHEET
    Ο συγχρονισμός κρατάει κάθε αριθμό ΜΙΑ φορά στο Sheet. Αν το ίδιο
    τιμολόγιο σταλεί ξανά, η δεύτερη αποστολή χάνεται σιωπηλά. Μόνο το
    αρχείο του mail θυμάται ΚΑΙ τις δύο φορές.

Secrets: GOOGLE_KEY_JSON, EMAIL_PASS
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mail import fetch_all_invoices
from core.sheets import collect_duplicate_alerts, log_duplicate_alerts
from core.config import DEEP_SCAN_YEARS

YEARS = DEEP_SCAN_YEARS


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1

    password = os.environ.get("EMAIL_PASS", "")
    if not password:
        print("✗ Λείπει το EMAIL_PASS")
        return 1

    since = date.today() - timedelta(days=YEARS * 365)

    print("═" * 64)
    print(f"  ΣΑΡΩΣΗ ΔΙΠΛΩΝ ΠΑΡΑΣΤΑΤΙΚΩΝ — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Περίοδος: από {since:%d/%m/%Y} ({YEARS} έτη)")
    print("═" * 64)

    # ── 1. ΣΑΡΩΣΗ ΟΛΩΝ ΤΩΝ EMAIL ──
    print("\n▶ Σάρωση email…")

    def tick(scanned, found):
        print(f"  · {scanned:4d} email → {found:5d} παραστατικά")

    records, errors, scanned = fetch_all_invoices(password, since=since, on_progress=tick)

    if errors:
        print(f"\n✗ {errors[0]}")
        return 1

    if not records:
        print("\n✗ Δεν βρέθηκε κανένα παραστατικό στα email.")
        return 1

    print(f"\n  Σύνολο: {scanned} email, {len(records)} παραστατικά")

    # ── 2. ΟΜΑΔΟΠΟΙΗΣΗ ΑΝΑ ΑΡΙΘΜΟ ──
    #
    # Ο αριθμός είναι η ταυτότητα. Αν εμφανίζεται σε 2+ ΔΙΑΦΟΡΕΤΙΚΑ email,
    # το παραστατικό στάλθηκε/κόπηκε ξανά.
    no_number = sum(1 for r in records if not str(r.get("number", "") or "").strip())
    alerts = collect_duplicate_alerts(records, source="scan")

    # ── 3. ΑΝΑΦΟΡΑ ──
    print("\n" + "─" * 64)
    print("  ΑΠΟΤΕΛΕΣΜΑΤΑ")
    print("─" * 64)

    if no_number:
        print(f"\n  (Παραλείφθηκαν {no_number} εγγραφές χωρίς αριθμό — δεν ελέγχονται)")

    if not alerts:
        print("\n  ✓ Καμία διπλή αποστολή. Κάθε αριθμός ήρθε μία φορά.")
        return 0

    same_amount = [a for a in alerts if len(a["amounts"]) == 1]
    diff_amount = [a for a in alerts if len(a["amounts"]) > 1]

    extra_cents = sum((a["times"] - 1) * a["value_cents"] for a in same_amount)

    print(f"\n  ⚠ {len(alerts)} αριθμοί ήρθαν πάνω από μία φορά:")
    print(f"      · {len(same_amount)} με ΙΔΙΟ ποσό  → πιθανές διπλές χρεώσεις")
    print(f"      · {len(diff_amount)} με ΔΙΑΦΟΡΕΤΙΚΟ ποσό → ακυρώσεις/επανεκδόσεις;")
    if extra_cents:
        print(f"\n  Αν οι ομοίες είναι διπλές χρεώσεις, μιλάμε για {extra_cents / 100:,.2f} €")

    print("\n  Οι 20 πιο βαριές περιπτώσεις:")
    for a in alerts[:20]:
        dates_txt = ", ".join(a["doc_dates"][:4])
        same = "ίδιο ποσό" if len(a["amounts"]) == 1 else f"ΠΟΣΑ: {' / '.join(a['amounts'])}"
        print(f"      #{a['number']:<12} {a['value_cents'] / 100:>10,.2f} € × {a['times']}  "
              f"({same})  {dates_txt}")
    if len(alerts) > 20:
        print(f"      … και άλλες {len(alerts) - 20}")

    # ── 4. ΚΑΤΑΓΡΑΦΗ ──
    print("\n▶ Καταγραφή στο φύλλο «dipla»…")
    written = log_duplicate_alerts(alerts)
    print(f"  ✓ {written} εγγραφές. Τις βλέπεις στην εφαρμογή → «Παραστατικά».")

    print("\n  Δεν σβήστηκε και δεν άλλαξε τίποτα στα δεδομένα.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
