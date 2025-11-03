"""Conversation agent scaffold using a LangChain ConversationChain with Ollama."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

import requests
from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory
from langchain_community.llms import Ollama

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s [ConversationAgent] %(message)s")
LOGGER = logging.getLogger("conversation_agent")


class ConversationAgent:
    """Placeholder conversation agent to gather onboarding details."""

    def __init__(self, model_name: str = None) -> None:
        self.model_name = model_name or os.getenv("CONVERSATION_AGENT_MODEL", "llama3")
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.enable_llm = os.getenv("ENABLE_OLLAMA", "false").lower() in {"1", "true", "yes"}
        self.llm = Ollama(model=self.model_name, base_url=self.base_url) if self.enable_llm else None
        self.memory = ConversationBufferMemory(return_messages=True) if self.enable_llm else None
        self.chain = (
            ConversationChain(llm=self.llm, memory=self.memory, verbose=False) if self.enable_llm and self.llm else None
        )

    def run(self, input_data: Dict[str, Any]) -> str:
        """Engage with the user context and return JSON placeholder output."""
        if self.enable_llm and self.memory:
            self.memory.clear()
        LOGGER.info("Starting conversation agent run with context keys: %s", list(input_data.keys()))
        serialized_context = json.dumps(input_data, default=str)
        prompt = (
            "You are the conversation agent for the BankBot Crew onboarding workflow.\n"
            "Given the prior context, craft a short greeting and list the next information you intend to collect.\n"
            "Respond ONLY with JSON using keys: greeting, requested_information, notes.\n"
            f"Context: {serialized_context}"
        )

        if not self.enable_llm:
            LOGGER.info("LLM disabled for ConversationAgent; returning scripted response.")
            return json.dumps(self._fallback_response())

        if not _is_ollama_available(self.base_url):
            LOGGER.warning("Ollama not reachable; returning fallback conversation response.")
            return json.dumps(self._fallback_response())

        try:
            if not self.chain:
                raise RuntimeError("Conversation chain is not initialised.")
            response = self.chain.predict(input=prompt)
            output = response.strip() if isinstance(response, str) else str(response)
            if not output:
                raise ValueError("Conversation agent returned an empty string.")
            LOGGER.debug("Conversation agent raw response: %s", output)
            return output
        except Exception as exc:  # pragma: no cover - defensive safety net
            LOGGER.exception("Conversation agent failed: %s", exc)
            return json.dumps(self._fallback_response())

    @staticmethod
    def _fallback_response() -> Dict[str, Any]:
        return {
            "greeting": "Hello! I'm here to help with your onboarding.",
            "requested_information": ["full_name", "date_of_birth", "country"],
            "notes": "Placeholder conversation response while the AI service initializes.",
        }


if __name__ == "__main__":
    sample_context = {
        "session_id": "demo-session",
        "recent_messages": [
            {"sender": "user", "content": "Hi, I'm interested in opening an account."},
        ],
    }
    agent = ConversationAgent()
    print(agent.run(sample_context))


def _is_ollama_available(base_url: str) -> bool:
    """Quick health probe for Ollama to avoid blocking when the model is unavailable."""
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=0.5)
        return response.ok
    except requests.RequestException:
        return False
