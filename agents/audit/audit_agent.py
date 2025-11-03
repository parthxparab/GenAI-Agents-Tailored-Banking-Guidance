"""Audit agent scaffold that logs activity while using LangChain with Ollama."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_community.llms import Ollama

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s [AuditAgent] %(message)s")
LOGGER = logging.getLogger("audit_agent")


class AuditAgent:
    """Placeholder audit agent that captures an audit trail and summary response."""

    def __init__(self, model_name: str = None, log_dir: str | None = None) -> None:
        self.model_name = model_name or os.getenv("AUDIT_AGENT_MODEL", "llama3")
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.enable_llm = os.getenv("ENABLE_OLLAMA", "false").lower() in {"1", "true", "yes"}
        configured_dir = log_dir or os.getenv("AUDIT_LOG_DIR")
        default_dir = Path(__file__).resolve().parents[2] / "audit_logs"
        self.log_dir = Path(configured_dir) if configured_dir else default_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.llm = Ollama(model=self.model_name, base_url=self.base_url) if self.enable_llm else None
        self.prompt = PromptTemplate(
            input_variables=["session_data"],
            template=(
                "You are the audit agent for the BankBot Crew workflow.\n"
                "Review the JSON session data and craft a brief summary.\n"
                "Respond ONLY with JSON containing: summary, verdict, next_steps.\n"
                "Session Data: {session_data}"
            ),
        )
        self.chain = LLMChain(llm=self.llm, prompt=self.prompt, verbose=False) if self.enable_llm and self.llm else None

    def run(self, input_data: Dict[str, Any]) -> str:
        """Create a placeholder audit summary and append an audit log entry."""
        session_id = str(
            input_data.get("session_id")
            or input_data.get("task_id")
            or f"session_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        )
        LOGGER.info("Running audit for session_id=%s", session_id)
        serialized_data = json.dumps(input_data, default=str)

        status = "success"
        output = ""
        error_message = None

        if not self.enable_llm:
            LOGGER.info("LLM disabled for AuditAgent; returning scripted summary.")
            status = "degraded"
            output = json.dumps(
                {
                    "summary": "Audit service configured for placeholder mode.",
                    "verdict": "pending_review",
                    "next_steps": ["Enable ENABLE_OLLAMA=true to activate AI summaries."],
                }
            )
        elif not _is_ollama_available(self.base_url):
            LOGGER.warning("Ollama not reachable; returning fallback audit summary.")
            status = "degraded"
            output = json.dumps(
                {
                    "summary": "Audit service warming up — using placeholder log summary.",
                    "verdict": "pending_review",
                    "next_steps": ["Re-run audit once AI services are reachable."],
                }
            )
        else:
            try:
                if not self.chain:
                    raise RuntimeError("Audit chain is not initialised.")
                response = self.chain.invoke({"session_data": serialized_data})
                output = response.strip() if isinstance(response, str) else str(response)
                if not output:
                    raise ValueError("Audit agent returned an empty response.")
                LOGGER.debug("Audit agent raw response: %s", output)
            except Exception as exc:  # pragma: no cover - defensive safety net
                status = "error"
                error_message = str(exc)
                LOGGER.exception("Audit agent failed: %s", exc)
                fallback = {
                    "summary": "Placeholder audit summary awaiting finalized implementation.",
                    "verdict": "pending_review",
                    "next_steps": ["Escalate to human reviewer once full logic is in place."],
                }
                output = json.dumps(fallback)

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent_name": "AuditAgent",
            "action": "run",
            "status": status,
            "data_summary": self._summarize_for_log(input_data),
            "result_preview": self._truncate(output),
        }
        if error_message:
            event["error"] = error_message
        self._append_audit_event(session_id, event)

        return output

    def _append_audit_event(self, session_id: str, event: Dict[str, Any]) -> None:
        log_path = self.log_dir / f"{session_id}.json"
        history: List[Any]
        if log_path.exists():
            try:
                history = json.loads(log_path.read_text())
                if not isinstance(history, list):
                    history = [history]
            except json.JSONDecodeError:
                LOGGER.warning("Existing audit log for %s is not valid JSON; starting fresh.", session_id)
                history = []
        else:
            history = []

        history.append(event)
        log_path.write_text(json.dumps(history, indent=2))
        LOGGER.info("Appended audit event to %s", log_path)

    @staticmethod
    def _summarize_for_log(data: Dict[str, Any]) -> Dict[str, Any]:
        keys = sorted(data.keys())
        summary = {key: data[key] for key in keys if key != "raw_messages"}
        return json.loads(json.dumps(summary, default=str))

    @staticmethod
    def _truncate(text: str, limit: int = 256) -> str:
        return text if len(text) <= limit else f"{text[:limit]}..."


if __name__ == "__main__":
    sample_session = {
        "session_id": "demo-session",
        "conversation_result": {"greeting": "Hi", "requested_information": ["address"]},
        "kyc_result": {"status": "manual_review"},
        "advisor_result": {"recommendations": ["Placeholder"]},
    }
    agent = AuditAgent()
    print(agent.run(sample_session))


def _is_ollama_available(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=0.5)
        return response.ok
    except requests.RequestException:
        return False
