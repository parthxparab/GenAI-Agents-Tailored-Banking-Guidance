"""KYC agent scaffold integrating LangChain with an Ollama LLaMA model."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

from agents.base_agent import BaseAgent

LOGGER = logging.getLogger("kyc_agent")


class KycAgent(BaseAgent):
    """Validates identity data and uploaded documents before advisor processing."""

    def __init__(self, model: str | None = None) -> None:
        super().__init__(model=model or "llama3")
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
        user_data = input_data.get("user_data", {})
        documents = input_data.get("documents", [])
        documents_summary = self._summarize_documents(documents)
        LOGGER.info("KycAgent evaluating user data keys: %s", list(user_data.keys()))

        # Refresh the LLM chain on-demand so the agent can recover if Ollama comes online mid-session.
        self._initialise_chain()

        if not self.llm_ready or not self.chain:
            LOGGER.info("KycAgent using fallback response pathway.")
            return self._fallback_response(documents_summary)

        try:
            response = self.chain.invoke(
                {
                    "user_data": json.dumps(user_data, default=str),
                    "documents": json.dumps(documents_summary, default=str),
                }
            )
            output = json.loads(response) if isinstance(response, str) else response
            if not isinstance(output, dict):
                raise ValueError("KycAgent expected dict output from LLM.")
            output.setdefault("documents_reviewed", documents_summary)
            LOGGER.debug("KycAgent produced structured output.")
            return output
        except Exception as exc:  # pragma: no cover - defensive safety net
            LOGGER.exception("KycAgent failed, returning fallback: %s", exc)
            return self._fallback_response(documents_summary)

    @staticmethod
    def _summarize_documents(documents: Any) -> list[Dict[str, Any]]:
        summaries = []
        for item in documents or []:
            name = str(item.get("name") or "document")
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

    @staticmethod
    def _fallback_response(documents_summary: list[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "status": "manual_review",
            "confidence": 0.0,
            "notes": "KYC placeholder response while identity validation services are starting up.",
            "documents_reviewed": documents_summary,
        }

    def _initialise_chain(self) -> None:
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


if __name__ == "__main__":
    sample_input = {
        "user_data": {"full_name": "Avery Doe", "dob": "1990-01-01", "country": "USA"},
        "documents": [{"type": "passport", "reference": "sample-passport-id"}],
    }
    agent = KycAgent()
    print(json.dumps(agent.run(sample_input), indent=2))
