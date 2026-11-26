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
    if provider_id:                    # «🔍 Αναζήτηση» από την εφαρμογή → αποτέλεσμα στον πάροχο
        _save_result(provs, recs, report, notes, since)
    if notes and not recs and all(x.startswith("✗") for x in notes):
        return -1
    return n


def _save_result(provs: list, recs: list, report: list, notes: list, since: date) -> None:
    """Γράφει στον πάροχο: πότε έγινε η αναζήτηση και τι βρέθηκε (φαίνεται στην εφαρμογή)."""
    from core.pagia import _eur
    from core.sheets import set_provider_fields
    when = datetime.now().strftime("%d/%m/%Y %H:%M")
    failed = [x for x in notes if x.startswith("✗")]
    for p in provs:
        mine = sorted((r for r in recs if r["kind"] == p["name"]), key=lambda r: r["pay_date"])
        n_mail = sum(1 for e in report if e["subject"].startswith(f"[{p['name']}]"))
        if mine:
            res = (f"{len(mine)} λογαριασμοί ({mine[0]['pay_date']:%m/%Y} – {mine[-1]['pay_date']:%m/%Y}) "
                   f"από {n_mail} email · τελευταίος {_eur(mine[-1]['amount'])} λήξη {mine[-1]['pay_date']:%d/%m/%Y}")
        elif failed and not n_mail:
            res = "✗ δεν έγινε σύνδεση με το Gmail — ξαναπάτα «🔍 Αναζήτηση»"
        else:
            res = (f"κανένας λογαριασμός από {since:%m/%Y}" + (f" ({n_mail} email χωρίς ποσό)" if n_mail else "")
                   + " — θα καταχωρούνται οι επόμενοι")
        set_provider_fields(p["id"], {"searched": when, "result": res})


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1
    try:
        days = int(os.environ.get("DAYS") or 60)
    except ValueError:
        days = 60
    n = sync_bills((os.environ.get("PROVIDER") or "").strip(), min(max(days, 1), 4000))
    return 1 if n < 0 else 0


if __name__ == "__main__":
    sys.exit(main())
