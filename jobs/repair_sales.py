#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/repair_sales.py — Επισκευή ημερών που διαβάστηκαν λάθος από το OCR.

ΤΡΕΧΕΙ ΧΕΙΡΟΚΙΝΗΤΑ από τα Actions. Δεν έχει χρονοδιάγραμμα.

ΠΩΣ ΔΟΥΛΕΥΕΙ
    1. Διαβάζει το Sheet και βρίσκει τις ΥΠΟΠΤΕΣ μέρες — αυτές που αποκλίνουν
       >45% από την τυπική ίδια μέρα της εβδομάδας (ο ίδιος έλεγχος που
       δείχνει η εφαρμογή στις Πωλήσεις).
    2. Ψάχνει στα email τα PDF πωλήσεων ΜΟΝΟ για εκείνες τις ημερομηνίες
       (τα υπόλοιπα email δεν τα ανοίγει καν — το OCR είναι αργό).
    3. Ξαναδιαβάζει κάθε PDF με τον ΔΙΟΡΘΩΜΕΝΟ parser.
    4. Αν η νέα τιμή διαφέρει από αυτή του Sheet → προτείνει διόρθωση.
       Αν είναι ίδια → η μέρα ήταν σωστή, ΔΕΝ την πειράζει.

ΔΥΟ ΛΕΙΤΟΥΡΓΙΕΣ (όπως το deep_check)

    DRY RUN (προεπιλογή)
        Δείχνει τι ΘΑ άλλαζε, γραμμή-γραμμή. Δεν γράφει τίποτα.
        Τρέξε αυτό ΠΡΩΤΑ. Πάντα.

    APPLY
        Γράφει τις διορθώσεις στο Sheet. Χρειάζεται ρητά APPLY=yes.

ΑΣΦΑΛΕΙΑ
    • Πειράζει ΜΟΝΟ μέρες που ο μηχανισμός έχει σημάνει ως ύποπτες.
    • Μια μέρα ενημερώνεται ΜΟΝΟ αν το PDF δίνει ΔΙΑΦΟΡΕΤΙΚΗ τιμή.
    • Αν η νέα τιμή είναι κι αυτή ύποπτη (μακριά από την τυπική μέρα),
      την αναφέρει αλλά ΔΕΝ τη γράφει — θέλει ανθρώπινο μάτι.

Secrets: GOOGLE_KEY_JSON, SALES_EMAIL_PASS
Μεταβλητή: APPLY=yes → εκτέλεση (αλλιώς dry run)
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.mail import fetch_sales
from core.sheets import load_sales, update_sales
from core.metrics import find_anomalies, day_name

