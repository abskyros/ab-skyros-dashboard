"""
views/suppliers.py — Προμηθευτές: πρόγραμμα παραγγελιών/παραδόσεων.

Δείχνει ποιον προμηθευτή πρέπει να παραγγείλεις ΣΗΜΕΡΑ, με τα στοιχεία
επικοινωνίας του, και αφήνει να καταχωρείς νέους προμηθευτές ή αλλαγές στο
πρόγραμμά τους (π.χ. άλλαξε μέρα παράδοσης) — απευθείας στο Google Sheet.

┌────────────────────────────────────────────────────────────────────────────┐
│ ΓΙΑΤΙ Η ΦΟΡΜΑ, ΟΧΙ ΑΡΧΕΙΟ ΣΤΟΝ ΚΩΔΙΚΑ                                       │
│                                                                            │
│ Ονόματα, email και τηλέφωνα συνεργατών είναι προσωπικά στοιχεία. Δεν      │
│ μπαίνουν ποτέ μέσα σε πηγαίο κώδικα υπό git — μπαίνουν μόνιμα στο          │
│ ιστορικό. Η θέση τους είναι το Google Sheet, και ο μόνος δρόμος προς τα    │
│ εκεί είναι αυτή η φόρμα.                                                   │
└────────────────────────────────────────────────────────────────────────────┘

ΚΑΝΟΝΑΣ: καμία ενημέρωση δεν αντικαθιστά την προηγούμενη. Κάθε αλλαγή μπαίνει
σαν ΝΕΑ γραμμή με ημερομηνία ισχύος (effective_from). Το «τρέχον» πρόγραμμα
είναι πάντα η πιο πρόσφατη ήδη ισχύουσα γραμμή — βλ. core/sheets.py.
"""

import html as _html
from datetime import date

import pandas as pd
import streamlit as st

from core.config import DAYS_GR
from core.metrics import day_name
from core.sheets import (
    current_suppliers, load_suppliers, add_supplier_update,
    current_order_schedule, load_order_schedule,
)
from ui import components as c


def render(today: date) -> None:
    suppliers = current_suppliers()
    schedule = current_order_schedule()

    _today_actions(suppliers, schedule, today)
    _suppliers_section(suppliers)
    _schedule_section(schedule)


# ══════════════════════════════════════════════════════════════════════════════
# ΣΗΜΕΡΑ
# ══════════════════════════════════════════════════════════════════════════════
def _today_actions(suppliers: pd.DataFrame, schedule: pd.DataFrame, today: date) -> None:
    c.section(f"Σήμερα · {day_name(today)}")

    todays_suppliers = _matching_today(suppliers, "order_days", today)
    todays_categories = _matching_today(schedule, "order_days", today)

    if todays_suppliers.empty and todays_categories.empty:
        c.note("Καμία παραγγελία δεν πρέπει να φύγει σήμερα.", "ok")
        return

    for _, r in todays_suppliers.iterrows():
        deadline = f' έως {_esc(r.get("order_deadline"))}' if r.get("order_deadline") else ""
        method = str(r.get("order_method") or "email")
        contact = r.get("phone") if method == "phone" else r.get("email")
        notes_html = (
            f'<br><span style="color:var(--muted);font-size:.85em">{_esc(r.get("notes"))}</span>'
            if r.get("notes") else ""
        )
        c.note(
            f'<b>{_esc(r["supplier"])}</b>{deadline} — {_esc(method)}: {_esc(contact)}{notes_html}',
            "warn",
        )

    for _, r in todays_categories.iterrows():
        c.note(
            f'<b>{_esc(r["category"])}</b> — εσωτερική παραγγελία ΑΒ '
            f'(αποθήκη {_esc(r.get("warehouse_code"))})',
            "info",
        )


def _matching_today(df: pd.DataFrame, col: str, today: date) -> pd.DataFrame:
    if df.empty or col not in df.columns:
        return df.iloc[0:0]
    name = day_name(today)
    mask = df[col].fillna("").apply(lambda cell: name in [d.strip() for d in cell.split(",") if d.strip()])
    return df[mask]


def _esc(v) -> str:
    return _html.escape(str(v)) if v else ""


# ══════════════════════════════════════════════════════════════════════════════
# ΠΡΟΜΗΘΕΥΤΕΣ
# ══════════════════════════════════════════════════════════════════════════════
def _suppliers_section(suppliers: pd.DataFrame) -> None:
    c.spacer(1.2)
    c.section("Προμηθευτές")

    if suppliers.empty:
        c.empty(
            "Δεν υπάρχουν καταχωρημένοι προμηθευτές ακόμη",
            "Πρόσθεσε τον πρώτο παρακάτω.",
        )
    else:
        view = suppliers[[
            "supplier", "category", "order_days", "order_deadline",
            "delivery_days", "order_method", "email", "phone",
        ]].rename(columns={
            "supplier": "Προμηθευτής", "category": "Κατηγορία",
            "order_days": "Μέρες παραγγελίας", "order_deadline": "Προθεσμία",
            "delivery_days": "Μέρες παράδοσης", "order_method": "Τρόπος",
            "email": "Email", "phone": "Τηλέφωνο",
        })
        st.dataframe(view, hide_index=True, width="stretch")

    with st.expander("➕ Νέος προμηθευτής / ενημέρωση προγράμματος"):
        _supplier_form(suppliers)

    if not suppliers.empty:
        with st.expander("Ιστορικό ενημερώσεων"):
            hist = load_suppliers().sort_values("effective_from", ascending=False)
            st.dataframe(
                hist[["supplier", "order_days", "delivery_days", "effective_from", "source"]],
                hide_index=True, width="stretch",
            )


