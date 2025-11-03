"""CrewAI-powered orchestration layer for the BankBot Crew system."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
import time
from typing import Any, Callable, Dict, Optional, List

import requests

from agents.advisor.advisor_agent import AdvisorAgent
from agents.audit.audit_agent import AuditAgent
from agents.conversation.conversation_agent import ConversationAgent
from agents.kyc.kyc_agent import KycAgent

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s [BankBotOrchestrator] %(message)s")
LOGGER = logging.getLogger("bankbot_orchestrator")


class BankBotOrchestrator:
    """CrewAI orchestrator coordinating Conversation, KYC, Advisor, and Audit agents."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model_name = model_name or os.getenv("ORCHESTRATOR_MODEL", "llama3")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.enable_llm = os.getenv("ENABLE_OLLAMA", "false").lower() in {"1", "true", "yes"}
        self._ollama_available = _is_ollama_available(self.ollama_base_url) if self.enable_llm else False
        if not self._ollama_available and self.enable_llm:
            LOGGER.warning("Ollama endpoint %s is unreachable; agents will use deterministic fallbacks.", self.ollama_base_url)

        self.conversation_agent = ConversationAgent(model=self.model_name)
        self.kyc_agent = KycAgent(model=self.model_name)
        self.advisor_agent = AdvisorAgent(model=self.model_name)
        self.audit_agent = AuditAgent(model=self.model_name)

        # Runtime state container populated per workflow run.
        self._session_state: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public orchestration API
    # ------------------------------------------------------------------

    def run_workflow(
        self,
        conversation_context: Dict[str, Any],
        documents: Optional[Any] = None,
        session_id: Optional[str] = None,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Kick off the CrewAI workflow and return aggregated results."""
        resolved_session_id = session_id or str(uuid.uuid4())
        sanitized_context = self._ensure_dict(conversation_context)
        sanitized_context = self._sanitize_conversation_context(sanitized_context)
        sanitized_documents = documents or []
        if not isinstance(sanitized_documents, list):
            sanitized_documents = [sanitized_documents]
        user_profile_raw = sanitized_context.get("user_profile", {}) if isinstance(sanitized_context, dict) else {}
        user_profile = user_profile_raw if isinstance(user_profile_raw, dict) else {}
        self._session_state = {
            "session_id": resolved_session_id,
            "conversation_context": sanitized_context,
            "documents": sanitized_documents,
            "conversation_result": None,
            "kyc_result": None,
            "advisor_result": None,
            "conversation_summary": None,
            "audit_summaries": [],
            "user_input": user_profile,
            "performance": {},
        }
        # The orchestrator always flows data sequentially: Conversation -> KYC -> Advisor -> Audit.
        # Each stage stores its structured output back into _session_state so downstream agents receive
        # a consistent dictionary when they execute.
        LOGGER.info("Executing sequential workflow for session %s", resolved_session_id)
        return self._run_sequential_workflow(progress_callback=progress_callback)

    def aggregate_results(self) -> Dict[str, Any]:
        """Prepare structured output for the Streamlit frontend."""
        session_id = self._session_state.get("session_id")
        audit_log_path = self.audit_agent.log_dir / f"{session_id}.json"
        logs: List[Any] = []
        if audit_log_path.exists():
            try:
                logs = json.loads(audit_log_path.read_text())
            except json.JSONDecodeError:
                LOGGER.warning("Audit log for %s is not valid JSON; returning empty logs.", session_id)

        conversation_result = self._ensure_dict(self._session_state.get("conversation_result"))
        if not isinstance(conversation_result, dict):
            conversation_result = {}
        advisor_result = self._ensure_dict(self._session_state.get("advisor_result"))
        if not isinstance(advisor_result, dict):
            advisor_result = {}
        kyc_result = self._ensure_dict(self._session_state.get("kyc_result"))
        if not isinstance(kyc_result, dict):
            kyc_result = {}
        conversation_summary = self._session_state.get("conversation_summary") or self._derive_conversation_summary(
            conversation_result
        )
        recommendations = advisor_result.get("recommendations", [])

        final_payload = {
            "session_id": session_id,
            "conversation_summary": conversation_summary,
            "kyc_status": kyc_result.get("status"),
            "recommendations": recommendations if isinstance(recommendations, list) else [],
            "audit_log_path": str(audit_log_path),
            "timestamp": datetime.utcnow().isoformat(),
            "conversation_result": conversation_result,
            "user_profile": self._session_state.get("user_input"),
            "advisor_result": advisor_result,
            "kyc_result": kyc_result,
            "logs": logs,
            "audit_events": logs,
            "audit_summaries": self._session_state.get("audit_summaries", []),
            "performance": self._session_state.get("performance", {}),
        }
        LOGGER.info("Aggregated workflow results for session %s", session_id)
        return final_payload

    def _run_sequential_workflow(
        self,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Run the deterministic multi-agent pipeline sequentially."""
        context = self._ensure_dict(self._session_state.get("conversation_context", {}))
        start_time = time.time()
        conversation_result = self._ensure_dict(self.conversation_agent.run(context))
        if "questions" not in conversation_result:
            questions = self._session_state.get("user_input", {}).get("questions")
            if questions:
                conversation_result["questions"] = questions
        self._session_state["conversation_result"] = conversation_result
        self._session_state["conversation_summary"] = self._derive_conversation_summary(conversation_result)
        self._record_audit_event("ConversationAgent", context, conversation_result)
        self._record_performance("ConversationAgent", time.time() - start_time)
        self._notify_progress("ConversationAgent", conversation_result, progress_callback)

        kyc_payload = {
            "user_data": {
                **self._session_state.get("user_input", {}),
                **conversation_result,
            },
            "documents": self._session_state.get("documents", []),
        }
        start_time = time.time()
        kyc_result = self._ensure_dict(self.kyc_agent.run(kyc_payload))
        self._session_state["kyc_result"] = kyc_result
        self._record_audit_event("KycAgent", kyc_payload, kyc_result)
        self._record_performance("KycAgent", time.time() - start_time)
        self._notify_progress("KycAgent", kyc_result, progress_callback)

        user_input = self._session_state.get("user_input", {}) or {}
        yearly_income = (
            user_input.get("yearly_income")
            if user_input.get("yearly_income") is not None
            else user_input.get("income")
        )
        advisor_payload = {
            "case_id": self._session_state.get("session_id"),
            "address": user_input.get("address"),
            "yearly_income": yearly_income,
            "questions": user_input.get("questions", {}),
            "user_profile": conversation_result,
            "kyc_result": kyc_result,
        }
        start_time = time.time()
        advisor_result = self._ensure_dict(self.advisor_agent.run(advisor_payload))
        self._session_state["advisor_result"] = advisor_result
        self._record_audit_event("AdvisorAgent", advisor_payload, advisor_result)
        self._record_performance("AdvisorAgent", time.time() - start_time)
        self._notify_progress("AdvisorAgent", advisor_result, progress_callback)

        self._record_audit_event(
            "AuditAgent",
            {"conversation": conversation_result, "kyc": kyc_result},
            advisor_result,
        )
        self._notify_progress(
            "AuditAgent",
            {"conversation": conversation_result, "kyc": kyc_result, "advisor": advisor_result},
            progress_callback,
        )
        return self.aggregate_results()

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _derive_conversation_summary(self, conversation_result: Dict[str, Any]) -> str:
        """Condense conversation agent output so downstream consumers get a quick snapshot."""
        if not conversation_result:
            return "No conversation data collected."
        notes = conversation_result.get("notes")
        if isinstance(notes, str) and notes.strip():
            return notes.strip()
        greeting = conversation_result.get("greeting")
        if isinstance(greeting, str) and greeting.strip():
            return greeting.strip()
        try:
            serialized = json.dumps(conversation_result, default=str)
        except (TypeError, ValueError):
            serialized = str(conversation_result)
        return serialized[:280]

    def _record_audit_event(self, stage: str, input_payload: Any, result_payload: Any) -> None:
        # AuditAgent persists a JSON timeline so downstream services can inspect progress.
        audit_payload = {
            "session_id": self._session_state.get("session_id"),
            "stage": stage,
            "input": input_payload,
            "result": result_payload,
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            audit_snapshot = self.audit_agent.run(audit_payload)
            self._session_state.setdefault("audit_summaries", []).append(audit_snapshot)
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.exception("Audit logging failed for stage %s: %s", stage, exc)

    def _record_performance(self, stage: str, duration_seconds: float) -> None:
        try:
            duration_ms = int(duration_seconds * 1000)
        except (TypeError, ValueError):
            duration_ms = -1
        if duration_ms > 20000:
            LOGGER.warning("Stage %s exceeded 20s (duration_ms=%d).", stage, duration_ms)
        self._session_state.setdefault("performance", {})[stage] = {
            "duration_ms": duration_ms,
            "completed_at": datetime.utcnow().isoformat(),
        }

    def _sanitize_conversation_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = {}
        allowed_keys = {"session_id", "user_profile", "recent_messages", "metadata"}
        for key in allowed_keys:
            if key in context:
                cleaned[key] = context[key]
        if not cleaned:
            return context if isinstance(context, dict) else {}
        return cleaned

    @staticmethod
    def _ensure_dict(payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return {"raw_output": payload}
        return json.loads(json.dumps(payload, default=str))

    def _notify_progress(
        self,
        stage: str,
        payload: Dict[str, Any],
        callback: Optional[Callable[[str, Dict[str, Any]], None]],
    ) -> None:
        if not callback:
            return
        try:
            callback(stage, payload)
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.warning("Progress callback for stage %s failed: %s", stage, exc)


def _is_ollama_available(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=0.5)
        return response.ok
    except requests.RequestException:
        return False


if __name__ == "__main__":
    dummy_context = {
        "session_id": "demo-session",
        "recent_messages": [
            {"sender": "user", "content": "I'd like a new credit card with travel rewards."},
        ],
        "metadata": {"channel": "web", "locale": "en-US"},
    }
    orchestrator = BankBotOrchestrator()
    results = orchestrator.run_workflow(conversation_context=dummy_context, documents=[{"type": "passport"}])
    print(json.dumps(results, indent=2))
