"""Conversation agent scaffold using a LangChain ConversationChain with Ollama."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory

from agents.base_agent import BaseAgent

LOGGER = logging.getLogger("conversation_agent")


class ConversationAgent(BaseAgent):
    """Collects structured onboarding details from the earlier chat context."""

    def __init__(self, model: str | None = None) -> None:
        super().__init__(model=model or "llama3")
        self.llm_ready = False
        self.memory: ConversationBufferMemory | None = None
        self.chain: ConversationChain | None = None
        self._initialise_chain()

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        LOGGER.info("ConversationAgent invoked with keys: %s", list(input_data.keys()))

        # Refresh chain lazily so the agent can recover if Ollama becomes available mid-run.
        self._initialise_chain()

        if not self.llm_ready or not self.chain:
            LOGGER.info("ConversationAgent using fallback response pathway.")
            return self._fallback_response()

        if self.memory:
            self.memory.clear()

        # Feed orchestrator-provided context into the conversation prompt so downstream
        # agents receive a structured snapshot of the customer's stated intent.
        prompt = (
            "You are the conversation agent for the BankBot Crew onboarding workflow.\n"
            "Given the prior context, craft a short greeting and list the next information you intend to collect.\n"
            "Respond ONLY with JSON using keys: greeting, requested_information, notes.\n"
            f"Context: {json.dumps(input_data, default=str)}"
        )

        try:
            response = self.chain.predict(input=prompt)
            output = json.loads(response) if isinstance(response, str) else response
            if not isinstance(output, dict):
                raise ValueError("ConversationAgent expected dict output from LLM.")
            LOGGER.debug("ConversationAgent produced structured output.")
            return output
        except Exception as exc:  # pragma: no cover - defensive safety net
            LOGGER.exception("ConversationAgent failed, falling back: %s", exc)
            return self._fallback_response()

    @staticmethod
    def _fallback_response() -> Dict[str, Any]:
        return {
            "greeting": "Hello! I'm here to help with your onboarding.",
            "requested_information": ["full_name", "date_of_birth", "country"],
            "notes": "Placeholder conversation response while the AI service initializes.",
        }

    def _initialise_chain(self) -> None:
        if self.llm_ready and self.chain:
            return
        llm_available = self.is_llm_available(refresh=not self.llm_ready)
        if not llm_available or not self.llm:
            self.llm_ready = False
            self.chain = None
            self.memory = None
            return
        if not self.memory:
            self.memory = ConversationBufferMemory(return_messages=True)
        if not self.chain:
            self.chain = ConversationChain(llm=self.llm, memory=self.memory, verbose=False)
        self.llm_ready = True


if __name__ == "__main__":
    sample_context = {
        "session_id": "demo-session",
        "recent_messages": [
            {"sender": "user", "content": "Hi, I'm interested in opening an account."},
        ],
    }
    agent = ConversationAgent()
    print(json.dumps(agent.run(sample_context), indent=2))
