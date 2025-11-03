"""Audit agent scaffold that logs activity while using LangChain with Ollama."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

from agents.base_agent import BaseAgent

LOGGER = logging.getLogger("audit_agent")


class AuditAgent(BaseAgent):
    """Captures audit trail snapshots after each workflow stage."""

    def __init__(self, model: str | None = None, log_dir: str | None = None) -> None:
        super().__init__(model=model or "llama3")
        self.use_llm = os.getenv("ENABLE_AUDIT_LLM", "false").lower() in {"1", "true", "yes"}
        configured_dir = log_dir or os.getenv("AUDIT_LOG_DIR")
        default_dir = Path(__file__).resolve().parents[2] / "audit_logs"
        self.log_dir = Path(configured_dir) if configured_dir else default_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.prompt = PromptTemplate(
            input_variables=["session_data"],
            template=(
                "You are the audit agent for the BankBot Crew workflow.\n"
                "Review the JSON session data and craft a brief summary.\n"
                "Respond ONLY with JSON containing: summary, verdict, next_steps.\n"
                "Session Data: {session_data}"
            ),
        )
        self.llm_ready = False
        self.chain: LLMChain | None = None
        self._initialise_chain()

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(
            input_data.get("session_id")
            or input_data.get("task_id")
            or f"session_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        )
        LOGGER.info("AuditAgent logging session_id=%s", session_id)
        serialized_data = json.dumps(input_data, default=str)

        status = "success"
        output: Dict[str, Any]
        error_message = None

        # Refresh once per call in case the Ollama runtime recovers mid-workflow.
        self._initialise_chain()

        if not self.llm_ready or not self.chain:
            if self.use_llm:
                LOGGER.info("AuditAgent using local AI summary pathway.")
            else:
                LOGGER.debug("AuditAgent LLM disabled via ENABLE_AUDIT_LLM; using deterministic summary.")
            status = "degraded"
            output = {
                "summary": "Audit service configured for placeholder mode.",
                "verdict": "pending_review",
                "next_steps": ["Enable ENABLE_AUDIT_LLM=true to activate AI summaries."],
            }
        else:
            try:
                response = self.chain.invoke({"session_data": serialized_data})
                parsed = json.loads(response) if isinstance(response, str) else response
                if not isinstance(parsed, dict):
                    raise ValueError("AuditAgent expected dict output from LLM.")
                output = parsed
                LOGGER.debug("AuditAgent produced structured audit summary.")
            except Exception as exc:  # pragma: no cover - defensive safety net
                status = "error"
                error_message = str(exc)
                LOGGER.exception("AuditAgent failed, returning fallback: %s", exc)
                output = {
                    "summary": "Placeholder audit summary awaiting finalized implementation.",
                    "verdict": "pending_review",
                    "next_steps": ["Escalate to human reviewer once full logic is in place."],
                }

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent_name": "AuditAgent",
            "action": "run",
            "status": status,
            "data_summary": self._summarize_for_log(input_data),
            "result_preview": self._truncate(json.dumps(output, default=str)),
        }
        if error_message:
            event["error"] = error_message
        self._append_audit_event(session_id, event)

        enriched = dict(output)
        enriched.update({"session_id": session_id, "status": status})
        return enriched

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


if __name__ == "__main__":
    sample_session = {
        "session_id": "demo-session",
        "conversation_result": {"greeting": "Hi", "requested_information": ["address"]},
        "kyc_result": {"status": "manual_review"},
        "advisor_result": {"recommendations": ["Placeholder"]},
    }
    agent = AuditAgent()
    print(json.dumps(agent.run(sample_session), indent=2))
