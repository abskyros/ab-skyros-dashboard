"""
ui/mobile.py — Η εφαρμογή στο κινητό.

Τι κάνει:
  • Βάζει το εικονίδιο ΑΒ ώστε να μπαίνει στην αρχική οθόνη σαν κανονική εφαρμογή
  • Κόκκινη μπάρα κατάστασης (status bar) στο iPhone
  • Κρύβει τη γραμμή διεύθυνσης του Safari όταν ανοίγει από την αρχική οθόνη

ΓΙΑΤΙ ΕΤΣΙ ΚΑΙ ΟΧΙ ΜΕ ΑΡΧΕΙΟ manifest.json:

Το Streamlit Cloud δεν σερβίρει στατικά αρχεία από φάκελο (χωρίς ρύθμιση που
δεν ελέγχουμε). Άρα το manifest και τα εικονίδια μπαίνουν ως data URI —
ενσωματωμένα μέσα στη σελίδα. Δουλεύει παντού, χωρίς εξαρτήσεις.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import streamlit as st

STATIC = Path(__file__).parent.parent / "static"

APP_NAME = "ΑΒ Σκύρος"
THEME = "#1E3A8A"


def _data_uri(filename: str) -> str | None:
    """Εικονίδιο → data URI. Δεν χρειάζεται server να το σερβίρει."""
    path = STATIC / filename
    if not path.exists():
        return None
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@st.cache_data(show_spinner=False)
def _head_html() -> str:
    """
    Χτίζεται μία φορά. Τα εικονίδια είναι ~30 KB — δεν θέλουμε να τα
    ξανακωδικοποιούμε σε κάθε rerun.
    """
    icons = {
        size: _data_uri(f"icon-{size}.png")
        for size in (32, 180, 192, 512)
    }
    maskable = _data_uri("icon-maskable-512.png")

    if not icons.get(180):
        return ""  # τα εικονίδια λείπουν — δεν σπάμε τίποτα

    manifest = {
        "name": APP_NAME,
        "short_name": "ΑΒ",
        "start_url": ".",
        "display": "standalone",
        "background_color": "#F6F7F9",
        "theme_color": THEME,
        "orientation": "portrait",
        "icons": [
            {"src": icons[192], "sizes": "192x192", "type": "image/png"},
            {"src": icons[512], "sizes": "512x512", "type": "image/png"},
            {"src": maskable or icons[512], "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }

    manifest_uri = "data:application/manifest+json;base64," + base64.b64encode(
        json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")

    return f"""
<link rel="manifest" href="{manifest_uri}">
<link rel="apple-touch-icon" sizes="180x180" href="{icons[180]}">
<link rel="icon" type="image/png" sizes="32x32" href="{icons[32]}">

<meta name="theme-color" content="{THEME}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{APP_NAME}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1">
"""


def setup() -> None:
    """
    Καλείται μία φορά, στην αρχή.

    Το Streamlit τρέχει σε iframe, οπότε τα <link> και <meta> πρέπει να μπουν
    στο ΓΟΝΙΚΟ document — αλλιώς το κινητό δεν τα βλέπει. Γι' αυτό το JS.
    """
    head = _head_html()
    if not head:
        return

    payload = json.dumps(head)

    st.markdown(
        f"""
<script>
(function() {{
  try {{
    var doc = window.parent && window.parent.document ? window.parent.document : document;

    if (doc.getElementById('ab-pwa')) return;   // ήδη μπήκε

    var slot = doc.createElement('div');
    slot.id = 'ab-pwa';
    slot.style.display = 'none';
    slot.innerHTML = {payload};

    var head = doc.head || doc.getElementsByTagName('head')[0];

    Array.prototype.forEach.call(slot.querySelectorAll('link, meta'), function(el) {{
      head.appendChild(el.cloneNode(true));
    }});

    doc.title = {json.dumps(APP_NAME)};
  }} catch (e) {{
    /* Cross-origin ή άλλο εμπόδιο — δεν πειράζει, η εφαρμογή δουλεύει κανονικά. */
  }}
}})();
</script>
""",
        unsafe_allow_html=True,
    )
