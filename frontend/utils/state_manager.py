from __future__ import annotations

from typing import Dict, List

import streamlit as st

STEP_FLOW: List[str] = ["start", "kyc", "advisor", "audit", "results"]
STEP_LABELS: Dict[str, str] = {
    "start": "Start",
    "kyc": "KYC Upload",
    "advisor": "Product Advice",
    "audit": "Audit",
    "results": "Complete",
}


def ensure_state_defaults() -> None:
    defaults = {
        "step": "start",
        "user_id": "",
        "task_id": "",
        "kyc_status": None,
        "kyc_upload_response": None,
        "chat_history": [],
        "support_history": [],
        "support_prompt": "",
        "recommended_products": [],
        "audit_note": "",
        "audit_complete": False,
        "start_message": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_state() -> None:
    """Reset session state while keeping Streamlit internals untouched."""
    for key in list(st.session_state.keys()):
        if key in {"step", "user_id", "task_id", "kyc_status", "kyc_upload_response",
                   "chat_history", "support_history", "support_prompt", "recommended_products",
                   "audit_note", "audit_complete", "start_message"}:
            del st.session_state[key]
    ensure_state_defaults()


def set_step(step: str) -> None:
    if step in STEP_FLOW:
        st.session_state["step"] = step


def mark_audit_complete(note: str = "Automated audit completed.") -> None:
    st.session_state["audit_complete"] = True
    st.session_state["audit_note"] = note


def get_progress_value(step: str) -> float:
    try:
        index = STEP_FLOW.index(step)
    except ValueError:
        return 0.0
    max_index = len(STEP_FLOW) - 1
    return index / max_index if max_index else 1.0


def get_step_statuses(current_step: str) -> Dict[str, str]:
    statuses: Dict[str, str] = {}
    try:
        current_index = STEP_FLOW.index(current_step)
    except ValueError:
        current_index = 0
    for idx, step in enumerate(STEP_FLOW):
        if idx < current_index:
            statuses[step] = "complete"
        elif idx == current_index:
            statuses[step] = "active"
        else:
            statuses[step] = "pending"
    if st.session_state.get("audit_complete"):
        statuses["audit"] = "complete"
    return statuses
