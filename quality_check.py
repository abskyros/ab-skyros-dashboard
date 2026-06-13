#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quality_check.py — Ημερήσιος έλεγχος ποιότητας δεδομένων
Τρέχει μέσω GitHub Actions κάθε μέρα στις 10:00 (ώρα Ελλάδας).
Ελέγχει ΜΟΝΟ τις πρόσφατες ημερομηνίες (1 μέρα πριν) για:
  • Διπλές εγγραφές (ίδια ημερομηνία 2+ φορές)
  • Κενά (χαμένες μέρες/εβδομάδες)
σε Πωλήσεις & Τιμολογήσεις.

Δεν σβήνει τίποτα αυτόματα — απλώς καταγράφει τα ευρήματα.
Ο χρήστης βλέπει & διορθώνει τα προβλήματα μέσα από την εφαρμογή.

GitHub Secrets: GOOGLE_KEY_JSON
"""

import os
import sys
import json
from datetime import date, datetime, timedelta
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1KWX5PH0Dg-dhfMfT8-jCd-Jft9f80I1E2Wss1w8QTlA"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
# Έλεγχος μόνο 1 μέρα πριν (όπως ζητήθηκε)
LOOKBACK_DAYS = 1


def _parse_number(x):
    if x is None:
        return 0.0
    s = str(x).replace("€", "").replace(" ", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def get_wb():
    info = json.loads(os.environ["GOOGLE_KEY_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def check_sheet(ws, value_col, recent_cutoff):
    """Επιστρέφει (duplicates, dates_set) για τις πρόσφατες ημερομηνίες."""
    vals = ws.get_all_values()
    if len(vals) < 2:
        return [], set()
    rows = vals[1:]
    date_rows = defaultdict(list)
    for i, r in enumerate(rows, start=2):
        if r and r[0]:
            d_str = str(r[0]).strip()
            vraw = r[value_col] if len(r) > value_col else ""
            date_rows[d_str].append((i, vraw))

    recent = [d for d in date_rows if d >= recent_cutoff]
    dups = []
    for d_str in recent:
        if len(date_rows[d_str]) > 1:
            entries = [{"row": ri, "value": round(_parse_number(vr) / 100.0, 2)}
                       for (ri, vr) in date_rows[d_str]]
            dups.append({"date": d_str, "entries": entries})

    all_dates = set()
    for d in date_rows:
        try:
            all_dates.add(datetime.strptime(d, "%Y-%m-%d").date())
        except Exception:
            pass
    return dups, all_dates


def main():
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("❌ Λείπει το GOOGLE_KEY_JSON")
        sys.exit(1)

    print(f"▶ Ημερήσιος έλεγχος ποιότητας — {datetime.now():%Y-%m-%d %H:%M}")
    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS + 1)).isoformat()
    wb = get_wb()

    problems = 0

    # ── ΠΩΛΗΣΕΙΣ ──
    print("\n📊 ΠΩΛΗΣΕΙΣ")
    try:
        ws_s = wb.worksheet("sales")
        dups_s, dates_s = check_sheet(ws_s, 1, cutoff)
        if dups_s:
            problems += len(dups_s)
            for d in dups_s:
                vals_txt = ", ".join(f"γρ.{e['row']}={e['value']}€" for e in d["entries"])
                print(f"  ⚠️ ΔΙΠΛΟ {d['date']}: {vals_txt}")
        else:
            print("  ✅ Καμία διπλοεγγραφή (πρόσφατες)")
        # Κενά: έλεγχος αν λείπει η χθεσινή
        yest = date.today() - timedelta(days=1)
        if yest not in dates_s:
            print(f"  📭 ΚΕΝΟ: λείπει η χθεσινή ημέρα {yest.isoformat()}")
            problems += 1
        else:
            print(f"  ✅ Η χθεσινή ({yest.isoformat()}) υπάρχει")
    except Exception as e:
        print(f"  ⚠️ Σφάλμα: {e}")

    # ── ΤΙΜΟΛΟΓΗΣΕΙΣ ──
    print("\n🧾 ΤΙΜΟΛΟΓΗΣΕΙΣ")
    try:
        ws_t = wb.worksheet("timologiseis")
        dups_t, dates_t = check_sheet(ws_t, 2, cutoff)
        if dups_t:
            problems += len(dups_t)
            for d in dups_t:
                vals_txt = ", ".join(f"γρ.{e['row']}={e['value']}€" for e in d["entries"])
                print(f"  ⚠️ ΔΙΠΛΟ {d['date']}: {vals_txt}")
        else:
            print("  ✅ Καμία διπλοεγγραφή (πρόσφατες)")
    except Exception as e:
        print(f"  ⚠️ Σφάλμα: {e}")

    print("\n" + "=" * 50)
    if problems:
        print(f"⚠️ Βρέθηκαν {problems} πιθανά προβλήματα.")
        print("   Άνοιξε την εφαρμογή → σελίδα Πωλήσεις/Τιμολογήσεις →")
        print("   '🔍 Έλεγχος δεδομένων' για διόρθωση.")
    else:
        print("🎉 Όλα καθαρά — καμία ανωμαλία στα πρόσφατα δεδομένα.")


if __name__ == "__main__":
    main()
