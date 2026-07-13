#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/clean_invoices.py — Η ΜΕΓΑΛΗ ΚΑΘΑΡΙΟΤΗΤΑ.

Τρέχει ΜΙΑ ΦΟΡΑ, χειροκίνητα. Καθαρίζει ΟΛΑ τα χρόνια.

Από εδώ και πέρα είναι άχρηστο: το data_sync κρατάει το Sheet καθαρό μόνο του,
γιατί το κλειδί είναι ο ΑΡΙΘΜΟΣ ΠΑΡΑΣΤΑΤΙΚΟΥ και δεν αφήνει το ίδιο τιμολόγιο
να μπει δύο φορές.

ΤΙ ΚΑΝΕΙ
    1. Κατεβάζει ΟΛΑ τα email παραστατικών
    2. Γεμίζει τους αριθμούς στις γραμμές που δεν τους έχουν
    3. Σβήνει ό,τι απομείνει χωρίς αριθμό — αποδεδειγμένα διπλά

Η ΛΟΓΙΚΗ
    Η 10/07 έχει 11 τιμολόγια στα email.
    Το Sheet έχει 30 γραμμές για την 10/07.
    Οι 11 πρώτες παίρνουν τους 11 αριθμούς.
    Οι 19 υπόλοιπες ΔΕΝ ΕΧΟΥΝ αριθμό να πάρουν — άρα είναι διπλές.

    Δεν μαντεύουμε. Μετράμε.

ΔΥΟ ΛΕΙΤΟΥΡΓΙΕΣ
    DRY RUN (προεπιλογή) — δείχνει τι ΘΑ έκανε. Δεν αγγίζει τίποτα.
    APPLY=yes            — εκτελεί.

    Τρέξε το dry run ΠΡΩΤΑ. Πάντα.

Secrets: GOOGLE_KEY_JSON, EMAIL_PASS
"""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mail import fetch_all_invoices
from core.backfill import repair, apply_repair, snapshot


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1

    password = os.environ.get("EMAIL_PASS", "")
    if not password:
        print("✗ Λείπει το EMAIL_PASS")
        return 1

    live = os.environ.get("APPLY", "").strip().lower() in ("yes", "true", "1")

    print("═" * 64)
    print(f"  ΚΑΘΑΡΙΣΜΟΣ ΠΑΡΑΣΤΑΤΙΚΩΝ — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  {'ΕΚΤΕΛΕΣΗ ⚠️' if live else 'ΔΟΚΙΜΗ — τίποτα δεν αλλάζει'}")
    print("═" * 64)

    # ── 1. ΣΑΡΩΣΗ ──
    print("\n▶ Σάρωση email…")

    def tick(scanned, found):
        print(f"  · {scanned:4d} email → {found:6d} παραστατικά", flush=True)

    records, errors, scanned = fetch_all_invoices(password, on_progress=tick)

    if errors:
        print(f"\n✗ {errors[0]}")
        return 1

    if not records:
        print("\n✗ Δεν βρέθηκε κανένα παραστατικό στα email.")
        return 1

    print(f"\n  Σύνολο: {scanned} email, {len(records)} παραστατικά")

    # ── 2. ΣΧΕΔΙΟ ──
    print("\n▶ Σύγκριση με το Sheet…")
    rep = repair(records)          # ΧΩΡΙΣ όρια → όλα τα χρόνια

    print(f"\n  Γραμμές στο Sheet: {rep['scanned']:,}".replace(",", "."))

    print("\n" + "─" * 64)
    print("  ΤΙ ΘΑ ΓΙΝΕΙ")
    print("─" * 64)

    if not rep["fill"] and not rep["delete"]:
        print("\n  ✓ Το Sheet είναι ήδη καθαρό.")
        return 0

    if rep["fill"]:
        print(f"\n  ✓ ΓΕΜΙΣΜΑ — {len(rep['fill'])} γραμμές θα πάρουν τον αριθμό τους")
        for row, num in rep["fill"][:6]:
            print(f"      γρ. {row:6d}  →  #{num}")
        if len(rep["fill"]) > 6:
            print(f"      … και άλλες {len(rep['fill']) - 6}")

    if rep["delete"]:
        print(f"\n  🗑 ΔΙΑΓΡΑΦΗ — {len(rep['delete'])} γραμμές")
        print(f"      Αξία: {rep['value']:,.2f} €")
        print(f"      Αποδεδειγμένα διπλές: περισσότερες γραμμές από αριθμούς")
        print(f"      παραστατικών στα email.")
        preview = ", ".join(str(r) for r in rep["delete"][:12])
        print(f"      γραμμές: {preview}{' …' if len(rep['delete']) > 12 else ''}")

    if rep["keep"]:
        print(f"\n  ⊘ ΔΕΝ ΠΕΙΡΑΖΟΝΤΑΙ — {len(rep['keep'])} γραμμές")
        print(f"      Δεν υπάρχουν σε κανένα email. Σβησμένο email; Χειροκίνητη")
        print(f"      καταχώρηση; Δεν ξέρουμε — άρα δεν αποφασίζουμε.")

    after = rep["scanned"] - len(rep["delete"])
    print(f"\n  Το Sheet: {rep['scanned']:,} → {after:,} γραμμές".replace(",", "."))
    print("\n" + "─" * 64)

    # ── 3. ΕΚΤΕΛΕΣΗ ──
    if not live:
        print("\n  ΔΟΚΙΜΗ — τίποτα δεν άλλαξε.")
        print("\n  Για εκτέλεση:")
        print("    Actions → «Καθαρισμός παραστατικών» → Run workflow → apply: yes")
        print()
        return 0

    if rep["delete"]:
        print("\n⚠️  Αντίγραφο ασφαλείας…")
        csv = snapshot()
        Path("invoices_backup.csv").write_text(csv, encoding="utf-8-sig")
        print(f"  ✓ invoices_backup.csv ({len(csv):,} bytes)".replace(",", "."))
        print(f"  ✓ Ανεβαίνει ως artifact — φυλάσσεται 30 μέρες")

    print("\n▶ Εκτέλεση…")
    print("  (παύσεις 1,2\" — το Google επιτρέπει 60 εγγραφές/λεπτό)\n")

    last = [""]

    def progress(stage, cur, total):
        if stage != last[0]:
            print(f"  {stage}:")
            last[0] = stage
        print(f"    {cur}/{total}", flush=True)

    done = apply_repair(rep, on_progress=progress)

    print("\n" + "─" * 64)
    print(f"  Γέμισμα:   {done['filled']:6d} γραμμές")
    print(f"  Διαγραφή:  {done['deleted']:6d} γραμμές")
    print("─" * 64)

    if done["errors"]:
        print("\n  ✗ ΔΕΝ ΟΛΟΚΛΗΡΩΘΗΚΕ")
        for e in done["errors"]:
            print(f"      {e}")
        print("\n  Ξανατρέξε το — θα συνεχίσει από εκεί που έμεινε.")
        print("  Τίποτα δεν χάθηκε.")
        return 1

    print("\n✓ Ολοκληρώθηκε. Το Sheet είναι καθαρό.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
