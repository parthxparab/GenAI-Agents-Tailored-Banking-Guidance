"""Streamlit frontend for the BankBot Crew onboarding workflow.

The app collects basic customer information, calls the FastAPI gateway to launch
the multi-agent CrewAI workflow, polls for status updates, and renders the advisor's
credit-card recommendations so the user can confirm a final selection.

The layout focuses on the required three-step experience:
    1. 🎯 User Information — capture form inputs and uploaded document.
    2. 🧠 AI Recommendations — display the cards returned by the AdvisorAgent.
    3. ✅ Onboarding Complete — acknowledge the confirmed card.
"""

from __future__ import annotations

import base64
import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from streamlit.runtime.uploaded_file_manager import UploadedFile

API_BASE_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
REQUEST_TIMEOUT = int(os.getenv("API_TIMEOUT_SECONDS", 1800))
# Poll every few seconds so UI reflects backend progress promptly.
STATUS_POLL_INTERVAL = float(os.getenv("STATUS_POLL_INTERVAL", 5))
STATUS_POLL_TIMEOUT = int(os.getenv("STATUS_POLL_TIMEOUT", 600))
STAGE_ORDER = ["conversation", "kyc", "advisor", "audit"]

st.set_page_config(page_title="BankBot Crew Onboarding", page_icon="🏦", layout="centered")

QUESTION_DEFINITIONS = [
    (
        "q1_credit_history",
        "Are you looking to build or improve your credit score, or do you already have an established credit history?",
        [
            ("building", "I'm looking to build or improve my credit score"),
            ("established", "I already have an established credit history"),
        ],
    ),
    (
        "q2_payment_style",
        "Do you usually pay off your balance in full each month, or would you prefer a card with a lower interest rate for flexibility?",
        [
            ("full_payment", "I usually pay off my balance in full each month"),
            ("lower_apr", "I'd like a lower interest rate for added flexibility"),
        ],
    ),
    (
        "q3_cashback",
        "Would you like to earn cash back on your everyday spending, like groceries, gas, or dining?",
        [
            ("yes", "Yes, earning cashback would be helpful"),
            ("no", "No, cashback rewards aren't important to me"),
        ],
    ),
    (
        "q4_travel",
        "Do you travel often enough that earning airline miles or travel rewards would be valuable to you?",
        [
            ("yes", "Yes, I'd value travel rewards or airline miles"),
            ("no", "No, I don't need travel-focused rewards"),
        ],
    ),
    (
        "q5_simple_card",
        "Would you prefer something simple with no annual fee, just for convenience and everyday use?",
        [
            ("yes", "Yes, a simple no-fee card sounds ideal"),
            ("no", "No, I'm open to cards with annual fees"),
        ],
    ),
]


