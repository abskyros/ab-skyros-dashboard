#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/bills_sync.py — ΛΟΓΑΡΙΑΣΜΟΙ ΠΑΡΟΧΩΝ (ρεύμα, τηλέφωνο…) από τα email τους.

  PROVIDER = id παρόχου (κενό = όλοι οι ενεργοί)
  DAYS     = πόσες μέρες πίσω (default 60· νέος πάροχος από την εφαρμογή: 730 = 2 χρόνια)

Τρέχει: (α) μόλις προστεθεί πάροχος στην εφαρμογή — παλιοί λογαριασμοί,
(β) κάθε βράδυ/πρωί μέσα από το daily_sync — οι καινούργιοι.
Γράφει μόνο ό,τι δεν υπάρχει (ίδιος λογαριασμός = ίδιος κωδικός RF / αρχείο).
Αναφορά ανά email στο «pagia_log» (φαίνεται στην «Αναφορά ανάκτησης»).

Secrets: GOOGLE_KEY_JSON, SALES_EMAIL_PASS (ftoulisgm), EMAIL_PASS (abf.skyros)
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import INVOICES_EMAIL_USER, SALES_EMAIL_USER  # noqa: E402
from core.mail import fetch_bills  # noqa: E402
from core.sheets import append_pagia_log, load_providers, merge_pagia  # noqa: E402


def sync_bills(provider_id: str = "", days: int = 60, log: bool = True) -> int:
    """→ πόσοι νέοι λογαριασμοί γράφτηκαν (−1 = σφάλμα σύνδεσης)."""
    provs = [p for p in load_providers() if p["active"] and (not provider_id or p["id"] == provider_id)]
    if not provs:
        print("  · Κανένας πάροχος με email")
        return 0
    pws = {SALES_EMAIL_USER: os.environ.get("SALES_EMAIL_PASS", ""),
           INVOICES_EMAIL_USER: os.environ.get("EMAIL_PASS", "")}
    since = date.today() - timedelta(days=days)
    print(f"  ▶ {', '.join(p['name'] for p in provs)} · από {since:%d/%m/%Y}")
    report: list = []
    recs, notes = fetch_bills(pws, provs, since=since, report=report)
    for nt in notes:
        print(f"  ! {nt}")
    n = merge_pagia(recs)
    if log and report:
        run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        for e in report:
            e["run_at"] = run_at
        append_pagia_log(sorted(report, key=lambda e: e["email_date"]))
    for e in sorted(report, key=lambda e: e["email_date"]):
        print(f"      ✉ {e['email_date']} «{e['subject'][:70]}» → {e['found'] or e['notes']}")
    print(f"  ✓ {len(recs)} λογαριασμοί βρέθηκαν · {n} νέοι γράφτηκαν")
    if notes and not recs and all(x.startswith("✗") for x in notes):
        return -1
    return n


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1
    try:
        days = int(os.environ.get("DAYS") or 60)
    except ValueError:
        days = 60
    n = sync_bills((os.environ.get("PROVIDER") or "").strip(), min(max(days, 1), 1100))
    return 1 if n < 0 else 0


if __name__ == "__main__":
    sys.exit(main())
