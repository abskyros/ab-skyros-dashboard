"""
core/notify.py — Ειδοποιήσεις μέσω email.

Στέλνει email ΜΟΝΟ όταν υπάρχει κάτι να πει (π.χ. νέα διπλή χρέωση). Σιωπή
όταν όλα καλά.

┌────────────────────────────────────────────────────────────────────────────┐
│ ΦΙΛΟΣΟΦΙΑ                                                                   │
│                                                                            │
│ Μια ειδοποίηση που έρχεται κάθε μέρα με τα ίδια πράγματα, γίνεται θόρυβος   │
│ και την αγνοείς. Γι' αυτό κρατάμε ΜΝΗΜΗ τι έχουμε ήδη στείλει — και         │
│ στέλνουμε μόνο τα ΚΑΙΝΟΥΡΓΙΑ.                                              │
│                                                                            │
│ Το Gmail που ήδη διαβάζουμε (IMAP) στέλνει και email (SMTP) με τον ίδιο     │
│ κωδικό εφαρμογής. Μηδέν νέα credentials.                                    │
└────────────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr

# Το Gmail στέλνει από τον ίδιο server που διαβάζουμε.
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465   # SSL

# Από ποιο mailbox φεύγουν οι ειδοποιήσεις, και σε ποιον πάνε.
# Στέλνουμε από το mailbox των παραστατικών στον εαυτό του — απλό και σίγουρο.
NOTIFY_FROM = "abf.skyros@gmail.com"
NOTIFY_TO = "abf.skyros@gmail.com"
NOTIFY_NAME = "AB Σκύρος — Ειδοποιήσεις"


def send_email(subject: str, body_html: str, password: str,
               to: str = NOTIFY_TO) -> tuple[bool, str]:
    """
    Στέλνει ένα email HTML.

    → (επιτυχία, μήνυμα σφάλματος αν απέτυχε)

    Το password είναι ο ΙΔΙΟΣ κωδικός εφαρμογής Gmail που χρησιμοποιούμε για
    το διάβασμα (EMAIL_PASS στα secrets).
    """
    if not password:
        return False, "Λείπει ο κωδικός email"

    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((NOTIFY_NAME, NOTIFY_FROM))
    msg["To"] = to

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=30) as server:
            server.login(NOTIFY_FROM, password)
            server.sendmail(NOTIFY_FROM, [to], msg.as_string())
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# ΕΙΔΟΠΟΙΗΣΗ: ΝΕΕΣ ΔΙΠΛΕΣ ΧΡΕΩΣΕΙΣ
# ══════════════════════════════════════════════════════════════════════════════
def _charge_signature(charge: dict) -> str:
    """
    Μοναδική «υπογραφή» μιας διπλής χρέωσης, για να ξέρουμε αν την έχουμε ξαναδεί.

    Χτίζεται από τους ΑΡΙΘΜΟΥΣ παραστατικών (που είναι μοναδικοί) — έτσι αν
    ξαναέρθει η ίδια ακριβώς διπλή χρέωση, την αναγνωρίζουμε.
    """
    nums = sorted(str(n) for n in charge.get("numbers", []))
    return "|".join(nums)


def format_charges_email(new_charges: list[dict], eur_fn) -> tuple[str, str]:
    """
    Φτιάχνει θέμα + σώμα HTML για email διπλών χρεώσεων.

    → (subject, body_html)
    """
    n = len(new_charges)
    total = sum(c["value"] * (c["count"] - 1) for c in new_charges)

    subject = (
        f"⚠️ {n} νέα πιθανή διπλή χρέωση" if n == 1
        else f"⚠️ {n} νέες πιθανές διπλές χρεώσεις"
    )

    rows = []
    for c in new_charges:
        nums = " · ".join(f"#{x}" for x in c["numbers"])
        d = c["date"]
        dstr = d if isinstance(d, str) else f"{d:%d/%m/%Y}"
        rows.append(
            f'<tr>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #eee">{dstr}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #eee;'
            f'font-weight:700">{eur_fn(c["value"])}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #eee">×{c["count"]}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #eee;'
            f'color:#666;font-size:13px">{nums}</td>'
            f'</tr>'
        )

    body = f"""\
<div style="font-family:-apple-system,system-ui,Arial,sans-serif;max-width:600px;margin:0 auto">
  <div style="background:#1e3a5f;color:#fff;padding:20px 24px;border-radius:12px 12px 0 0">
    <div style="font-size:18px;font-weight:800">AB Σκύρος</div>
    <div style="opacity:.85;font-size:13px;margin-top:2px">Έλεγχος παραστατικών</div>
  </div>

  <div style="border:1px solid #e2e8f0;border-top:none;padding:24px;border-radius:0 0 12px 12px">
    <p style="font-size:15px;color:#1e293b;margin:0 0 8px">
      Βρέθηκαν <b>{n}</b> παραστατικά με <b>ίδιο ποσό και ίδια μέρα</b>,
      αλλά διαφορετικό αριθμό.
    </p>
    <p style="font-size:14px;color:#64748b;margin:0 0 20px">
      Αν είναι διπλές χρεώσεις, μιλάμε για <b style="color:#dc2626">{eur_fn(total)}</b>.
      Μπορεί όμως να είναι δύο κανονικές παραδόσεις — έλεγξε τα δελτία αποστολής.
    </p>

    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="text-align:left;color:#94a3b8;font-size:12px;text-transform:uppercase">
          <th style="padding:8px 12px">Ημερομηνία</th>
          <th style="padding:8px 12px">Ποσό</th>
          <th style="padding:8px 12px">Φορές</th>
          <th style="padding:8px 12px">Αριθμοί</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>

    <p style="font-size:12px;color:#94a3b8;margin:24px 0 0;padding-top:16px;
              border-top:1px solid #f1f5f9">
      Αυτόματη ειδοποίηση από την εφαρμογή AB Σκύρος. Δεν χρειάζεται απάντηση.
    </p>
  </div>
