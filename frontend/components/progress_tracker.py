from typing import Dict

import streamlit as st

STATUS_ICONS = {
    "complete": "✅",
    "active": "🟢",
    "pending": "⬜️",
}


def render_sidebar(
    step_labels: Dict[str, str],
    step_statuses: Dict[str, str],
    progress_value: float,
    backend_healthy: bool,
) -> None:
    with st.sidebar:
        st.title("🏦 BankBot Crew")
        st.write("Smart Onboarding Assistant")

        health_color = "green" if backend_healthy else "red"
        health_icon = "🟢" if backend_healthy else "🔴"
        st.markdown(
            f"{health_icon} **Backend Status:** :{health_color}[{'Online' if backend_healthy else 'Offline'}]"
        )

        st.progress(progress_value)
        st.caption("Onboarding journey")

        for step, label in step_labels.items():
            status = step_statuses.get(step, "pending")
            icon = STATUS_ICONS.get(status, "⬜️")
            if status == "active":
                st.markdown(f"{icon} **{label}**")
            else:
                st.markdown(f"{icon} {label}")
