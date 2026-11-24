#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/pagia_backfill.py — Ανάκτηση ΠΑΓΙΩΝ (μισθοδοσία, δώρα/επιδόματα, ΕΦΚΑ/ΤΕΚΑ,
ΑΑΔΕ) από τα email του λογιστή, από το SINCE (default: core.config.PAGIA_FROM) ως σήμερα.

ΓΙΑΤΙ ΕΔΩ ΚΑΙ ΟΧΙ ΣΤΗΝ ΕΦΑΡΜΟΓΗ: η ανάκτηση από το 2024 κατεβάζει εκατοντάδες
μεγάλα συνημμένα. Στο Streamlit Cloud δεν τελείωνε. Εδώ:
  • ΑΝΑ ΜΗΝΑ, ΕΝΑ email τη φορά (προσεκτικά, λίγη μνήμη — ο χρόνος δεν μας πειράζει)
  • νέα προσπάθεια αν το Gmail δεν απαντήσει (έως 3 φορές ανά μήνα)
  • γράφει στο Sheet μετά από ΚΑΘΕ μήνα — αν κοπεί, δεν χάνεται ό,τι έγινε
  • ΑΝΑΦΟΡΑ ανά email στο φύλλο «pagia_log» (αρχεία · τι βρέθηκε · έλεγχοι)
  • υπάρχει OCR → διαβάζονται και τα έγγραφα που έρχονται ως φωτογραφία
RESET=true → ΑΔΕΙΑΖΕΙ πρώτα τα «pagia», «misthodosies», «pagia_log» (ανάκτηση από
την αρχή). Αλλιώς ό,τι υπάρχει ήδη δεν ξαναγράφεται.

Secrets: GOOGLE_KEY_JSON, SALES_EMAIL_PASS
"""

import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import PAGIA_FROM  # noqa: E402
from core.mail import fetch_pagia  # noqa: E402
from core.sheets import append_pagia_log, merge_pagia, reset_pagia_sheets  # noqa: E402

TRIES = 3


def months(start: date, end: date):
    """(αρχή, τέλος) κάθε μήνα από `start` ως `end`."""
    d = start
    while d <= end:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
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
    if (os.environ.get("RESET") or "").strip().lower() in ("true", "1", "yes"):
        print(f"▶ ΑΔΕΙΑΣΜΑ: {', '.join(reset_pagia_sheets())}")
    today = date.today()
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"▶ Ανάκτηση παγίων από {since:%d/%m/%Y} ως σήμερα, ανά μήνα, ένα email τη φορά")

    total_found = total_new = n_mails = 0
    failed, warns = [], []
    kinds: dict = {}
    for a, b in months(since, today):
        for t in range(1, TRIES + 1):
            report: list = []
            recs, notes = fetch_pagia(pw, since=a, until=b, limit=500, bulk=False, report=report)
            if not (notes and notes[0].startswith("✗") and not recs):
                break
            print(f"  … {a:%m/%Y}: {notes[0]} — προσπάθεια {t}/{TRIES}")
            time.sleep(30 * t)
        else:
            failed.append(f"{a:%m/%Y}")
            print(f"  ✗ {a:%m/%Y}: ΔΕΝ διαβάστηκε ({notes[0]})")
            continue
        n = merge_pagia(recs)
        for e in report:
            e["run_at"] = run_at
        append_pagia_log(sorted(report, key=lambda e: e["email_date"]))
        n_mails += len(report)
        total_found += len(recs)
        total_new += n
        for r in recs:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
            if str(r.get("check", "")).startswith("⚠"):
                warns.append(f"{r['kind']} {r['ref']} {r.get('sub', '')}: {r['check']}")
        print(f"  · {a:%m/%Y}: {len(report)} email, {len(recs)} ποσά, {n} νέα")
        for e in sorted(report, key=lambda e: e["email_date"]):
            print(f"      ✉ {e['email_date']} «{e['subject'][:70]}»")
            for line in (e["files"] or "").splitlines():
                print(f"          📎 {line}")
            for line in (e["found"] or "").splitlines():
                print(f"          → {line}")
            for line in (e["notes"] or "").splitlines():
                print(f"          ! {line}")

    print(f"\n✓ {n_mails} email · {total_found} ποσά ({kinds}) · {total_new} νέα γράφτηκαν στο «pagia».")
    if warns:
        print(f"⚠ {len(warns)} μισθοδοσίες δεν συμφωνούν με τα σύνολα:")
        for w in warns:
            print(f"   {w}")
    if failed:
        print(f"✗ Μήνες που ΔΕΝ διαβάστηκαν (ξανατρέξε με SINCE): {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
