from typing import Callable

import streamlit as st


def render(on_start: Callable[[str], None]) -> None:
    st.subheader("1️⃣ Start Onboarding")
    st.caption("Kick things off so the crew can tailor your journey.")

    st.text_input(
        "Email or User ID",
        key="user_id",
        placeholder="e.g. alex.lee@example.com",
        help="We use this to link your onboarding task across agents.",
    )

    start_clicked = st.button(
        "Start Onboarding",
        type="primary",
        use_container_width=True,
    )

    if start_clicked:
        user_id = st.session_state.get("user_id", "").strip()
        if not user_id:
            st.warning("Please provide an email or ID to get started.")
            return
        on_start(user_id)
