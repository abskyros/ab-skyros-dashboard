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
ΑΝΤΙΚΑΤΑΣΤΑΣΗ ΣΥΓΚΕΚΡΙΜΕΝΩΝ (KINDS = «ΑΑΔΕ,Λογιστής», SINCE/UNTIL = μήνες):
σβήνει ΜΟΝΟ αυτές τις κατηγορίες σε αυτούς τους μήνες (pagia + misthodosies),
διαβάζει τα email του διαστήματος (−3 μήνες / +2 μήνες περιθώριο) και κρατά ΜΟΝΟ
τις εγγραφές αυτών των κατηγοριών/μηνών. Όλα τα άλλα μένουν όπως είναι.
RESET=true (χωρίς KINDS) → ΑΔΕΙΑΖΕΙ πρώτα όλα τα «pagia», «misthodosies»,
«pagia_log» (σπάνια — ανακατασκευή όλων). Αλλιώς ό,τι υπάρχει δεν ξαναγράφεται.

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
from core.sheets import (append_pagia_log, merge_pagia, purge_pagia_kinds,  # noqa: E402
                         purge_pagia_log, reset_pagia_sheets)

TRIES = 3


def months(start: date, end: date):
    """(αρχή, τέλος) κάθε μήνα από `start` ως `end`."""
    d = start
    while d <= end:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        yield d, min(nxt - timedelta(days=1), end)
        d = nxt


def _month_start(raw: str, default: date) -> date:
    """«2025-07» / «2025-07-15» → 1η του μήνα. Κενό/λάθος → default."""
    try:
        y, m = (int(x) for x in (raw or "").strip().split("-")[:2])
        return date(y, m, 1)
    except (ValueError, TypeError):
        return default


def _shift(d: date, months_: int) -> date:
    """1η του μήνα, μετατοπισμένη κατά `months_` μήνες."""
    k = d.year * 12 + d.month - 1 + months_
    return date(k // 12, k % 12 + 1, 1)


def main() -> int:
    pw = os.environ.get("SALES_EMAIL_PASS", "")
    if not pw or not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει SALES_EMAIL_PASS ή GOOGLE_KEY_JSON")
        return 1

    today = date.today()
    since = _month_start(os.environ.get("SINCE") or "", date.fromisoformat(PAGIA_FROM))
    until_m = _month_start(os.environ.get("UNTIL") or "", date(today.year, today.month, 1))
    only = [k.strip() for k in (os.environ.get("KINDS") or "").split(",") if k.strip()]
    ref_from, ref_to = f"{since:%Y-%m}", f"{until_m:%Y-%m}"
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    if only:
        # Τα email ενός μήνα έρχονται συνήθως τον επόμενο (μισθοδοσία) ή νωρίτερα (ΑΑΔΕ).
        mail_from = _shift(since, -3)
        mail_to = min(today, _shift(until_m, 3) - timedelta(days=1))
        gone = purge_pagia_kinds(only, ref_from, ref_to)
        purge_pagia_log(f"{mail_from:%Y-%m-%d}", f"{mail_to:%Y-%m-%d}")
        print(f"▶ ΑΝΤΙΚΑΤΑΣΤΑΣΗ: {', '.join(only)} · μήνες {ref_from} – {ref_to} · "
              f"σβήστηκαν {gone}")
        print(f"▶ Email από {mail_from:%d/%m/%Y} ως {mail_to:%d/%m/%Y}, ανά μήνα, ένα email τη φορά")
    else:
        if (os.environ.get("RESET") or "").strip().lower() in ("true", "1", "yes"):
            print(f"▶ ΑΔΕΙΑΣΜΑ: {', '.join(reset_pagia_sheets())}")
        mail_from, mail_to = since, min(today, _shift(until_m, 1) - timedelta(days=1))
        print(f"▶ Ανάκτηση παγίων από {mail_from:%d/%m/%Y} ως {mail_to:%d/%m/%Y}, "
              f"ανά μήνα, ένα email τη φορά")

    total_found = total_new = n_mails = 0
    failed, warns = [], []
    kinds: dict = {}
    for a, b in months(mail_from, mail_to):
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
        if only:                       # ΜΟΝΟ οι επιλεγμένες κατηγορίες, στους επιλεγμένους μήνες
            recs = [r for r in recs if r.get("kind") in only
                    and ref_from <= str(r.get("ref") or "")[:7] <= ref_to]
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
