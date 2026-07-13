# ΑΒ Σκύρος — Dashboard

Πωλήσεις, παραστατικά και τιμολογήσεις σε μία οθόνη.

---

## Τι άλλαξε από την προηγούμενη έκδοση

| | Πριν | Τώρα |
|---|---|---|
| **Δομή** | 2.061 γραμμές σε ένα `app.py` | 4 στρώματα, καμία λογική στις σελίδες |
| **Parsing** | Αντιγραμμένο σε 3 αρχεία | Γραμμένο μία φορά στο `core/parsers.py` |
| **Γραφήματα** | `st.line_chart` | Plotly με hover που δείχνει φέτος & πέρσι μαζί |
| **CSS** | ~40 HTML strings μέσα στη λογική | Ένα `style.css` |
| **Segfault** | `.style.format()` έριχνε το app | Μορφοποίηση πριν το dataframe |
| **Bug λεπτών** | Το `daily_sync.py` έγραφε ευρώ, τα άλλα λεπτά | Όλα από το `core/sheets.py` |

### Το bug που διορθώθηκε

Το παλιό `daily_sync.py` έγραφε στο Sheet **ευρώ** (`1547.73`), ενώ τα
`data_sync.py` και `sales_sync.py` έγραφαν **λεπτά** (`154773`).

Η εφαρμογή διαβάζει πάντα `/100`. Άρα ό,τι έγραφε το `daily_sync.py` εμφανιζόταν
100 φορές μικρότερο: **1.547,73 € → 15,48 €**.

Τώρα και τα τρία περνούν από το `core/sheets.py`, που κάνει τη μετατροπή μία
φορά, σωστά.

---

## Δομή

```
streamlit_app.py          Router. Δεν κάνει τίποτα άλλο.
│
├── core/                 ΤΙ κάνει η εφαρμογή
│   ├── config.py         Σταθερές. Μία πηγή αλήθειας.
│   ├── sheets.py         Όλο το Google Sheets I/O. Cached σωστά.
│   ├── metrics.py        Επιχειρηματική λογική. Καθαρές συναρτήσεις.
│   ├── parsers.py        Excel, CSV, PDF+OCR. Γραμμένα μία φορά.
│   └── mail.py           Ανάγνωση Gmail.
│
├── ui/                   ΠΩΣ φαίνεται
│   ├── style.css         Όλο το CSS.
│   ├── components.py     Όλο το HTML.
│   └── charts.py         Plotly.
│
├── views/                Οι 5 σελίδες. Καλούν core/ και ui/. Τίποτα άλλο.
│
└── jobs/                 GitHub Actions. Χρησιμοποιούν το ίδιο core/.
```

Ο κανόνας: **HTML γράφεται μόνο στο `ui/components.py`.** Αν χρειαστεί αλλαγή
εμφάνισης, δεν αγγίζεις λογική. Και το αντίστροφο.

---

## Οι κανόνες του μαγαζιού

Είναι στο `core/metrics.py`, με σχόλια που εξηγούν το γιατί.

**Σύγκριση με πέρσι = 364 ημέρες πίσω**, όχι «ίδια ημερομηνία».
52 εβδομάδες πέφτουν πάντα στην ίδια μέρα της εβδομάδας. Το Σάββατο συγκρίνεται
με Σάββατο. Η 17/3 πέρσι μπορεί να ήταν Τρίτη — άχρηστη σύγκριση για λιανική.

**Εβδομάδα ως τώρα vs οι ίδιες μέρες πέρσι.**
Αν είναι Τετάρτη, συγκρίνουμε Δευ–Τετ με Δευ–Τετ πέρσι. Όχι με ολόκληρη
περσινή εβδομάδα — αλλιώς κάθε Δευτέρα θα φαινόμασταν 85% κάτω.

**Η επιταγή καλύπτει τις 7 μέρες πριν από αυτήν** και «πέφτει» στην εβδομάδα
πριν την ημερομηνία της.

**Καθαρό παραστατικών = τιμολόγια − πιστωτικά.**

**Στο Sheet όλα τα ποσά είναι λεπτά** (ακέραιοι). Έτσι δεν μας πειράζει το
ελληνικό locale με κόμμα/τελεία.

---

## Στήσιμο

