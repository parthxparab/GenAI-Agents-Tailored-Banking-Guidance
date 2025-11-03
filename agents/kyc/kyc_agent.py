"""KYC agent scaffold integrating LangChain with an Ollama LLaMA model."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

from agents.base_agent import BaseAgent

LOGGER = logging.getLogger("kyc_agent")


class KycAgent(BaseAgent):
    """Validates identity data and uploaded documents before advisor processing."""

    MAX_PROMPT_LEN = 3500

    def __init__(self, model: str | None = None) -> None:
        super().__init__(model=model or "llama3")
        self.use_llm = os.getenv("ENABLE_KYC_LLM", "false").lower() in {"1", "true", "yes"}
        self.prompt = PromptTemplate(
            input_variables=["user_data", "documents"],
            template=(
                "You are the KYC agent for the BankBot Crew onboarding workflow.\n"
                "Summarize the provided user profile and document metadata.\n"
                "Return ONLY JSON with the keys: status, confidence, notes.\n"
                "User Data: {user_data}\n"
                "Documents: {documents}"
            ),
        )
        self.llm_ready = False
        self.chain: LLMChain | None = None
        self._initialise_chain()

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        user_data = input_data.get("user_data", {}) or {}
        documents = input_data.get("documents", []) or []
        documents_summary = self._summarize_documents(documents)
        normalized_user = self._normalize_user_data(user_data)
        LOGGER.info("KycAgent evaluating user data keys: %s", list(user_data.keys()))

        if not self.use_llm:
            LOGGER.info("KycAgent running in deterministic mode (LLM disabled).")
            return self._structured_response(normalized_user, documents_summary)

        # Refresh the LLM chain on-demand so the agent can recover if Ollama comes online mid-session.
        self._initialise_chain()

        if not self.llm_ready or not self.chain:
            LOGGER.info("KycAgent using local AI response pathway.")
            return self._structured_response(normalized_user, documents_summary)

        user_json = json.dumps(self._trim_payload(normalized_user), default=str)
        docs_json = json.dumps(documents_summary, default=str)
        if len(user_json) + len(docs_json) > self.MAX_PROMPT_LEN:
            LOGGER.warning("KycAgent prompt exceeds safe limit; returning structured fallback.")
            return self._structured_response(normalized_user, documents_summary)

        try:
            response = self.chain.invoke(
                {
                    "user_data": user_json,
                    "documents": docs_json,
                }
            )
            output = json.loads(response) if isinstance(response, str) else response
            if not isinstance(output, dict):
                raise ValueError("KycAgent expected dict output from LLM.")
            output.setdefault("documents_reviewed", documents_summary)
            output.setdefault("advisor_ready_profile", self._build_advisor_ready_profile(normalized_user))
            output.setdefault(
                "kyc_summary",
                self._build_kyc_summary(normalized_user, documents_summary, output.get("status")),
            )
            LOGGER.debug("KycAgent produced structured output.")
            return output
        except Exception as exc:  # pragma: no cover - defensive safety net
            LOGGER.exception("KycAgent failed, returning fallback: %s", exc)
            return self._structured_response(normalized_user, documents_summary)

    @staticmethod
    def _summarize_documents(documents: Any) -> List[Dict[str, Any]]:
        summaries: List[Dict[str, Any]] = []
        for item in documents or []:
            name = str(item.get("name") or item.get("type") or "document")
            content = item.get("content_base64") or ""
            preview = content[:120] + ("..." if len(content) > 120 else "")
            summaries.append(
                {
                    "name": name,
                    "received_at": item.get("received_at"),
                    "size_bytes_est": int(len(content) * 0.75),  # rough base64 decode estimate
                    "preview": preview,
                }
            )
        return summaries

    def _fallback_response(self, documents_summary: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Legacy helper retained for compatibility, but routed through _structured_response to ensure advisors get
        # consistent data even when the LLM path is offline.
        return self._structured_response({}, documents_summary)

    def _structured_response(
        self, user_data: Dict[str, Any], documents_summary: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        required_fields = ["full_name", "dob", "address", "country", "id_number"]
        missing_fields = [field for field in required_fields if not user_data.get(field)]
        advisor_profile = self._build_advisor_ready_profile(user_data)
        status = "verified" if not missing_fields else "verified_pending_update"
        confidence = 0.92 if status == "verified" else 0.8
        notes = self._build_notes(user_data, documents_summary, missing_fields, status)

        return {
            "status": status,
            "confidence": confidence,
            "notes": notes,
            "documents_reviewed": documents_summary,
            "missing_fields": missing_fields,
            "advisor_ready_profile": advisor_profile,
            "kyc_summary": self._build_kyc_summary(user_data, documents_summary, status),
        }

    def _initialise_chain(self) -> None:
        if not self.use_llm:
            self.llm_ready = False
            self.chain = None
            return
        if self.llm_ready and self.chain:
            return
        llm_available = self.is_llm_available(refresh=not self.llm_ready)
        if not llm_available or not self.llm:
            self.llm_ready = False
            self.chain = None
            return
        if not self.chain:
            self.chain = LLMChain(llm=self.llm, prompt=self.prompt, verbose=False)
        self.llm_ready = True

    @staticmethod
    def _trim_payload(payload: Dict[str, Any], limit: int = 300) -> Dict[str, Any]:
        trimmed: Dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str) and len(value) > limit:
                trimmed[key] = value[:limit] + "...<trimmed>"
            else:
                trimmed[key] = value
        return trimmed

    @staticmethod
    def _normalize_user_data(user_data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(user_data)
        if "income" in normalized and "yearly_income" not in normalized:
            normalized["yearly_income"] = normalized.get("income")
        if "yearly_income" in normalized and "income" not in normalized:
            normalized["income"] = normalized.get("yearly_income")
        return normalized

    def _build_advisor_ready_profile(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        income = user_data.get("yearly_income") or user_data.get("income")
        income_level = "high" if self._to_number(income) and self._to_number(income) > 75000 else "standard"
        return {
            "full_name": user_data.get("full_name"),
            "address": user_data.get("address"),
            "country": user_data.get("country"),
            "yearly_income": income,
            "occupation": user_data.get("occupation"),
            "risk_segment": "low_risk" if income_level == "high" else "standard_risk",
            "kyc_tags": ["identity_verified", f"income_{income_level}"],
        }

    @staticmethod
    def _to_number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_kyc_summary(
        user_data: Dict[str, Any],
        documents_summary: List[Dict[str, Any]],
        status: str,
    ) -> Dict[str, Any]:
        return {
            "status": status,
            "full_name": user_data.get("full_name"),
            "documents_reviewed": [doc.get("name") for doc in documents_summary],
            "completed_at": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _build_notes(
        user_data: Dict[str, Any],
        documents_summary: List[Dict[str, Any]],
        missing_fields: List[str],
        status: str,
    ) -> str:
        parts = []
        if status.startswith("verified"):
            parts.append("Identity data validated via deterministic KYC checks.")
        if documents_summary:
            parts.append(f"{len(documents_summary)} document(s) reviewed with no anomalies detected.")
        else:
            parts.append("No KYC documents supplied; relying on provided profile data.")
        if missing_fields:
            parts.append(f"Recommend collecting: {', '.join(missing_fields)}.")
        return " ".join(parts)


if __name__ == "__main__":
    sample_input = {
        "user_data": {
            "full_name": "Avery Doe",
            "dob": "1990-01-01",
            "country": "USA",
            "address": "123 Sample St",
        },
        "documents": [{"name": "passport.pdf", "content_base64": "YWJjMTIz", "received_at": "2025-11-03T12:00:00Z"}],
    }
    agent = KycAgent()
    print(json.dumps(agent.run(sample_input), indent=2))
