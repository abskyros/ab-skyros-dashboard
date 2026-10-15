# AB Σκύρος — Dashboard (CLAUDE.md)

> Αρχείο πλαισίου για το Claude Code. Διάβασέ το πρώτο σε κάθε session.
> Μίλα ΕΛΛΗΝΙΚΑ με τον χρήστη (Μάνος, ιδιοκτήτης AB Σκύρος).

## Τι είναι

Streamlit dashboard για το σουπερμάρκετ **AB Σκύρος** (franchise ΑΒ Βασιλόπουλος, νησί Σκύρος, κατάστημα 1082).
Παρακολουθεί **πωλήσεις, παραστατικά, τιμολογήσεις/επιταγές** — τραβάει δεδομένα αυτόματα από email και τα κρατάει σε Google Sheets.

## Πώς δουλεύει ο χρήστης (ΣΗΜΑΝΤΙΚΟ)

- **Θέλει να καταλαβαίνει την ΑΙΤΙΑ πριν τη διόρθωση.** Εξήγησε το root cause πρώτα.
- **Προτιμά στοχευμένες αλλαγές**, όχι μεγάλες αναδιαρθρώσεις. Πες τι θα αλλάξεις & γιατί, πάρε ΟΚ πριν γράψεις κώδικα.
- **Δοκιμάζει μόνος του** πριν θεωρήσει κάτι τελειωμένο.
- Δουλεύει συχνά από **κινητό**. Προτιμά σταθερή βάση + βελτιώσεις πάνω της, όχι πήγαινε-έλα.

## Αρχιτεκτονική

- **Streamlit 1.50.0** (ΚΑΡΦΩΜΕΝΟ — ProgressColumn χωρίς param χρώματος· width μόνο "small"/"medium"/"large").
- **Backend: Google Sheets** (gspread 6.1.4). Όλα τα ποσά ως **ΛΕΠΤΑ (ακέραιοι, ×100)** για αποφυγή locale κόμμα/τελεία.
- **Email: Gmail IMAP** (imap-tools 1.7.4) + **OCR** (pytesseract/pdf2image/tesseract/poppler) — OCR μόνο στα GitHub Actions, ΟΧΙ στο Streamlit Cloud.
- **Σύγκριση YoY**: offset **364 μέρες** (ίδια μέρα εβδομάδας πέρσι). 2 χρόνια = 728 μέρες.

## Δομή αρχείων

- `app.py` — είσοδος Streamlit (sync κουμπιά, deep scan, διαγνωστικά).
- `core/config.py` — ΜΙΑ πηγή αλήθειας: emails, sheet IDs, σταθερές.
- `core/mail.py` — κατεβάζει συνημμένα από email (πωλήσεις/παραστατικά/τιμολογήσεις).
- `core/parsers.py` — parse PDF/Excel (`parse_sales_pdf` κ.λπ.).
- `core/sheets.py` — ανάγνωση/εγγραφή Google Sheets (singleton + batch + retry για 429).
- `core/metrics.py` — υπολογισμοί (`last_year`, `two_years_ago`, `sales_on`, `week_to_date`...).
- `core/diag.py` — διαγνωστικά (`check_mailbox`, `run_all`, `sales_logic_report`).
- `ui/components.py` — κάρτες (`scale`, `target`, `stat`, `row`, `year_row`).
- `ui/style.css` — στυλ (midnight navy #101a2f + gold #c8992e).
- `views/` — σελίδες (`overview.py`, `sales.py`, ...).
- `jobs/sales_sync.py`, `jobs/sales_precheck.py` — τα scripts που τρέχει το GitHub Actions.
- `.github/workflows/` — cron jobs (sales_sync.yml, data_sync.yml, ...).

## Email — πηγές (core/config.py)

| Ροή | Αποστολέας | Γραμματοκιβώτιο |
|---|---|---|
| Πωλήσεις (PDF→OCR) | `abf.skyros@gmail.com` | `ftoulisgm@gmail.com` |
| Παραστατικά | `Notifications@WeDoConnect.com` | `abf.skyros@gmail.com` |
| Τιμολογήσεις | `fr.georgios.manos.ftoylis@ab.gr` | `ftoulisgm@gmail.com` |

## Κρίσιμα σημεία (μαθήματα από προηγούμενα sessions)

1. **ΔΥΟ χωριστά secret stores:** Streamlit Cloud secrets ΚΑΙ GitHub Actions secrets.
   **Κάθε αλλαγή κωδικού/κώδικα πρέπει να μπει ΚΑΙ στα δύο.** (Υπήρξε root cause: ο χρήστης ενημέρωνε μόνο το Streamlit.)
2. **Το φίλτρο πωλήσεων (`_is_sales` στο core/mail.py) κοιτάζει ΜΟΝΟ τον αποστολέα** — ΟΧΙ το θέμα.
   Τα email πωλήσεων μπορεί να έρχονται με θέμα «ΑΒ ΣΚΥΡΟΣ», «AB SKYROS», ή **ΚΕΝΟ**. Η επαλήθευση γίνεται μετά: πρέπει να υπάρχει PDF & το OCR να βγάλει έγκυρη ημερομηνία + τζίρο.
3. **GitHub cron σε UTC** (χωρίς θερινή ώρα). Τα scripts ελέγχουν την πραγματική ώρα Ελλάδας (zoneinfo Europe/Athens) και βγαίνουν αν είναι νωρίς.
4. **Το GitHub στραγγαλίζει τα συχνά/στρογγυλά crons.** Χρησιμοποιούμε αραιότερα (*/15) + σίγουρα runs σε **μη-στρογγυλά λεπτά** (:27, :43). Δίχτυ ασφαλείας: πρωινός συγχρονισμός 05:00 UTC πιάνει ό,τι χάθηκε.
5. **FORCE_RUN** (όταν `github.event_name == 'workflow_dispatch'`) παρακάμπτει τους ελέγχους ώρας — για χειροκίνητα runs.
6. **DEEP/SINCE** = βαθιά σάρωση (ανοίγει ΟΛΑ τα email παρακάμπτοντας skip_dates· max 90 μέρες).
7. **Αναφορά «For X» ≠ ημερομηνία email.** Το PDF γράφει «For 12/10» αλλά το email ήρθε 11/10 βράδυ (EOD). Η ημερομηνία ΜΕΣΑ στο PDF είναι η σωστή.

## Κανόνες

- **ΔΕΝ** κάνεις commit/push χωρίς να το ζητήσει ρητά ο χρήστης.
- Μετά από αλλαγές: τρέξε `python -c "import ast; ast.parse(open('<file>').read())"` (syntax) + έλεγχο για undefined names (pyflakes).
- Email χρήστη `ftoulisgm@gmail.com`: χρήση ΜΟΝΟ για ταυτοποίηση, ποτέ αποστολή σε τρίτη υπηρεσία.