### 1. Streamlit Cloud

Main file: `streamlit_app.py`

Settings → Secrets:

```toml
EMAIL_PASS       = "app_password_του_abf.skyros@gmail.com"
SALES_EMAIL_PASS = "app_password_του_ftoulisgm@gmail.com"

[gcp_service_account]
type                        = "service_account"
project_id                  = "ab-skyros"
private_key_id              = "…"
private_key                 = "-----BEGIN PRIVATE KEY-----\n…\n-----END PRIVATE KEY-----\n"
client_email                = "ab-skyros-bot@ab-skyros.iam.gserviceaccount.com"
client_id                   = "…"
auth_uri                    = "https://accounts.google.com/o/oauth2/auth"
token_uri                   = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url        = "…"
```

### 2. GitHub Secrets

Settings → Secrets and variables → Actions:

| Secret | Τιμή |
|---|---|
| `GOOGLE_KEY_JSON` | Όλο το περιεχόμενο του `ab-skyros-key.json` |
| `EMAIL_PASS` | App password του `abf.skyros@gmail.com` |
| `SALES_EMAIL_PASS` | App password του `ftoulisgm@gmail.com` |

Ίδια με πριν — δεν χρειάζεται να αλλάξεις τίποτα.

---

## Αυτόματος συγχρονισμός

| Workflow | Πότε | Τι |
|---|---|---|
| `data_sync.yml` | Κάθε 2 ώρες | Παραστατικά + τιμολογήσεις |
| `sales_sync.yml` | Κάθε 30′, 20:00–02:00 | Πωλήσεις (OCR) |
| `daily_sync.yml` | 08:00 | Και τα τρία — δίχτυ ασφαλείας |
| `quality_check.yml` | 10:00 | Ψάχνει διπλά & κενά. **Δεν σβήνει τίποτα.** |

Όλα είναι idempotent — μπορούν να τρέξουν όσες φορές θέλουν χωρίς κίνδυνο.

---

## Δεδομένα

Το Google Sheet **δεν αλλάζει**. Ίδιο ID, ίδια φύλλα, ίδιες στήλες.

| Φύλλο | Στήλες |
|---|---|
| `sales` | `date`, `net_sales`, `customers`, `avg_basket` |
| `invoices` | `date`, `type`, `value` |
| `timologiseis` | `check_date`, `period`, `amount`, `check_number`, `expenses` |

Όλα τα ποσά σε **λεπτά**.

---

## Γιατί δεν σκάει πια

Το παλιό app έπεφτε με segmentation fault στο Streamlit Cloud. Τρεις αιτίες,
τρεις λύσεις:

**1. `.style.format()`**
Ο pandas Styler χτίζει ολόκληρο HTML στη μνήμη. Με 10.000 γραμμές παραστατικών,
τέλος. → Μορφοποιούμε **πριν** το dataframe, σε απλά strings.

**2. Εκατοντάδες widgets**
Το παλιό loop έφτιαχνε `st.text_input` σε κάθε γραμμή της σελίδας «Μήνας».
→ **Ένα** `data_editor`, όσες γραμμές κι αν έχει.

**3. Uncached client**
Κάθε rerun έφτιαχνε νέο `gspread` connection. → `@st.cache_resource` singleton.
Στο cache μπαίνουν **μόνο** DataFrames — ποτέ ζωντανά worksheet objects.

**Και το OCR δεν φορτώνεται ποτέ στο Streamlit Cloud.** Το `pdf2image` και το
`pytesseract` χρειάζονται system libs (poppler, tesseract) που δεν υπάρχουν εκεί
— και μόνο το import τους ρίχνει την εφαρμογή. Γι' αυτό υπάρχουν δύο αρχεία:

- `requirements.txt` → Streamlit Cloud. **Χωρίς OCR.**
- `requirements-ocr.txt` → GitHub Actions. Εκεί εγκαθιστούμε tesseract & poppler.

---

## Τοπική εκτέλεση

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# συμπλήρωσε τα κλειδιά
streamlit run streamlit_app.py
```

Ένα job χειροκίνητα:

```bash
export GOOGLE_KEY_JSON="$(cat ab-skyros-key.json)"
export EMAIL_PASS="…"
python jobs/data_sync.py
```
