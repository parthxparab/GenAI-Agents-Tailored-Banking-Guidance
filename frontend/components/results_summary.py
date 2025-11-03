from typing import Callable, Iterable, Mapping

import streamlit as st


def render(
    kyc_status: str,
    recommended_products: Iterable[Mapping[str, str]],
    audit_note: str,
    on_restart: Callable[[], None],
) -> None:
    st.subheader("4️⃣ Results Summary")
    st.success("Onboarding completed — welcome aboard!")

    status_color = (
        "green"
        if kyc_status.lower() == "verified"
        else "orange"
        if kyc_status.lower() == "manual review"
        else "red"
    )
    st.markdown(f"**KYC Status:** :{status_color}[{kyc_status}]")

    if audit_note:
        st.info(audit_note)

    st.markdown("### Recommended Products")
    has_products = False
    for product in recommended_products:
        has_products = True
        name = product.get("name") or product.get("title") or "Personalised Offer"
        summary = product.get("summary") or product.get("description") or ""
        st.write(f"**{name}**")
        if summary:
            st.write(summary)
        if benefits := product.get("benefits"):
            st.write(f"• {benefits}")
        st.caption("— BankBot Product Advisor")

    if not has_products:
        st.write("You'll receive tailored recommendations shortly.")

    st.divider()
    if st.button("Restart Onboarding", use_container_width=True):
        on_restart()