</div>"""

    return subject, body


# ══════════════════════════════════════════════════════════════════════════════
# ΕΙΔΟΠΟΙΗΣΗ: ΠΑΡΑΓΓΕΛΙΕΣ ΠΟΥ ΠΡΕΠΕΙ ΝΑ ΦΥΓΟΥΝ ΣΗΜΕΡΑ
# ══════════════════════════════════════════════════════════════════════════════
def format_order_reminder_email(
    suppliers_today: list[dict], categories_today: list[dict], today_label: str,
) -> tuple[str, str]:
    """
    Φτιάχνει θέμα + σώμα HTML για το πρωινό email παραγγελιών.

    suppliers_today   : γραμμές από core.sheets.current_suppliers(), ήδη
                         φιλτραρισμένες σε όσες έχουν order_days σήμερα.
    categories_today   : ίδιο, από current_order_schedule().
    today_label        : π.χ. "Δευτέρα 26/8"

    → (subject, body_html)
    """
    n = len(suppliers_today) + len(categories_today)
    subject = f"📦 Παραγγελίες σήμερα · {today_label} ({n})"

    rows = []
    for s in suppliers_today:
        method = str(s.get("order_method") or "email")
        contact = s.get("phone") if method == "phone" else s.get("email")
        deadline = f' · έως {s["order_deadline"]}' if s.get("order_deadline") else ""
        notes = f'<div style="color:#94a3b8;font-size:12px;margin-top:2px">{s["notes"]}</div>' if s.get("notes") else ""
        rows.append(
            f'<tr><td style="padding:10px 12px;border-bottom:1px solid #eee">'
            f'<b>{s["supplier"]}</b>{notes}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:13px">'
            f'{method}: {contact or "—"}{deadline}</td></tr>'
        )
    for c in categories_today:
        rows.append(
            f'<tr><td style="padding:10px 12px;border-bottom:1px solid #eee">'
            f'<b>{c["category"]}</b><div style="color:#94a3b8;font-size:12px">εσωτερική παραγγελία ΑΒ</div></td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #eee;font-size:13px">αποθήκη {c.get("warehouse_code","")}</td></tr>'
        )

    body = f"""\
<div style="font-family:-apple-system,system-ui,Arial,sans-serif;max-width:600px;margin:0 auto">
  <div style="background:#1e3a5f;color:#fff;padding:20px 24px;border-radius:12px 12px 0 0">
    <div style="font-size:18px;font-weight:800">AB Σκύρος</div>
    <div style="opacity:.85;font-size:13px;margin-top:2px">Παραγγελίες · {today_label}</div>
  </div>

  <div style="border:1px solid #e2e8f0;border-top:none;padding:24px;border-radius:0 0 12px 12px">
    <p style="font-size:15px;color:#1e293b;margin:0 0 16px">
      Σήμερα πρέπει να φύγουν <b>{n}</b> παραγγελί{"α" if n == 1 else "ες"}.
    </p>

    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="text-align:left;color:#94a3b8;font-size:12px;text-transform:uppercase">
          <th style="padding:8px 12px">Ποιος</th>
          <th style="padding:8px 12px">Πώς / πότε</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>

    <p style="font-size:12px;color:#94a3b8;margin:24px 0 0;padding-top:16px;
              border-top:1px solid #f1f5f9">
      Αυτόματη υπενθύμιση από την εφαρμογή AB Σκύρος. Δες τη σελίδα «Προμηθευτές»
      για τα πλήρη στοιχεία.
    </p>
  </div>
</div>"""

    return subject, body


def notify_new_double_charges(all_charges: list[dict], password: str,
                              load_seen, save_seen, eur_fn) -> dict:
    """
    Ελέγχει ποιες διπλές χρεώσεις είναι ΝΕΕΣ, στέλνει email μόνο γι' αυτές,
    και θυμάται τι έστειλε.

    all_charges : ό,τι επιστρέφει το find_double_charges()
    load_seen   : συνάρτηση που διαβάζει τις ήδη-ειδοποιημένες υπογραφές (str)
    save_seen   : συνάρτηση που αποθηκεύει τις υπογραφές (str)
    eur_fn      : μορφοποίηση ποσού (π.χ. components.eur)

    → {"new": int, "sent": bool, "error": str}
    """
    if not all_charges:
        return {"new": 0, "sent": False, "error": ""}

    # Ποιες έχουμε ήδη στείλει;
    seen_raw = load_seen()
    seen = set(seen_raw.split("\n")) if seen_raw else set()

    # Ποιες είναι καινούργιες;
    new_charges = [
        c for c in all_charges
        if _charge_signature(c) not in seen
    ]

    if not new_charges:
        return {"new": 0, "sent": False, "error": ""}

    # Στείλε email
    subject, body = format_charges_email(new_charges, eur_fn)
    ok, err = send_email(subject, body, password)

    if not ok:
        return {"new": len(new_charges), "sent": False, "error": err}

    # Θυμήσου ό,τι στείλαμε (πρόσθεσε τις νέες υπογραφές)
    for c in new_charges:
        seen.add(_charge_signature(c))
    save_seen("\n".join(sorted(seen)))

    return {"new": len(new_charges), "sent": True, "error": ""}
