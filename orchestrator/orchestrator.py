"""CrewAI-powered orchestration layer for the BankBot Crew system."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, List

import requests
from crewai import Agent as CrewAgent
from crewai import Crew, Process, Task
from langchain_core.language_models.llms import LLM
from langchain_core.tools import Tool
from langchain_community.llms import Ollama

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
        self._use_llm = self.enable_llm and self._ollama_available
        self.llm = (
            Ollama(model=self.model_name, base_url=self.ollama_base_url) if self._use_llm else _FallbackPlannerLLM()
        )

        # Instantiate operational agents.
        self.conversation_agent = ConversationAgent(model=self.model_name)
        self.kyc_agent = KycAgent(model=self.model_name)
        self.advisor_agent = AdvisorAgent(model=self.model_name)
        self.audit_agent = AuditAgent(model=self.model_name)

        # Runtime state container populated per workflow run.
        self._session_state: Dict[str, Any] = {}

        # Wrap the LangChain agents as CrewAI tools so Crew processes can invoke them.
        self._conversation_tool = Tool(
            name="ConversationAgentTool",
            func=self._run_conversation_step,
            description="Collect structured onboarding details from the user context.",
        )
        self._kyc_tool = Tool(
            name="KycAgentTool",
            func=self._run_kyc_step,
            description="Validate identity data and documents gathered during onboarding.",
        )
        self._advisor_tool = Tool(
            name="AdvisorAgentTool",
            func=self._run_advisor_step,
            description="Generate placeholder banking product recommendations.",
        )

        # Register CrewAI-facing personas for coordination. These use the shared Ollama model
        # for high-level planning while delegating execution to the wrapped tools.
        self._conversation_crewai_agent = CrewAgent(
            role="Onboarding Conversation Specialist",
            goal="Gather accurate, structured onboarding data to kick off KYC.",
            backstory=(
                "You welcome new customers, record their basic details, and ensure the session "
                "is ready for automated KYC verification."
            ),
            tools=[self._conversation_tool],
            allow_delegation=False,
            verbose=False,
            llm=self.llm,
        )
        self._kyc_crewai_agent = CrewAgent(
            role="Digital KYC Analyst",
            goal="Assess provided documents and return a placeholder verification result.",
            backstory="You confirm KYC readiness before the advisor formulates offers.",
            tools=[self._kyc_tool],
            allow_delegation=False,
            verbose=False,
            llm=self.llm,
        )
        self._advisor_crewai_agent = CrewAgent(
            role="Product Advisor",
            goal="Draft provisional credit-card guidance based on verified data.",
            backstory="You sketch product options so a human banker can follow up quickly.",
            tools=[self._advisor_tool],
            allow_delegation=False,
            verbose=False,
            llm=self.llm,
        )

        # Tasks reference the session payload which is supplied during kickoff.
        self._conversation_task = Task(
            description=(
                "Use ConversationAgentTool to collect onboarding details for session {{session_id}}. "
                "Input payload: {{conversation_context}}"
            ),
            agent=self._conversation_crewai_agent,
            expected_output="JSON containing greeting, requested_information, and notes.",
        )
        self._kyc_task = Task(
            description=(
                "Execute KycAgentTool with the structured data produced earlier for session {{session_id}}. "
                "Ensure the output includes status, confidence, and notes."
            ),
            agent=self._kyc_crewai_agent,
            expected_output="JSON containing status, confidence, and notes.",
        )
        self._advisor_task = Task(
            description=(
                "Run AdvisorAgentTool to propose placeholder credit card recommendations for session {{session_id}}. "
                "Include a rationale string in the JSON output."
            ),
            agent=self._advisor_crewai_agent,
            expected_output="JSON containing recommendations and rationale.",
        )

        # Assemble a sequential crew when LLM-powered workflows are enabled.
        if self._use_llm:
            self.crew = Crew(
                agents=[
                    self._conversation_crewai_agent,
                    self._kyc_crewai_agent,
                    self._advisor_crewai_agent,
                ],
                tasks=[
                    self._conversation_task,
                    self._kyc_task,
                    self._advisor_task,
                ],
                process=Process.sequential,
                verbose=False,
            )
        else:
            self.crew = None

    # ------------------------------------------------------------------
    # Tool wrappers executed by Crew tasks. Each wrapper logs via AuditAgent.
    # ------------------------------------------------------------------

    def _run_conversation_step(self, conversation_context: Any) -> str:
        context = self._ensure_dict(conversation_context)
        result_raw = self.conversation_agent.run(context)
        result = self._ensure_dict(result_raw)
        if "questions" not in result:
            questions = self._session_state.get("user_input", {}).get("questions")
            if questions:
                result["questions"] = questions
        self._session_state["conversation_result"] = result
        self._session_state["conversation_summary"] = self._derive_conversation_summary(result)
        self._record_audit_event("ConversationAgent", context, result)
        return json.dumps(result)

    def _run_kyc_step(self, _: Any = None) -> str:
        documents_raw = self._session_state.get("documents", [])
        documents_summary = self.kyc_agent._summarize_documents(documents_raw)
        user_input = self._session_state.get("user_input", {})
        if not isinstance(user_input, dict):
            user_input = {}
        conversation_details = self._ensure_dict(self._session_state.get("conversation_result"))
        if not isinstance(conversation_details, dict):
            conversation_details = {}
        payload = {
            "user_data": {
                **user_input,
                **conversation_details,
            },
            "documents": documents_summary,
        }
        result_raw = self.kyc_agent.run(payload)
        result = self._ensure_dict(result_raw)
        self._session_state["kyc_result"] = result
        self._record_audit_event("KycAgent", payload, result)
        return json.dumps(result)

    def _run_advisor_step(self, _: Any = None) -> str:
        user_input = self._session_state.get("user_input", {}) or {}
        if not isinstance(user_input, dict):
            user_input = {}
        yearly_income = (
            user_input.get("yearly_income")
            if user_input.get("yearly_income") is not None
            else user_input.get("income")
        )
        if yearly_income is None:
            yearly_income = 0
        try:
            yearly_income_value = float(yearly_income)
        except (TypeError, ValueError):
            yearly_income_value = 0.0
        questions = user_input.get("questions", {})
        if not isinstance(questions, dict):
            questions = {}
        conversation_details = self._ensure_dict(self._session_state.get("conversation_result"))
        if not isinstance(conversation_details, dict):
            conversation_details = {}
        kyc_result = self._ensure_dict(self._session_state.get("kyc_result"))
        if not isinstance(kyc_result, dict):
            kyc_result = {}
        payload = {
            "case_id": self._session_state.get("session_id"),
            "address": user_input.get("address"),
            "yearly_income": yearly_income_value,
            "questions": questions,
            "user_profile": conversation_details,
            "kyc_result": kyc_result,
        }
        result_raw = self.advisor_agent.run(payload)
        result = self._ensure_dict(result_raw)
        self._session_state["advisor_result"] = result
        self._record_audit_event("AdvisorAgent", payload, result)
        return json.dumps(result)

    # ------------------------------------------------------------------
    # Public orchestration API
    # ------------------------------------------------------------------

    def run_workflow(
        self,
        conversation_context: Dict[str, Any],
        documents: Optional[Any] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Kick off the CrewAI workflow and return aggregated results."""
        resolved_session_id = session_id or str(uuid.uuid4())
        sanitized_context = self._ensure_dict(conversation_context)
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
        }
        # The orchestrator always flows data sequentially: Conversation -> KYC -> Advisor -> Audit.
        # Each stage stores its structured output back into _session_state so downstream agents
        # receive a consistent dictionary when they execute.

        if not self._use_llm or not self.crew:
            LOGGER.info("Executing fallback workflow for session %s (LLM disabled or unavailable).", resolved_session_id)
            # When Ollama is offline we short-circuit the CrewAI stack and execute agents sequentially.
            results = self._run_fallback_workflow()
            return results

        inputs = {
            "session_id": resolved_session_id,
            "conversation_context": json.dumps(sanitized_context, default=str),
        }
        LOGGER.info("Launching workflow for session %s", resolved_session_id)
        try:
            self.crew.kickoff(inputs=inputs)
        except Exception as exc:
            LOGGER.exception("Crew execution failed for session %s; falling back to sequential run: %s", resolved_session_id, exc)
            return self._run_fallback_workflow()

        # Record a final audit snapshot combining all outcomes.
        self._record_audit_event(
            "AuditAgent",
            {"conversation": self._session_state["conversation_result"], "kyc": self._session_state["kyc_result"]},
            self._session_state.get("advisor_result"),
        )
        return self.aggregate_results()

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
        }
        LOGGER.info("Aggregated workflow results for session %s", session_id)
        return final_payload

    def _run_fallback_workflow(self) -> Dict[str, Any]:
        """Run a lightweight placeholder workflow when LLMs are disabled."""
        context = self._ensure_dict(self._session_state.get("conversation_context", {}))
        conversation_result = self._ensure_dict(self.conversation_agent.run(context))
        if "questions" not in conversation_result:
            questions = self._session_state.get("user_input", {}).get("questions")
            if questions:
                conversation_result["questions"] = questions
        self._session_state["conversation_result"] = conversation_result
        self._session_state["conversation_summary"] = self._derive_conversation_summary(conversation_result)
        self._record_audit_event("ConversationAgent", context, conversation_result)

        kyc_payload = {
            "user_data": {
                **self._session_state.get("user_input", {}),
                **conversation_result,
            },
            "documents": self._session_state.get("documents", []),
        }
        kyc_result = self._ensure_dict(self.kyc_agent.run(kyc_payload))
        self._session_state["kyc_result"] = kyc_result
        self._record_audit_event("KycAgent", kyc_payload, kyc_result)

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
        advisor_result = self._ensure_dict(self.advisor_agent.run(advisor_payload))
        self._session_state["advisor_result"] = advisor_result
        self._record_audit_event("AdvisorAgent", advisor_payload, advisor_result)

        self._record_audit_event(
            "AuditAgent",
            {"conversation": conversation_result, "kyc": kyc_result},
            advisor_result,
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


class _FallbackPlannerLLM(LLM):
    """Minimal LLM stub so CrewAI can continue while Ollama is unavailable."""

    def _call(
        self,
        prompt: str,
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        return (
            "Crew coordination fallback response. Continue using existing task outputs without additional planning."
        )

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"name": "FallbackPlannerLLM"}

    @property
    def _llm_type(self) -> str:
        return "fallback"


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
