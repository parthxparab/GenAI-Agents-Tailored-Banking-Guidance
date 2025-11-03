from __future__ import annotations

import time
from typing import Dict, List

import requests
import streamlit as st

from components import advisor_chat, kyc_upload, onboarding, progress_tracker, results_summary
from utils import api_client, state_manager
from utils.api_client import APIClientError

st.set_page_config(
    page_title="BankBot Crew — Smart Onboarding Assistant",
    page_icon="🏦",
    layout="wide",
)

st.markdown(
    """
    <style>
        .stApp {
            background-color: #f8f9fa;
        }
        .reportview-container .markdown-text-container {
            font-size: 0.95rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def handle_start(user_identifier: str) -> None:
    state_manager.ensure_state_defaults()
    with st.spinner("Connecting to the onboarding orchestrator..."):
        try:
            response = api_client.start_onboarding(user_identifier)
        except (requests.RequestException, APIClientError) as exc:
            st.error(f"Unable to start onboarding right now. ({exc})")
            return
    task_id = response.get("task_id") or user_identifier
    st.session_state["task_id"] = task_id
    st.session_state["start_message"] = response.get("message", "Onboarding started.")
    state_manager.set_step("kyc")


def handle_kyc_upload(file_obj) -> None:
    state_manager.ensure_state_defaults()
    task_id = st.session_state.get("task_id")
    user_identifier = st.session_state.get("user_id")
    primary_id = user_identifier or task_id
    if not primary_id:
        st.warning("Please start onboarding before uploading your document.")
        return

    with st.spinner("Sending your document to the KYC agent..."):
        try:
            # Ensure the task_id follows the upload so the orchestrator can correlate documents.
            response = api_client.upload_kyc(primary_id, file_obj, task_id=task_id)
        except (requests.RequestException, APIClientError) as exc:
            st.error(f"We hit a snag while uploading the document. ({exc})")
            return
    st.session_state["kyc_upload_response"] = response
    st.session_state["kyc_status"] = response.get("status", "uploaded").capitalize()


def handle_proceed_to_advisor() -> None:
    state_manager.set_step("advisor")


def handle_advice_prompt(prompt: str) -> None:
    state_manager.ensure_state_defaults()
    chat_history: List[Dict[str, str]] = st.session_state.get("chat_history", [])
    chat_history.append({"role": "user", "content": prompt})
    st.session_state["chat_history"] = chat_history

    task_id = st.session_state.get("task_id") or st.session_state.get("user_id")
    if not task_id:
        st.warning("Start onboarding to chat with the advisor.")
        return

    with st.spinner("Advisor is analysing your profile..."):
        try:
            response = api_client.get_advice(task_id, prompt)
        except (requests.RequestException, APIClientError) as exc:
            chat_history.append(
                {
                    "role": "assistant",
                    "content": "I'm unable to fetch advice right now. Please try again shortly.",
                }
            )
            st.error(f"Advisor service is unavailable. ({exc})")
            return

    advice = response.get("advice") or "Here's what I recommend based on your profile."
    chat_history.append({"role": "assistant", "content": advice})
    st.session_state["chat_history"] = chat_history
    st.session_state["recommended_products"] = [
        {"name": "Tailored Advisor Recommendation", "summary": advice}
    ]


def handle_support_prompt(question: str) -> None:
    state_manager.ensure_state_defaults()
    st.session_state["support_prompt"] = ""
    task_id = st.session_state.get("task_id") or st.session_state.get("user_id")
    if not task_id:
        st.warning("Start onboarding to reach the support agent.")
        return

    with st.spinner("Checking in with the support agent..."):
        try:
            response = api_client.support_query(task_id, question)
        except (requests.RequestException, APIClientError) as exc:
            st.error(f"Support agent is unavailable. ({exc})")
            return

    answer = response.get("answer") or "We're working on your request and will update you soon."
    history = st.session_state.get("support_history", [])
    history.insert(0, {"question": question, "answer": answer})
    st.session_state["support_history"] = history


def handle_finalize() -> None:
    state_manager.set_step("audit")
    with st.spinner("Running compliance checks..."):
        time.sleep(1.0)
    state_manager.mark_audit_complete("Automated audit complete — no outstanding actions.")
    if not st.session_state.get("kyc_status"):
        st.session_state["kyc_status"] = "Verified"
    if not st.session_state.get("recommended_products"):
        st.session_state["recommended_products"] = [
            {
                "name": "SmartSaver Account",
                "summary": "High-yield savings with zero maintenance fees and instant digital onboarding.",
            }
        ]
    state_manager.set_step("results")


def handle_restart() -> None:
    state_manager.reset_state()


def main() -> None:
    state_manager.ensure_state_defaults()

    health_payload = api_client.health_check()
    backend_healthy = bool(health_payload and health_payload.get("status") == "ok")

    current_step = st.session_state.get("step", "start")
    step_statuses = state_manager.get_step_statuses(current_step)
    progress_value = state_manager.get_progress_value(current_step)

    progress_tracker.render_sidebar(
        step_labels=state_manager.STEP_LABELS,
        step_statuses=step_statuses,
        progress_value=progress_value,
        backend_healthy=backend_healthy,
    )

    st.title("🏦 BankBot Crew — Smart Onboarding Assistant")
    st.write("A multi-agent journey that guides you from signup to tailored product recommendations.")

    task_id = st.session_state.get("task_id")
    if task_id:
        st.caption(f"Active Task ID: `{task_id}`")

    step = st.session_state.get("step", "start")

    with st.container():
        if step == "start":
            onboarding.render(handle_start)
        elif step == "kyc":
            if message := st.session_state.get("start_message"):
                st.success(message)
            kyc_upload.render(handle_kyc_upload, handle_proceed_to_advisor)
        elif step == "advisor":
            advisor_chat.render(
                chat_history=st.session_state.get("chat_history", []),
                support_history=st.session_state.get("support_history", []),
                on_user_prompt=handle_advice_prompt,
                on_support_prompt=handle_support_prompt,
                on_finalize=handle_finalize,
            )
        elif step == "results":
            results_summary.render(
                kyc_status=st.session_state.get("kyc_status", "Verified"),
                recommended_products=st.session_state.get("recommended_products", []),
                audit_note=st.session_state.get("audit_note", ""),
                on_restart=handle_restart,
            )
        else:
            st.info("Let’s continue your onboarding journey.")


if __name__ == "__main__":
    main()
