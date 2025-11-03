from typing import Callable, List, Mapping

import streamlit as st

ChatMessage = Mapping[str, str]


def render(
    chat_history: List[ChatMessage],
    support_history: List[ChatMessage],
    on_user_prompt: Callable[[str], None],
    on_support_prompt: Callable[[str], None],
    on_finalize: Callable[[], None],
) -> None:
    st.subheader("3️⃣ Product Advisor")
    st.caption("Chat with the crew's advisor agent for personalised banking picks.")

    chat_container = st.container()
    with chat_container:
        for message in chat_history:
            role = message.get("role", "assistant")
            content = message.get("content", "")
            with st.chat_message(role):
                st.markdown(content)

    prompt = st.chat_input("Ask about products, rates, or features")
    if prompt:
        on_user_prompt(prompt)

    st.divider()
    st.markdown("**Need help?** Drop a quick support question below.")
    col_support, col_button = st.columns([3, 1])
    with col_support:
        support_prompt = st.text_input(
            "Support question",
            key="support_prompt",
            placeholder="Where can I track my application?",
            label_visibility="collapsed",
        )
    with col_button:
        if st.button("Ask Support", use_container_width=True):
            question = support_prompt.strip()
            if question:
                on_support_prompt(question)
            else:
                st.warning("Please enter a support question.")

    if support_history:
        with st.expander("Recent support answers", expanded=False):
            for entry in support_history:
                st.markdown(f"**You:** {entry.get('question')}")
                st.write(entry.get("answer"))
                st.caption("---")

    st.divider()
    st.info("Ready to wrap things up? We'll run a quick compliance audit.")
    if st.button(
        "Finalize Onboarding",
        type="primary",
        use_container_width=True,
    ):
        on_finalize()
