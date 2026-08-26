#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jobs/order_reminders.py — Πρωινή υπενθύμιση παραγγελιών.

Τρέχει κάθε πρωί. Κοιτάει το φύλλο «suppliers» και «order_schedule» και
στέλνει email ΜΟΝΟ αν κάποιος προμηθευτής ή κατηγορία έχει order_days που
περιλαμβάνει τη ΣΗΜΕΡΙΝΗ μέρα. Αν δεν πρέπει να φύγει καμία παραγγελία
σήμερα, δεν στέλνει τίποτα — σιωπή όταν δεν υπάρχει κάτι να πει.

Το «σήμερα» υπολογίζεται στην ώρα Ελλάδας, όχι στην ώρα UTC του runner.

Secrets: GOOGLE_KEY_JSON, EMAIL_PASS
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.metrics import today_greece, day_name
from core.notify import send_email, format_order_reminder_email
from core.sheets import current_suppliers, current_order_schedule


def _due_today(df, day_col: str, name: str) -> list[dict]:
    if df.empty or day_col not in df.columns:
        return []
    hits = df[df[day_col].fillna("").apply(
        lambda cell: name in [d.strip() for d in cell.split(",") if d.strip()]
    )]
    return hits.to_dict("records")


def main() -> int:
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("✗ Λείπει το GOOGLE_KEY_JSON")
        return 1

    password = os.environ.get("EMAIL_PASS", "")
    if not password:
        print("✗ Λείπει το EMAIL_PASS")
        return 1

    today = today_greece()
    name = day_name(today)
    today_label = f"{name} {today:%d/%m}"

    print(f"▶ Έλεγχος παραγγελιών για {today_label}…")

    suppliers_today = _due_today(current_suppliers(), "order_days", name)
    categories_today = _due_today(current_order_schedule(), "order_days", name)

    total = len(suppliers_today) + len(categories_today)
    if total == 0:
        print("  Καμία παραγγελία δεν πρέπει να φύγει σήμερα. Δεν στέλνεται email.")
        return 0

    print(f"  {len(suppliers_today)} προμηθευτές, {len(categories_today)} κατηγορίες ΑΒ.")

    subject, body = format_order_reminder_email(suppliers_today, categories_today, today_label)
    ok, err = send_email(subject, body, password)

    if ok:
        print(f"  ✓ Στάλθηκε το email υπενθύμισης ({total} υποχρεώσεις).")
        return 0

    print(f"✗ Απέτυχε η αποστολή: {err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
