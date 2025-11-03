"""KYC agent scaffold integrating LangChain with an Ollama LLaMA model."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

import requests
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_community.llms import Ollama

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s [KycAgent] %(message)s")
LOGGER = logging.getLogger("kyc_agent")


class KycAgent:
    """Placeholder KYC agent that prepares a generic verification response."""

    def __init__(self, model_name: str = None) -> None:
        self.model_name = model_name or os.getenv("KYC_AGENT_MODEL", "llama3")
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.enable_llm = os.getenv("ENABLE_OLLAMA", "false").lower() in {"1", "true", "yes"}
        self.llm = Ollama(model=self.model_name, base_url=self.base_url) if self.enable_llm else None
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
        self.chain = LLMChain(llm=self.llm, prompt=self.prompt, verbose=False) if self.enable_llm and self.llm else None

    def run(self, input_data: Dict[str, Any]) -> str:
        """Execute the KYC flow with structured input and return placeholder JSON."""
        user_data = input_data.get("user_data", {})
        documents = input_data.get("documents", [])
        LOGGER.info("Starting KYC evaluation for user data keys: %s", list(user_data.keys()))

        if not self.enable_llm:
            LOGGER.info("LLM disabled for KycAgent; returning scripted response.")
            return json.dumps(self._fallback_response())

        if not _is_ollama_available(self.base_url):
            LOGGER.warning("Ollama not reachable; returning fallback KYC response.")
            return json.dumps(self._fallback_response())

        try:
            if not self.chain:
                raise RuntimeError("KYC chain is not initialised.")
            response = self.chain.invoke(
                {
                    "user_data": json.dumps(user_data, default=str),
                    "documents": json.dumps(documents, default=str),
                }
            )
            output = response.strip() if isinstance(response, str) else str(response)
            if not output:
                raise ValueError("Received empty response from LLM.")
            LOGGER.debug("KYC agent raw response: %s", output)
            return output
        except Exception as exc:  # pragma: no cover - defensive safety net
            LOGGER.exception("KYC agent failed: %s", exc)
            return json.dumps(self._fallback_response())

    @staticmethod
    def _fallback_response() -> Dict[str, Any]:
        return {
            "status": "manual_review",
            "confidence": 0.0,
            "notes": "KYC placeholder response while identity validation services are starting up.",
        }


if __name__ == "__main__":
    sample_input = {
        "user_data": {"full_name": "Avery Doe", "dob": "1990-01-01", "country": "USA"},
        "documents": [{"type": "passport", "reference": "sample-passport-id"}],
    }
    agent = KycAgent()
    print(agent.run(sample_input))


def _is_ollama_available(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=0.5)
        return response.ok
    except requests.RequestException:
        return False
