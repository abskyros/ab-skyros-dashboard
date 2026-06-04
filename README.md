# ΑΒ Σκύρος — Dashboard

Κεντρική εφαρμογή για παρακολούθηση **Παραστατικών** και **Πωλήσεων**.

---

## Αρχεία

| Αρχείο | Ρόλος |
|---|---|
| `app.py` | Κεντρική Streamlit εφαρμογή |
| `gsheets_helper.py` | Read/Write στο Google Sheets |
| `daily_sync.py` | Script για GitHub Actions (καθημερινός συγχρονισμός) |
| `.github/workflows/daily_sync.yml` | GitHub Actions workflow |
| `requirements.txt` | Python dependencies |

---

## Στήσιμο

### 1. Streamlit Secrets

Στο Streamlit Cloud → Settings → Secrets, πρόσθεσε:

```toml
EMAIL_PASS       = "app_password_του_abf.skyros@gmail.com"
SALES_EMAIL_PASS = "app_password_του_ftoulisgm@gmail.com"

[gcp_service_account]
type                        = "service_account"
project_id                  = "ab-skyros"
private_key_id              = "..."
private_key                 = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email                = "ab-skyros-bot@ab-skyros.iam.gserviceaccount.com"
client_id                   = "..."
auth_uri                    = "https://accounts.google.com/o/oauth2/auth"
token_uri                   = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url        = "..."
```

### 2. GitHub Secrets

Στο GitHub repo → Settings → Secrets and variables → Actions:

| Secret | Τιμή |
|---|---|
| `GOOGLE_KEY_JSON` | Ολόκληρο το περιεχόμενο του `ab-skyros-key.json` |
| `EMAIL_PASS` | App password του abf.skyros@gmail.com |
| `SALES_EMAIL_PASS` | App password του ftoulisgm@gmail.com |

### 3. Πρώτη φόρτωση δεδομένων

Μετά την ανάπτυξη της εφαρμογής:
1. Άνοιξε το tab **Πωλήσεις → Ενημέρωση**
2. Πάτα **"Βαθιά (2 χρόνια)"** για να φορτωθούν όλα τα ιστορικά δεδομένα
3. Για τα παραστατικά: πάτα **"Ανανέωση Παραστατικών"**

Μετά από αυτό, ο **GitHub Actions** αναλαμβάνει καθημερινά στις 08:00.

---

## Δομή Google Sheets

| Φύλλο | Στήλες |
|---|---|
| `sales` | date, net_sales, customers, avg_basket |
| `invoices` | date, type, value |
