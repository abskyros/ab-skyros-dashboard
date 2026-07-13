"""
core/github.py — Ξεκινάει GitHub Actions από την εφαρμογή.

ΓΙΑΤΙ ΥΠΑΡΧΕΙ

Το Streamlit Cloud δεν έχει tesseract/poppler — άρα το OCR των πωλήσεων δεν
τρέχει εκεί. Τρέχει μόνο στο GitHub Actions.

Χωρίς αυτό το αρχείο, όταν ο αυτόματος συγχρονισμός αποτύχει, ο χρήστης δεν έχει
κανέναν τρόπο να το διορθώσει από την εφαρμογή — πρέπει να πάει στο GitHub και να
πατήσει «Run workflow» με το χέρι.

Τώρα το κουμπί «Πωλήσεις» ξεκινάει το workflow. Το OCR τρέχει εκεί που δουλεύει.

ΤΙ ΧΡΕΙΑΖΕΤΑΙ

Ένα Personal Access Token με δικαίωμα `actions: write`, στα Streamlit secrets:

    GITHUB_TOKEN = "ghp_..."
    GITHUB_REPO  = "abskyros/ab-skyros-dashboard"

Αν λείπουν, το κουμπί λέει στον χρήστη να πάει στο GitHub. Δεν σκάει.
"""

from __future__ import annotations

import requests
import streamlit as st


API = "https://api.github.com"
TIMEOUT = 12


def _config() -> tuple[str, str]:
    """→ (token, repo) — κενά αν δεν έχουν οριστεί."""
    try:
        token = st.secrets.get("GITHUB_TOKEN", "")
        repo = st.secrets.get("GITHUB_REPO", "")
        return token, repo
    except Exception:
        return "", ""


def available() -> bool:
    token, repo = _config()
    return bool(token and repo)


def trigger_workflow(filename: str, branch: str = "main") -> tuple[bool, str]:
    """
    Ξεκινάει ένα workflow.

    → (πέτυχε, μήνυμα)

    Το GitHub επιστρέφει 204 (No Content) όταν πετύχει — όχι 200.
    """
    token, repo = _config()

    if not token or not repo:
        return False, (
            "Λείπουν τα <code>GITHUB_TOKEN</code> και <code>GITHUB_REPO</code> "
            "από τα secrets."
        )

    url = f"{API}/repos/{repo}/actions/workflows/{filename}/dispatches"

    try:
        r = requests.post(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": branch},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        return False, f"Δεν έγινε σύνδεση με το GitHub: {e}"

    if r.status_code == 204:
        return True, "Ξεκίνησε."

    if r.status_code == 401:
        return False, "Το GITHUB_TOKEN δεν έγινε δεκτό. Έληξε;"

    if r.status_code == 403:
        return False, (
            "Το token δεν έχει δικαίωμα να τρέξει workflows. "
            "Χρειάζεται <code>actions: write</code>."
        )

    if r.status_code == 404:
        return False, (
            f"Δεν βρέθηκε το workflow <code>{filename}</code> ή το repo "
            f"<code>{repo}</code>."
        )

    return False, f"Το GitHub απάντησε {r.status_code}."


def last_run(filename: str) -> dict | None:
    """
    Η τελευταία εκτέλεση ενός workflow.

    → {"status", "conclusion", "started", "url"} ή None

    Χρήσιμο για να λέμε στον χρήστη «τρέχει τώρα» ή «απέτυχε πριν 10 λεπτά».
    """
    token, repo = _config()
    if not token or not repo:
        return None

    url = f"{API}/repos/{repo}/actions/workflows/{filename}/runs"

    try:
        r = requests.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
            },
            params={"per_page": 1},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None

        runs = r.json().get("workflow_runs", [])
        if not runs:
            return None

        run = runs[0]
        return {
            "status": run.get("status"),          # queued | in_progress | completed
            "conclusion": run.get("conclusion"),  # success | failure | cancelled
            "started": run.get("run_started_at"),
            "url": run.get("html_url"),
        }
    except Exception:
        return None
