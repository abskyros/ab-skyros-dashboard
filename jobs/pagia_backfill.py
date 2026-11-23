#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/pagia_backfill.py — Ανάκτηση ΠΑΓΙΩΝ (μισθοδοσία, ΕΦΚΑ/ΤΕΚΑ, ΑΑΔΕ) από
τα email του λογιστή, από το SINCE (default: core.config.PAGIA_FROM) ως σήμερα.

ΓΙΑΤΙ ΕΔΩ ΚΑΙ ΟΧΙ ΣΤΗΝ ΕΦΑΡΜΟΓΗ: η ανάκτηση από το 2024 κατεβάζει εκατοντάδες
μεγάλα συνημμένα (5 αρχεία μισθοδοσίας τον μήνα). Στο Streamlit Cloud έτρεχε
πάνω από 15 λεπτά χωρίς να τελειώσει. Εδώ:
  • ΑΝΑ ΤΡΙΜΗΝΟ, ένα email τη φορά (όχι όλα μαζί στη μνήμη)
  • γράφει στο Sheet μετά από ΚΑΘΕ τρίμηνο — αν κοπεί, δεν χάνεται ό,τι έγινε
  • υπάρχει OCR → διαβάζονται και τα έγγραφα που έρχονται ως φωτογραφία
Ό,τι υπάρχει ήδη στο φύλλο «pagia» δεν ξαναγράφεται.

Secrets: GOOGLE_KEY_JSON, SALES_EMAIL_PASS
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import PAGIA_FROM  # noqa: E402
from core.mail import fetch_pagia  # noqa: E402
from core.sheets import merge_pagia  # noqa: E402


def quarters(start: date, end: date):
    """(αρχή, τέλος) τριμήνων από `start` ως `end`."""
    d = start
    while d <= end:
        m = ((d.month - 1) // 3) * 3 + 1
        nxt = date(d.year + (m + 3 > 12), (m + 3 - 1) % 12 + 1, 1)
        yield d, min(nxt - timedelta(days=1), end)
        d = nxt


def main() -> int:
    pw = os.environ.get("SALES_EMAIL_PASS", "")
    if not pw or not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει SALES_EMAIL_PASS ή GOOGLE_KEY_JSON")
        return 1

    raw = (os.environ.get("SINCE") or "").strip() or PAGIA_FROM
    try:
        since = date.fromisoformat(raw)
    except ValueError:
        since = date.fromisoformat(PAGIA_FROM)
    today = date.today()
    print(f"▶ Ανάκτηση παγίων από {since:%d/%m/%Y} ως σήμερα, ανά τρίμηνο")

    total_found = total_new = 0
    kinds: dict = {}
    for a, b in quarters(since, today):
        # bulk=True ανά τρίμηνο: λίγα email τη φορά (όχι όλα τα χρόνια μαζί) αλλά
        # με μία αίτηση — πολύ πιο γρήγορο από ένα-ένα (το πρώτο πέρασμα έφτασε τα 90').
        recs, notes = fetch_pagia(pw, since=a, until=b, limit=200, bulk=True)
        if notes and notes[0].startswith("✗") and not recs:
            print(f"  ✗ {a:%m/%Y}–{b:%m/%Y}: {notes[0]}")
            continue
        n = merge_pagia(recs)
        total_found += len(recs)
        total_new += n
        for r in recs:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        found = ", ".join(f"{r['kind']} {r['ref']}" for r in sorted(recs, key=lambda x: x["ref"]))
        print(f"  · {a:%d/%m/%Y}–{b:%d/%m/%Y}: {len(recs)} βρέθηκαν, {n} νέα  {found}")
        for nt in notes[:5]:
            print(f"      ! {nt}")

    print(f"\n✓ Σύνολο: {total_found} ποσά ({kinds}) · {total_new} νέα γράφτηκαν στο «pagia».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
