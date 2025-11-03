"""Conversation agent that simply normalises incoming payloads for downstream agents."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict

from agents.base_agent import BaseAgent

LOGGER = logging.getLogger("conversation_agent")


class ConversationAgent(BaseAgent):
    """Pass-through agent that forwards the gathered context to KYC and Advisor agents."""

    def __init__(self, model: str | None = None) -> None:
        # Still call BaseAgent for consistency, but this agent no longer relies on the LLM.
        super().__init__(model=model or "llama3")

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        LOGGER.info("ConversationAgent invoked with keys: %s", list(input_data.keys()))
        normalized = self._normalise_payload(input_data)
        LOGGER.debug("ConversationAgent normalised payload with keys: %s", list(normalized.keys()))
        return normalized

    @staticmethod
    def _normalise_payload(payload: Any) -> Dict[str, Any]:
        """Ensure the downstream agents receive a serialisable dict with basic bookkeeping."""
        if isinstance(payload, dict):
            result = dict(payload)
        elif isinstance(payload, str):
            try:
                result = json.loads(payload)
                if not isinstance(result, dict):
                    result = {"raw_input": payload}
            except json.JSONDecodeError:
                result = {"raw_input": payload}
        else:
            result = json.loads(json.dumps(payload, default=str))

        result.setdefault("conversation_timestamp", datetime.utcnow().isoformat())
        result.setdefault("stage", "conversation_pass_through")

        user_profile = result.get("user_profile")
        if user_profile and isinstance(user_profile, dict):
            result["user_profile"] = json.loads(json.dumps(user_profile, default=str))

        if "messages" in result and not isinstance(result.get("messages"), list):
            result["messages"] = [result["messages"]]

        return result


if __name__ == "__main__":
    sample_context = {
        "session_id": "demo-session",
        "user_profile": {
            "name": "Jordan",
            "email": "jordan@example.com",
        },
        "recent_messages": [
            {"sender": "user", "content": "Hi, I'm interested in opening an account."},
        ],
    }
    agent = ConversationAgent()
    print(json.dumps(agent.run(sample_context), indent=2))