def _supplier_form(suppliers: pd.DataFrame) -> None:
    st.caption(
        "Μια αλλαγή σε υπάρχοντα προμηθευτή ΔΕΝ σβήνει το παλιό πρόγραμμα — "
        "προστίθεται σαν νέα ενημέρωση, με ημερομηνία από πότε ισχύει."
    )

    existing_names = sorted(suppliers["supplier"].unique()) if not suppliers.empty else []
    choice = st.selectbox(
        "Προμηθευτής", ["— Νέος προμηθευτής —"] + existing_names, key="sup_choice",
    )
    is_new = choice == "— Νέος προμηθευτής —"

    prior = {}
    if not is_new and not suppliers.empty:
        prior = suppliers[suppliers["supplier"] == choice].iloc[0].to_dict()

    with st.form("supplier_form", clear_on_submit=True):
        name = st.text_input("Όνομα προμηθευτή", value="" if is_new else choice)
        category = st.text_input("Κατηγορία / προϊόντα", value=str(prior.get("category", "")))

        col1, col2 = st.columns(2)
        with col1:
            contact_person = st.text_input("Υπεύθυνος επικοινωνίας", value=str(prior.get("contact_person", "")))
            email = st.text_input("Email", value=str(prior.get("email", "")))
        with col2:
            phone = st.text_input("Τηλέφωνο", value=str(prior.get("phone", "")))
            order_method = st.radio(
                "Πώς στέλνεται η παραγγελία", ["email", "phone"],
                index=0 if str(prior.get("order_method", "email")) != "phone" else 1,
                horizontal=True,
            )

        prior_order = [d for d in str(prior.get("order_days", "")).split(",") if d]
        prior_deliv = [d for d in str(prior.get("delivery_days", "")).split(",") if d]

        order_days = st.multiselect("Μέρες παραγγελίας", DAYS_GR, default=prior_order)
        order_deadline = st.text_input(
            "Προθεσμία παραγγελίας (ώρα)", value=str(prior.get("order_deadline", "")),
            placeholder="π.χ. 12:00",
        )
        delivery_days = st.multiselect("Μέρες παράδοσης", DAYS_GR, default=prior_deliv)

        notes = st.text_area("Σημειώσεις", value=str(prior.get("notes", "")))
        effective_from = st.date_input("Ισχύει από", value=date.today())
        source = st.text_input(
            "Πηγή ενημέρωσης", placeholder="π.χ. τηλεφωνική συνεννόηση, email 5/9",
        )

        submitted = st.form_submit_button("Αποθήκευση", type="primary")

    if not submitted:
        return

    if not name.strip():
        c.note("Χρειάζεται όνομα προμηθευτή.", "bad")
        return

    ok = add_supplier_update({
        "supplier": name.strip(),
        "category": category.strip(),
        "contact_person": contact_person.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "order_days": ",".join(d for d in DAYS_GR if d in order_days),
        "order_deadline": order_deadline.strip(),
        "delivery_days": ",".join(d for d in DAYS_GR if d in delivery_days),
        "order_method": order_method,
        "notes": notes.strip(),
        "effective_from": effective_from.strftime("%Y-%m-%d"),
        "source": source.strip() or "χειροκίνητη καταχώρηση dashboard",
    })

    if ok:
        c.note(f"Καταχωρήθηκε η ενημέρωση για «{name}».", "ok")
        st.rerun()
    else:
        c.note("Κάτι πήγε στραβά στην αποθήκευση. Δοκίμασε ξανά.", "bad")


# ══════════════════════════════════════════════════════════════════════════════
# ΠΡΟΓΡΑΜΜΑ ΑΒ ΑΝΑ ΚΑΤΗΓΟΡΙΑ
# ══════════════════════════════════════════════════════════════════════════════
def _schedule_section(schedule: pd.DataFrame) -> None:
    c.spacer(1.2)
    c.section("Πρόγραμμα ΑΒ ανά κατηγορία")

    if schedule.empty:
        c.empty(
            "Δεν υπάρχει καταχωρημένο πρόγραμμα ακόμη",
            "Έρχεται από τα εποχιακά email της ΑΒ (π.χ. «Θερινό πρόγραμμα»).",
        )
        return

    view = schedule[["category", "warehouse_code", "order_days", "delivery_days"]].rename(columns={
        "category": "Κατηγορία", "warehouse_code": "Αποθήκη",
        "order_days": "Μέρες παραγγελίας", "delivery_days": "Μέρες παράδοσης",
    })
    st.dataframe(view, hide_index=True, width="stretch")

    with st.expander("Ιστορικό προγράμματος"):
        hist = load_order_schedule().sort_values("effective_from", ascending=False)
        st.dataframe(
            hist[["category", "order_days", "delivery_days", "effective_from", "source"]],
            hide_index=True, width="stretch",
        )