def _ensure_state_defaults() -> None:
    """Initialize session_state keys used across the UI."""
    defaults = {
        "session_id": None,
        "session_status": None,
        "status_message": "",
        "progress": {stage: "pending" for stage in STAGE_ORDER},
        "recommendations": [],
        "selected_card": None,
        "confirmation_response": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _encode_document(uploaded_file: Optional["UploadedFile"]) -> Tuple[Optional[str], Optional[str]]:
    """Convert an UploadedFile into base64 payload expected by the gateway."""
    if not uploaded_file:
        return None, None
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    return uploaded_file.name, encoded


def _compute_progress(progress_map: Dict[str, str]) -> int:
    """Convert a stage-status map into a 0-100 integer for the progress bar."""
    weights = {"completed": 1.0, "in_progress": 0.5, "pending": 0.0, "error": 1.0}
    total = 0.0
    for stage in STAGE_ORDER:
        status = progress_map.get(stage, "pending")
        total += weights.get(status, 0.0)
    percentage = int((total / len(STAGE_ORDER)) * 100)
    return max(0, min(100, percentage))


def _render_progress_badges(progress_map: Dict[str, str]) -> None:
    """Display the stage-by-stage progress timeline."""
    status_emojis = {
        "pending": "⏳",
        "in_progress": "🔄",
        "completed": "✅",
        "error": "⚠️",
    }
    cols = st.columns(len(STAGE_ORDER))
    for idx, stage in enumerate(STAGE_ORDER):
        with cols[idx]:
            status = progress_map.get(stage, "pending")
            st.markdown(f"**{status_emojis.get(status, '⏳')} {stage.title()}**")
            st.caption(status.replace("_", " ").title())


def start_onboarding(form_values: Dict[str, Any]) -> Optional[str]:
    """Call POST /onboard and store the resulting session in Streamlit state."""
    endpoint = f"{API_BASE_URL.rstrip('/')}/onboard"
    try:
        response = requests.post(endpoint, json=form_values, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        st.error(f"Unable to reach the onboarding gateway: {exc}")
        return None

    if response.status_code not in (200, 202):
        st.error(f"Gateway returned {response.status_code}: {response.text}")
        return None

    payload = response.json()
    session_id = payload.get("session_id")
    if not session_id:
        st.error("Gateway response did not include a session identifier.")
        return None

    st.session_state["session_id"] = session_id
    st.session_state["session_status"] = payload.get("status")
    st.session_state["status_message"] = payload.get("message", "")
    return session_id


def poll_status_until_terminal(session_id: str) -> Optional[Dict[str, Any]]:
    """Poll GET /status until the workflow completes, fails, or times out."""
    endpoint = f"{API_BASE_URL.rstrip('/')}/status/{session_id}"
    status_placeholder = st.empty()
    progress_bar = st.progress(0, text="Starting orchestration…")
    timeline_placeholder = st.empty()
    start_time = time.time()

    while time.time() - start_time < STATUS_POLL_TIMEOUT:
        try:
            response = requests.get(endpoint, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            st.error(f"Error contacting status endpoint: {exc}")
            return None

        if response.status_code == 404:
            st.error("The session could not be found. Please start again.")
            return None

        payload = response.json()
        st.session_state["session_status"] = payload.get("status")
        st.session_state["status_message"] = payload.get("message", "")
        st.session_state["progress"] = payload.get("progress", st.session_state["progress"])

        percentage = _compute_progress(st.session_state["progress"])
        progress_bar.progress(percentage, text=f"Workflow status: {st.session_state['session_status']}")
        status_placeholder.info(f"{st.session_state['status_message']} (updated {payload.get('updated_at')})")
        with timeline_placeholder.container():
            _render_progress_badges(st.session_state["progress"])

        if st.session_state["session_status"] in {"completed", "failed"}:
            return payload

        time.sleep(STATUS_POLL_INTERVAL)

    status_placeholder.warning("Polling timed out before the workflow completed.")
    return None


def fetch_recommendations(session_id: str) -> List[Dict[str, Any]]:
    """Retrieve advisor recommendations for a completed session."""
    endpoint = f"{API_BASE_URL.rstrip('/')}/recommendations/{session_id}"
    try:
        response = requests.get(endpoint, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        st.error(f"Unable to fetch recommendations: {exc}")
        return []

    if response.status_code == 202:
        st.warning("Recommendations are not ready yet. Please wait a moment and try again.")
        return []
    if response.status_code >= 400:
        st.error(f"Error fetching recommendations ({response.status_code}): {response.text}")
        return []

    payload = response.json()
    recommendations = payload.get("recommendations") or []
    st.session_state["recommendations"] = recommendations
    return recommendations


def confirm_selection(session_id: str, card_name: str, notes: Optional[str]) -> Optional[Dict[str, Any]]:
    """Send POST /confirm with the selected card."""
    endpoint = f"{API_BASE_URL.rstrip('/')}/confirm/{session_id}"
    body = {"selected_card": card_name, "notes": notes}

    try:
        response = requests.post(endpoint, json=body, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        st.error(f"Unable to confirm selection: {exc}")
        return None

    if response.status_code >= 400:
        st.error(f"Confirmation failed ({response.status_code}): {response.text}")
        return None

    payload = response.json()
    st.session_state["confirmation_response"] = payload
    return payload


def render_recommendation_grid(recommendations: List[Dict[str, Any]]) -> None:
    """Render advisor recommendations using Streamlit columns."""
    if not recommendations:
        st.info("No recommendations available yet.")
        return

    st.header("🧠 AI Recommendations")
    chunk_size = 2
    for idx in range(0, len(recommendations), chunk_size):
        cols = st.columns(chunk_size)
        for offset, card in enumerate(recommendations[idx : idx + chunk_size]):
            column = cols[offset]
            with column:
                name = card.get("card_name") or card.get("name") or f"Card {idx + offset + 1}"
                st.subheader(name)
                summary = card.get("summary") or card.get("description")
                reason = card.get("why_recommended")
                if summary:
                    st.write(summary)
                if reason:
                    st.markdown(f"**Why recommended:** {reason}")
                info_pairs = [
                    ("Annual Fee", card.get("annual_fee")),
                    ("Interest Rate", card.get("interest_rate")),
                    ("Rewards", card.get("rewards")),
                    ("Requirements", card.get("requirements")),
                ]
                details = [f"- **{label}:** {value}" for label, value in info_pairs if value]
                if details:
                    st.caption("\n".join(details))


def render_confirmation_section(session_id: str, recommendations: List[Dict[str, Any]]) -> None:
    """Allow the user to select and confirm a recommendation."""
    if not recommendations:
        return

    card_names = [card.get("card_name") or card.get("name") or f"Card {idx + 1}" for idx, card in enumerate(recommendations)]
    st.session_state["selected_card"] = st.radio(
        "Select the card that best fits your needs:",
        card_names,
        index=0 if card_names else None,
        key="card_selection_radio",
    )
    notes = st.text_area("Optional notes for the banker (visible to the audit trail):", key="confirmation_notes")

    if st.button("Confirm Selection ✅"):
        with st.spinner("Submitting your confirmation..."):
            payload = confirm_selection(session_id, st.session_state["selected_card"], notes or None)
        if payload:
            st.success(f"Onboarding complete! You chose **{payload.get('selected_card')}**.")
            st.session_state["session_status"] = payload.get("status")
            st.session_state["status_message"] = payload.get("message")


def render_completion_summary() -> None:
    """Display final confirmation details."""
    response = st.session_state.get("confirmation_response")
    if not response:
        return

    st.header("✅ Onboarding Complete")
    st.success(
        f"Your selection `{response.get('selected_card')}` has been recorded. "
        "Our team will follow up shortly to finalize your account."
    )
    if notes := response.get("notes"):
        st.caption(f"Notes sent to the audit trail: {notes}")


def main() -> None:
    """Entry point for the Streamlit app."""
    _ensure_state_defaults()

    st.title("🏦 BankBot Crew — Tailored Credit Card Guidance")
    st.write(
        "Kick off the AI-assisted onboarding journey, review curated credit card options, "
        "and confirm the product that fits your lifestyle."
    )

    st.header("🎯 User Information")
    with st.form("onboarding_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Full Name", placeholder="Alex Morgan")
            income = st.number_input("Annual Income (USD)", min_value=0.0, step=1000.0, format="%.2f")
            occupation = st.text_input("Occupation", placeholder="Product Manager")
        with col2:
            email = st.text_input("Work Email", placeholder="alex@example.com")
            document = st.file_uploader("Upload KYC Document (PDF/Image)", type=["pdf", "png", "jpg", "jpeg"])

        st.markdown("### 🧭 Smart Goal-Based Credit Card Questions")
        question_answers: Dict[str, str] = {}
        for key, prompt, options in QUESTION_DEFINITIONS:
            option_values = [value for value, _ in options]
            labels = {value: label for value, label in options}
            question_answers[key] = st.radio(
                prompt,
                options=option_values,
                index=0,
                format_func=lambda opt, labels=labels: labels[opt],
                key=f"question_{key}",
            )

        submitted = st.form_submit_button("Start Onboarding 🚀")

    if submitted:
        if not all([name, email, occupation]) or income <= 0:
            st.error("Please fill in the required fields (name, email, income, occupation).")
        else:
            document_name, document_payload = _encode_document(document)
            payload = {
                "name": name,
                "email": email,
                "income": income,
                "occupation": occupation,
                "questionnaire": question_answers,
                "document_name": document_name,
                "document_content": document_payload,
            }
            with st.spinner("Contacting the gateway to start your onboarding journey..."):
                session_id = start_onboarding(payload)
            if session_id:
                status_payload = poll_status_until_terminal(session_id)
                if status_payload and st.session_state["session_status"] == "completed":
                    with st.spinner("Fetching advisor recommendations..."):
                        fetch_recommendations(session_id)

    if st.session_state.get("session_status") in {"completed", "confirmed"}:
        render_recommendation_grid(st.session_state.get("recommendations", []))
        if st.session_state.get("session_status") == "completed":
            render_confirmation_section(st.session_state["session_id"], st.session_state.get("recommendations", []))
        render_completion_summary()
    elif st.session_state.get("session_status") == "failed":
        st.error(
            "The AI workflow encountered an issue. Please adjust the input data or retry once the service is available."
        )

    if st.session_state.get("confirmation_response"):
        if st.button("Start a New Onboarding Session 🔁"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            _ensure_state_defaults()


if __name__ == "__main__":
    main()