EMAIL_BUFFER_DAYS = 2      # το email έρχεται την ίδια ή την επόμενη μέρα
CHANGE_THRESHOLD   = 0.005 # <0.5% διαφορά = «ίδια τιμή», δεν πειράζουμε


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1

    password = os.environ.get("SALES_EMAIL_PASS", "") or os.environ.get("EMAIL_PASS", "")
    if not password:
        print("✗ Λείπει το SALES_EMAIL_PASS")
        return 1

    apply_mode = os.environ.get("APPLY", "").strip().lower() == "yes"
    today = date.today()

    print(f"▶ Επισκευή πωλήσεων — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Λειτουργία: {'ΕΚΤΕΛΕΣΗ (θα γράψει στο Sheet)' if apply_mode else 'DRY RUN (μόνο αναφορά)'}")

    # ── 1. ΥΠΟΠΤΕΣ ΜΕΡΕΣ ──
    df = load_sales()
    if df.empty:
        print("✗ Δεν φόρτωσαν πωλήσεις από το Sheet")
        return 1

    flagged = find_anomalies(df, today)
    if not flagged:
        print("\n✓ Καμία ύποπτη μέρα — τίποτα προς επισκευή.")
        return 0

    targets = {a["date"]: a for a in flagged}
    oldest = min(targets)

    print(f"\n· {len(targets)} ύποπτες μέρες, παλιότερη: {oldest:%d/%m/%Y}")

    # ── 2. EMAIL ΜΟΝΟ ΓΙΑ ΕΚΕΙΝΕΣ ΤΙΣ ΜΕΡΕΣ ──
    # Το fetch_sales παραλείπει το OCR όταν η μέρα του email ΚΑΙ η προηγούμενή
    # είναι στο skip_dates. Του δίνουμε ως skip ΟΛΕΣ τις μέρες εκτός των
    # ύποπτων — έτσι OCR γίνεται μόνο στα PDF που μας ενδιαφέρουν.
    since = oldest - timedelta(days=EMAIL_BUFFER_DAYS)
    skip = set()
    d = since
    while d <= today:
        if d not in targets:
            skip.add(d)
        d += timedelta(days=1)

    print("· Λήψη email και OCR στα ύποπτα PDF…")
    records, errors, seen = fetch_sales(
        password, since=since, limit=600, skip_dates=skip,
    )
    if errors:
        print(f"  ✗ {errors[0]}")
        return 1

    reread = {r["date"]: r for r in records if r.get("date") in targets}
    print(f"  · OCR σε {seen} PDF — βρέθηκαν {len(reread)} από τις {len(targets)} μέρες")

    # ── 3. ΣΥΓΚΡΙΣΗ & ΠΛΑΝΟ ──
    plan, same, missing, unsafe = [], [], [], []

    for d in sorted(targets, reverse=True):
        a = targets[d]
        old = a["net_sales"] or 0
        rec = reread.get(d)

        if rec is None:
            missing.append(d)
            continue

        new = rec["net_sales"]
        if new is None:
            missing.append(d)
            continue

        if old and abs(new - old) / old < CHANGE_THRESHOLD:
            same.append((d, old))
            continue

        # Η νέα τιμή είναι κι αυτή ύποπτη; Τότε δεν τη γράφουμε μόνοι μας.
        base = a["baseline"]
        if base and (new - base) / base * 100 < -45:
            unsafe.append((d, old, new, base))
            continue

        plan.append((d, old, new, rec))

    # ── 4. ΑΝΑΦΟΡΑ ──
    print("\n" + "─" * 62)

    for d, old, new, rec in plan:
        mark = "ΘΑ ΔΙΟΡΘΩΘΕΙ" if apply_mode else "θα διορθωθεί"
        print(f"  ✎ {day_name(d, short=True)} {d:%d/%m/%Y}: "
              f"{old:,.2f} € → {new:,.2f} €  [{mark}]")
        if apply_mode:
            ok, msg = update_sales(
                d, net_sales=new,
                customers=rec.get("customers"),
                avg_basket=rec.get("avg_basket"),
            )
            print(f"      {'✓' if ok else '✗'} {msg}")

    for d, old in same:
        print(f"  · {day_name(d, short=True)} {d:%d/%m/%Y}: {old:,.2f} € — "
              f"το PDF συμφωνεί, ΔΕΝ πειράχτηκε")

    for d, old, new, base in unsafe:
        print(f"  ! {day_name(d, short=True)} {d:%d/%m/%Y}: Sheet {old:,.2f} €, "
              f"PDF {new:,.2f} € — κι αυτό μακριά από τα τυπικά ~{base:,.2f} €. "
              f"ΔΕΝ γράφτηκε· έλεγξέ το με το χέρι.")

    for d in missing:
        print(f"  ? {day_name(d, short=True)} {d:%d/%m/%Y}: δεν βρέθηκε PDF στα email — "
              f"διόρθωσέ τη από την εφαρμογή (Πωλήσεις → Διόρθωση)")

    print("─" * 62)
    print(f"Σύνοψη: {len(plan)} προς διόρθωση, {len(same)} σωστές από την αρχή, "
          f"{len(unsafe)} θέλουν μάτι, {len(missing)} χωρίς PDF")

    if plan and not apply_mode:
        print("\nΑυτό ήταν DRY RUN — τίποτα δεν άλλαξε.")
        print("Αν οι νέες τιμές είναι οι σωστές, ξανατρέξε με APPLY=yes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
