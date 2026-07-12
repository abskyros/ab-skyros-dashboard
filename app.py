"""
app.py — ΔΙΑΓΝΩΣΤΙΚΟ (προσωρινό)
Φορτώνει τα κομμάτια ένα-ένα για να βρούμε πού σκάει.
Κάθε βήμα εμφανίζει ✅ πριν προχωρήσει στο επόμενο.
Το τελευταίο ✅ που βλέπεις = το επόμενο βήμα είναι ο ένοχος.
"""
import streamlit as st

st.set_page_config(page_title="Διάγνωση", layout="wide")
st.title("🔍 Διάγνωση ΑΒ Σκύρος")

# ── ΒΗΜΑ 1: Βασικά imports ──
st.write("**Βήμα 1:** Βασικά imports...")
try:
    import pandas as pd
    import io, re
    from datetime import datetime, date, timedelta
    st.success("✅ Βήμα 1 OK — pandas, datetime")
except Exception as e:
    st.error(f"❌ Βήμα 1 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 2: imap_tools ──
st.write("**Βήμα 2:** imap_tools...")
try:
    from imap_tools import MailBox, AND
    st.success("✅ Βήμα 2 OK — imap_tools")
except Exception as e:
    st.error(f"❌ Βήμα 2 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 3: gsheets_helper import ──
st.write("**Βήμα 3:** gsheets_helper import...")
try:
    from gsheets_helper import (
        load_sales, load_invoices, load_timologiseis,
    )
    st.success("✅ Βήμα 3 OK — gsheets_helper φορτώθηκε")
except Exception as e:
    st.error(f"❌ Βήμα 3 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 4: Secrets ──
st.write("**Βήμα 4:** Έλεγχος secrets...")
try:
    _has_google = "GOOGLE_KEY_JSON" in st.secrets or "gcp_service_account" in st.secrets
    st.success(f"✅ Βήμα 4 OK — secrets διαθέσιμα (Google key: {_has_google})")
except Exception as e:
    st.error(f"❌ Βήμα 4 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 5: Φόρτωση ΠΩΛΗΣΕΩΝ (το πιο βαρύ) ──
st.write("**Βήμα 5:** Φόρτωση πωλήσεων από Google Sheets...")
try:
    df_s = load_sales()
    st.success(f"✅ Βήμα 5 OK — {len(df_s)} γραμμές πωλήσεων")
    st.write(f"Μνήμη DataFrame: {df_s.memory_usage(deep=True).sum() / 1024:.1f} KB")
except Exception as e:
    st.error(f"❌ Βήμα 5 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 6: Φόρτωση ΠΑΡΑΣΤΑΤΙΚΩΝ ──
st.write("**Βήμα 6:** Φόρτωση παραστατικών...")
try:
    df_i = load_invoices()
    st.success(f"✅ Βήμα 6 OK — {len(df_i)} γραμμές παραστατικών")
except Exception as e:
    st.error(f"❌ Βήμα 6 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 7: Φόρτωση ΤΙΜΟΛΟΓΗΣΕΩΝ ──
st.write("**Βήμα 7:** Φόρτωση τιμολογήσεων...")
try:
    df_t = load_timologiseis()
    st.success(f"✅ Βήμα 7 OK — {len(df_t)} γραμμές τιμολογήσεων")
except Exception as e:
    st.error(f"❌ Βήμα 7 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 8: Μεγάλο CSS block ──
st.write("**Βήμα 8:** Φόρτωση CSS...")
try:
    st.markdown("<style>" + ("/* filler */ " * 500) + "</style>", unsafe_allow_html=True)
    st.success("✅ Βήμα 8 OK — CSS")
except Exception as e:
    st.error(f"❌ Βήμα 8 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 9: line_chart (γραφήματα Overview) ──
st.write("**Βήμα 9:** Γράφημα...")
try:
    if not df_s.empty:
        _c = df_s.head(20)[["net_sales"]].reset_index(drop=True)
        st.line_chart(_c, height=200)
    st.success("✅ Βήμα 9 OK — γράφημα")
except Exception as e:
    st.error(f"❌ Βήμα 9 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

# ── ΒΗΜΑ 10: data_editor (σελίδα Μήνας) ──
st.write("**Βήμα 10:** data_editor...")
try:
    if not df_t.empty:
        st.data_editor(df_t.head(10), hide_index=True, key="diag_editor")
    st.success("✅ Βήμα 10 OK — data_editor")
except Exception as e:
    st.error(f"❌ Βήμα 10 ΑΠΕΤΥΧΕ: {e}")
    st.stop()

st.balloons()
st.header("🎉 ΟΛΑ ΤΑ ΒΗΜΑΤΑ ΠΕΡΑΣΑΝ!")
st.info("Αν βλέπεις αυτό το μήνυμα, όλα τα βαριά κομμάτια δουλεύουν. "
        "Το πρόβλημα είναι αλλού στον κώδικα.")
