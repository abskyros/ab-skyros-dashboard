#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sales_sync.py — Νυχτερινός συγχρονισμός Πωλήσεων (OCR)
Τρέχει μέσω GitHub Actions κάθε βράδυ στις 23:00 (ώρα Ελλάδας).
Διαβάζει τα πιο πρόσφατα emails πωλήσεων, κάνει OCR και αποθηκεύει
νέες ημέρες στο φύλλο "sales" του Google Sheets.

GitHub Secrets που απαιτούνται:
  • GOOGLE_KEY_JSON  — ολόκληρο το service-account JSON
  • SALES_EMAIL_PASS — App password του ftoulisgm@gmail.com
"""

import io
import os
import re
import json
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from imap_tools import MailBox, AND
from pdf2image import convert_from_bytes
import pytesseract

# ── CONFIG ──
SPREADSHEET_ID     = "1KWX5PH0Dg-dhfMfT8-jCd-Jft9f80I1E2Wss1w8QTlA"
SALES_EMAIL_USER   = "ftoulisgm@gmail.com"
SALES_EMAIL_SENDER = "abf.skyros@gmail.com"
SALES_SUBJECT_KW   = "ΑΒ ΣΚΥΡΟΣ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
OCR_DPI = 180
# Πόσες μέρες πίσω να ελέγχει (incremental — μικρό παράθυρο για ταχύτητα)
LOOKBACK_DAYS = 10
EMAIL_SCAN_LIMIT = 80

SALES_PW = os.environ.get("SALES_EMAIL_PASS", "")


def get_sheet():
    info = json.loads(os.environ["GOOGLE_KEY_JSON"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    wb = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = wb.worksheet("sales")
    except Exception:
        ws = wb.add_worksheet(title="sales", rows=5000, cols=5)
    vals = ws.get_all_values()
    if not vals or [str(c).strip().lower() for c in vals[0][:4]] != ["date", "net_sales", "customers", "avg_basket"]:
        ws.clear()
        ws.append_row(["date", "net_sales", "customers", "avg_basket"])
    return ws


def extract_sales_from_pdf(pdf_bytes):
    r = {"date": None, "net_sales": None, "customers": None, "avg_basket": None}
    try:
        images = convert_from_bytes(pdf_bytes, dpi=OCR_DPI, first_page=1, last_page=1)
        if not images:
            return r
        t = pytesseract.image_to_string(images[0].rotate(90, expand=True),
                                        lang="ell+eng", config="--psm 6 --oem 3")
        m = re.search(r"Run\s+[Oo0]n\s*[:\s]+(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t, re.IGNORECASE)
        if m:
            try: r["date"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except: pass
        if not r["date"]:
            m = re.search(r"\bFor\s+(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t, re.IGNORECASE)
            if m:
                try: r["date"] = date(int(m.group(3)), int(m.group(2)), int(m.group(1))) - timedelta(days=1)
                except: pass
        m = re.search(r"Net[Dd]ay[Ss]al[Dd]is\s+([\d.,]+)", t, re.IGNORECASE)
        if not m:
            m = re.search(r"Ne[t7][Dd]ay\S+\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                v = float(raw)
                if 500 < v < 500000: r["net_sales"] = round(v, 2)
            except: pass
        m = re.search(r"Num[O0]fCus\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            try:
                v = int(re.sub(r"[.,]", "", m.group(1).split()[0]))
                if 10 < v < 5000: r["customers"] = v
            except: pass
        m = re.search(r"Avg[Ss]al[Cc]us\s+([\d.,]+)", t, re.IGNORECASE)
        if m:
            try:
                raw = m.group(1).replace(".", "").replace(",", ".")
                v = float(raw)
                if 1 < v < 1000: r["avg_basket"] = round(v, 2)
            except: pass
        if r["net_sales"] and r["customers"] and not r["avg_basket"]:
            ab = r["net_sales"] / r["customers"]
            if 1 < ab < 1000: r["avg_basket"] = round(ab, 2)
    except Exception:
        pass
    return r


def valid_subj(s):
    s = (s or "").upper()
    return SALES_SUBJECT_KW in s or "SKYROS" in s


def main():
    if not SALES_PW:
        print("❌ Λείπει το SALES_EMAIL_PASS")
        sys.exit(1)
    if not os.environ.get("GOOGLE_KEY_JSON"):
        print("❌ Λείπει το GOOGLE_KEY_JSON")
        sys.exit(1)

    print(f"▶ Νυχτερινός συγχρονισμός πωλήσεων — {datetime.now():%Y-%m-%d %H:%M}")
    ws = get_sheet()
    existing = {str(r[0]).strip() for r in ws.get_all_values()[1:] if r}
    print(f"  Ήδη αποθηκευμένες: {len(existing)} ημέρες")

    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    added = 0
    with MailBox("imap.gmail.com").login(SALES_EMAIL_USER, SALES_PW) as mb:
        for msg in mb.fetch(limit=EMAIL_SCAN_LIMIT, reverse=True, mark_seen=False):
            mdate = msg.date.date() if msg.date else None
            if mdate and mdate < cutoff:
                break
            if SALES_EMAIL_SENDER.lower() not in (msg.from_ or "").lower():
                continue
            if not valid_subj(msg.subject):
                continue
            pdfs = [a for a in msg.attachments if a.filename and a.filename.lower().endswith(".pdf")]
            for pdf in pdfs:
                rec = extract_sales_from_pdf(pdf.payload)
                if rec["date"] and rec["net_sales"] is not None:
                    d_str = rec["date"].isoformat()
                    if d_str in existing:
                        break
                    existing.add(d_str)
                    ws.append_row([
                        d_str,
                        round(rec["net_sales"] * 100),
                        int(rec["customers"]) if rec["customers"] else "",
                        round(rec["avg_basket"] * 100) if rec["avg_basket"] else "",
                    ], value_input_option="RAW")
                    added += 1
                    print(f"  + {d_str}: {rec['net_sales']}€")
                    break

    print(f"✅ Ολοκληρώθηκε — {added} νέες ημέρες πωλήσεων.")


if __name__ == "__main__":
    main()
