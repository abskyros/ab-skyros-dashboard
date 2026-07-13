#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/deep_check.py — Βαθύς έλεγχος παλιών παραστατικών.

ΤΡΕΧΕΙ ΧΕΙΡΟΚΙΝΗΤΑ. Δεν έχει χρονοδιάγραμμα — δεν θέλουμε να σβήνει γραμμές
μόνο του κάθε πρωί.

ΤΙ ΚΑΝΕΙ
    1. Κατεβάζει ΟΛΑ τα email παραστατικών (χωρίς όριο)
    2. Διαβάζει κάθε Excel → βρίσκει τον πραγματικό αριθμό κάθε παραστατικού
    3. Ταιριάζει τις παλιές γραμμές του Sheet με τους αριθμούς
    4. Σβήνει όσες αποδεικνύονται διπλές

ΔΥΟ ΛΕΙΤΟΥΡΓΙΕΣ

    DRY RUN (προεπιλογή)
        Δείχνει τι ΘΑ έκανε. Δεν αγγίζει τίποτα.
        Τρέξε αυτό ΠΡΩΤΑ. Πάντα.

    APPLY
        Εκτελεί. Χρειάζεται ρητό APPLY=yes.

ΓΙΑΤΙ ΔΕΝ ΤΡΕΧΕΙ ΑΥΤΟΜΑΤΑ
    Σβήνει γραμμές. Ένα script που σβήνει γραμμές μόνο του, κάθε μέρα, χωρίς
    να το βλέπει κανείς, είναι θέμα χρόνου να κάνει ζημιά. Ο άνθρωπος βλέπει
    το dry run, καταλαβαίνει τι θα γίνει, και μόνο τότε πατάει το κουμπί.

Secrets: GOOGLE_KEY_JSON, EMAIL_PASS
Μεταβλητή: APPLY=yes  → εκτέλεση (αλλιώς dry run)
"""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mail import fetch_all_invoices
from core.backfill import plan, apply, snapshot


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
    print(f"  ΒΑΘΥΣ ΕΛΕΓΧΟΣ ΠΑΡΑΣΤΑΤΙΚΩΝ — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Λειτουργία: {'ΕΚΤΕΛΕΣΗ ⚠️' if live else 'ΔΟΚΙΜΗ (τίποτα δεν αλλάζει)'}")
    print("═" * 64)

    # ── 1. ΣΑΡΩΣΗ ──
    print("\n▶ Σάρωση email…")

    def tick(scanned, found):
        print(f"  · {scanned:4d} email → {found:5d} παραστατικά")

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
    p = plan(records, emails_scanned=scanned)

    print(f"\n  Γραμμές στο Sheet: {p.sheet_rows}")
    print(f"  Είχαν ήδη αριθμό:  {p.already}")

    print("\n" + "─" * 64)
    print("  ΤΙ ΘΑ ΓΙΝΕΙ")
    print("─" * 64)

    if not p.touched:
        print("\n  ✓ Τίποτα. Όλα εντάξει.")
        return 0

    if p.fill:
        print(f"\n  ✓ ΓΕΜΙΣΜΑ — {len(p.fill)} γραμμές θα πάρουν τον αριθμό τους")
        for row, num in p.fill[:8]:
            print(f"      γρ. {row:5d}  →  #{num}")
        if len(p.fill) > 8:
            print(f"      … και άλλες {len(p.fill) - 8}")

    if p.delete:
        print(f"\n  🗑 ΔΙΑΓΡΑΦΗ — {len(p.delete)} γραμμές (αξίας {p.deleted_value:,.2f} €)")
        print(f"      Αποδεδειγμένα διπλές: υπάρχουν περισσότερες γραμμές")
        print(f"      από αριθμούς παραστατικών στα email.")
        preview = ", ".join(str(r) for r in p.delete[:15])
        print(f"      γραμμές: {preview}{' …' if len(p.delete) > 15 else ''}")

    if p.add:
        print(f"\n  + ΠΡΟΣΘΗΚΗ — {len(p.add)} παραστατικά λείπουν από το Sheet")
        for row in p.add[:5]:
            print(f"      {row[0]} · {row[1][:26]:26s} · {row[2]/100:>10,.2f} € · #{row[3]}")
        if len(p.add) > 5:
            print(f"      … και άλλα {len(p.add) - 5}")

    if p.skip:
        print(f"\n  ⊘ ΔΕΝ ΠΕΙΡΑΖΟΝΤΑΙ — {len(p.skip)} γραμμές")
        print(f"      Δεν βρέθηκαν σε κανένα email. Ίσως το email σβήστηκε,")
        print(f"      ίσως καταχωρήθηκαν με το χέρι. Μένουν ως έχουν.")
        for x in p.skip[:5]:
            print(f"      γρ. {x['row']:5d}  {x['date']}  {x['type'][:24]:24s}  {x['value']:>10,.2f} €")
        if len(p.skip) > 5:
            print(f"      … και άλλες {len(p.skip) - 5}")

    print("\n" + "─" * 64)

    # ── 3. ΕΚΤΕΛΕΣΗ ──
    if not live:
        print("\n  ΔΟΚΙΜΗ — τίποτα δεν άλλαξε.")
        print("\n  Για να εκτελεστεί:")
        print("    GitHub → Actions → «Βαθύς έλεγχος παραστατικών»")
        print("    → Run workflow → apply: yes")
        print()
        return 0

    if p.delete:
        print("\n⚠️  ΠΡΟΣΟΧΗ — αντίγραφο ασφαλείας")
        csv = snapshot()
        backup = Path("invoices_backup.csv")
        backup.write_text(csv, encoding="utf-8-sig")
        print(f"  ✓ Γράφτηκε στο {backup} ({len(csv):,} bytes)")
        print(f"  ✓ Ανέβηκε ως artifact του workflow — κατέβασέ το αν χρειαστεί")

    print("\n▶ Εκτέλεση…")
    done = apply(p)

    print(f"\n  ✓ {done['filled']} γραμμές πήραν αριθμό")
    print(f"  ✓ {done['deleted']} διπλές σβήστηκαν")
    print(f"  ✓ {done['added']} προστέθηκαν")

    if done["errors"]:
        print("\n  ✗ Σφάλματα:")
        for e in done["errors"]:
            print(f"      {e}")
        return 1

    print("\n✓ Ολοκληρώθηκε.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
