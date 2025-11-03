from typing import Callable

import streamlit as st


def render(on_upload: Callable, on_proceed: Callable[[], None]) -> None:
    st.subheader("2️⃣ KYC Upload")
    st.caption("Securely share your document so we can verify your identity.")

    uploaded_file = st.file_uploader(
        "Upload your ID document",
        type=["png", "jpg", "jpeg", "pdf"],
        accept_multiple_files=False,
        help="Accepted formats: PNG, JPG, or PDF.",
    )

    kyc_status = (st.session_state.get("kyc_status") or "").lower()
    upload_clicked = st.button(
        "Upload Document",
        use_container_width=True,
        disabled=kyc_status in {"uploaded", "verified"},
    )

    if upload_clicked:
        if not uploaded_file:
            st.warning("Please choose a file before uploading.")
        else:
            with st.spinner("Uploading to verification agent..."):
                on_upload(uploaded_file)

    response = st.session_state.get("kyc_upload_response")
    if response:
        st.success("Document Uploaded ✅")
        if message := response.get("message"):
            st.write(message)

    proceed_disabled = not response
    if st.button(
        "Proceed to Product Advisor",
        type="primary",
        use_container_width=True,
        disabled=proceed_disabled,
    ):
        if proceed_disabled:
            st.info("Upload your KYC document to move forward.")
        else:
            on_proceed()
