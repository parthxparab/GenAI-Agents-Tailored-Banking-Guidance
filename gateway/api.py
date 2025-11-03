"""FastAPI gateway exposing the BankBot Crew orchestration workflow.

The gateway bridges the Streamlit frontend with the CrewAI orchestrator by providing
REST endpoints for launching onboarding sessions, polling progress, retrieving
credit-card recommendations, and confirming the final product selection.

The implementation keeps runtime state in memory but highlights where a Redis or
task-queue backed persistence layer can be plugged in for horizontal scalability.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from agents.audit.audit_agent import AuditAgent
from orchestrator.orchestrator import BankBotOrchestrator

LOGGER = logging.getLogger("bankbot_gateway")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [gateway] %(message)s",
)


class OnboardRequest(BaseModel):
    """Payload submitted by the Streamlit frontend to start onboarding."""

    name: str = Field(..., min_length=1, description="Customer full name.")
    email: EmailStr
    income: float = Field(..., gt=0, description="Annual income in numeric form.")
    occupation: str = Field(..., min_length=2)
    preferences: Optional[str] = Field(
        None, description="Optional free-form preference notes captured during conversation."
    )
    document_name: Optional[str] = Field(None, description="Original filename for the uploaded KYC document.")
    document_content: Optional[str] = Field(
        None,
        description="Base64 encoded representation of the uploaded KYC document.",
        json_schema_extra={"example": "JVBERi0xLjcKJb/..."},
    )


class ConfirmRequest(BaseModel):
    """Payload submitted when the user confirms the recommended product."""

    selected_card: str = Field(..., min_length=1, description="Identifier or name of the chosen card.")
    notes: Optional[str] = Field(None, description="Optional confirmation notes or feedback.")


SessionState = Dict[str, Any]

app = FastAPI(
    title="BankBot Crew Gateway",
    version="1.0.0",
    description="REST interface orchestrating the multi-agent onboarding workflow.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("GATEWAY_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_LOCK = threading.Lock()
_SESSIONS: Dict[str, SessionState] = {}
_ORCHESTRATOR = BankBotOrchestrator()
_AUDIT_AGENT = AuditAgent()

DEFAULT_PROGRESS = {
    "conversation": "pending",
    "kyc": "pending",
    "advisor": "pending",
    "audit": "pending",
}


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _log_api_call(endpoint: str, payload: Dict[str, Any], session_id: Optional[str], outcome: str) -> None:
    """Record API activity via the AuditAgent while shielding the gateway from failures."""
    # Skip heavy audit processing for high-frequency read endpoints; rely on standard logging instead.
    read_only_endpoints = {"GET /status", "GET /recommendations", "GET /health"}
    if any(endpoint.startswith(prefix) for prefix in read_only_endpoints):
        LOGGER.debug("API call %s for session %s: %s", endpoint, session_id, outcome)
        return

    audit_payload = {
        "session_id": session_id,
        "endpoint": endpoint,
        "outcome": outcome,
        "payload_preview": json.loads(json.dumps(payload, default=str)) if payload else {},
        "logged_at": _utc_now(),
    }
    if not _AUDIT_AGENT:
        return

    def _dispatch() -> None:
        try:
            _AUDIT_AGENT.run(audit_payload)
        except Exception as exc:  # pragma: no cover - defensive audit path
            LOGGER.warning("Audit logging for endpoint %s failed: %s", endpoint, exc)

    threading.Thread(target=_dispatch, daemon=True).start()


def _register_session(request: OnboardRequest, session_id: str) -> SessionState:
    """Store a new session entry in memory. Replace with Redis hash in production."""
    session_data: SessionState = {
        "session_id": session_id,
        "status": "pending",
        "message": "Onboarding request accepted. Workflow will start shortly.",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "request": request.model_dump(),
        "progress": DEFAULT_PROGRESS.copy(),
        "recommendations": [],
        "results": None,
        "selected_card": None,
        "confirmation_notes": None,
        "audit_log_path": None,
        "error": None,
    }
    with _LOCK:
        _SESSIONS[session_id] = session_data
    return session_data


def _update_session(session_id: str, **updates: Any) -> None:
    with _LOCK:
        if session_id not in _SESSIONS:
            raise KeyError(f"Unknown session_id: {session_id}")
        _SESSIONS[session_id].update(updates)
        _SESSIONS[session_id]["updated_at"] = _utc_now()


def _build_conversation_context(request: OnboardRequest, session_id: str) -> Dict[str, Any]:
    """Shape the conversation payload expected by the orchestrator."""
    return {
        "session_id": session_id,
        "user_profile": {
            "name": request.name,
            "email": request.email,
            "income": request.income,
            "occupation": request.occupation,
            "preferences": request.preferences,
        },
        "metadata": {
            "channel": "streamlit",
            "locale": "en-US",
            "submitted_at": _utc_now(),
        },
    }


def _decode_documents(request: OnboardRequest) -> List[Dict[str, Any]]:
    """Prepare KYC documents for the orchestrator; data remains base64 encoded for now."""
    if not request.document_content:
        return []
    try:
        base64.b64decode(request.document_content.encode("utf-8"), validate=True)
    except Exception:  # pragma: no cover - defensive validation
        LOGGER.warning("Invalid base64 payload received for session document; storing raw string.")
    return [
        {
            "name": request.document_name or "kyc_document",
            "content_base64": request.document_content,
            "received_at": _utc_now(),
        }
    ]


def _progress_from_results(results: Dict[str, Any]) -> Dict[str, str]:
    progress = DEFAULT_PROGRESS.copy()
    if not results:
        return progress
    if results.get("conversation_result"):
        progress["conversation"] = "completed"
    if results.get("kyc_result"):
        progress["kyc"] = "completed"
    if results.get("advisor_result"):
        progress["advisor"] = "completed"
    if results.get("audit_log_path"):
        progress["audit"] = "completed"
    return progress


def _collect_progress_from_audit(session_id: str) -> Dict[str, str]:
    """Infer progress using the audit log file written by the AuditAgent."""
    progress = DEFAULT_PROGRESS.copy()
    log_path = _AUDIT_AGENT.log_dir / f"{session_id}.json"
    if not log_path.exists():
        return progress

    try:
        events = json.loads(log_path.read_text())
    except json.JSONDecodeError:
        LOGGER.warning("Audit log for %s is not valid JSON; skipping progress extraction.", session_id)
        return progress

    if not isinstance(events, list):
        events = [events]

    mapping = {
        "ConversationAgent": "conversation",
        "KycAgent": "kyc",
        "AdvisorAgent": "advisor",
        "AuditAgent": "audit",
    }
    for event in events:
        summary = event.get("data_summary") or {}
        stage = summary.get("stage")
        if not stage:
            continue
        key = mapping.get(stage)
        if not key:
            continue
        progress[key] = "completed" if event.get("status") == "success" else "error"
    return progress


def _run_workflow_async(session_id: str, request: OnboardRequest) -> None:
    """Execute the CrewAI workflow in the background for the given session."""
    LOGGER.info("Starting workflow for session %s", session_id)
    _update_session(
        session_id,
        status="running",
        message="CrewAI orchestration in progress.",
        progress={
            "conversation": "in_progress",
            "kyc": "pending",
            "advisor": "pending",
            "audit": "pending",
        },
    )
    _log_api_call("workflow_start", request.model_dump(), session_id, outcome="accepted")

    conversation_context = _build_conversation_context(request, session_id)
    documents = _decode_documents(request)

    try:
        results = _ORCHESTRATOR.run_workflow(
            conversation_context=conversation_context,
            documents=documents,
            session_id=session_id,
        )
        recommendations = (
            results.get("advisor_result", {}).get("recommendations") if isinstance(results, dict) else None
        )
        _update_session(
            session_id,
            status="completed",
            message="Onboarding workflow completed successfully.",
            results=results,
            recommendations=recommendations or [],
            audit_log_path=results.get("audit_log_path") if isinstance(results, dict) else None,
            progress=_progress_from_results(results),
        )
        _log_api_call("workflow_complete", {"recommendation_count": len(recommendations or [])}, session_id, "success")
    except Exception as exc:  # pragma: no cover - defensive orchestration path
        LOGGER.exception("Workflow failed for session %s: %s", session_id, exc)
        _update_session(
            session_id,
            status="failed",
            message="Workflow failed; please retry or contact support.",
            error=str(exc),
            progress={"conversation": "error", "kyc": "pending", "advisor": "pending", "audit": "pending"},
        )
        _log_api_call("workflow_failed", {"error": str(exc)}, session_id, "error")


@app.post("/onboard", status_code=status.HTTP_202_ACCEPTED)
async def start_onboarding(request: OnboardRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Kick off the onboarding workflow and return a session identifier."""
    session_id = str(uuid.uuid4())
    _register_session(request, session_id)
    background_tasks.add_task(_run_workflow_async, session_id, request)
    response_payload = {
        "session_id": session_id,
        "status": "pending",
        "message": "Onboarding initialized. Poll /status/{session_id} for updates.",
    }
    _log_api_call("POST /onboard", response_payload, session_id, outcome="queued")
    return response_payload


@app.get("/status/{session_id}")
async def get_status(session_id: str) -> Dict[str, Any]:
    """Return the latest known status and progress for a session."""
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if not session:
        _log_api_call("GET /status", {"error": "not_found"}, session_id, outcome="not_found")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown session_id.")

    if session["status"] == "running":
        session_progress = _collect_progress_from_audit(session_id)
        _update_session(session_id, progress=session_progress)
        with _LOCK:
            session = _SESSIONS.get(session_id)  # refreshed snapshot

    payload = {
        "session_id": session_id,
        "status": session["status"],
        "message": session["message"],
        "progress": session.get("progress", DEFAULT_PROGRESS.copy()),
        "audit_log_path": session.get("audit_log_path"),
        "updated_at": session.get("updated_at"),
        "error": session.get("error"),
    }
    _log_api_call("GET /status", payload, session_id, outcome="returned")
    return payload


@app.get("/recommendations/{session_id}")
async def get_recommendations(session_id: str) -> Dict[str, Any]:
    """Expose advisor recommendations once the workflow has completed."""
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if not session:
        _log_api_call("GET /recommendations", {"error": "not_found"}, session_id, outcome="not_found")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown session_id.")
    if session["status"] == "failed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=session.get("error", "Workflow failed."))
    if session["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Recommendations not ready yet. Please poll /status until completed.",
        )

    results = session.get("results") or {}
    recommendations = session.get("recommendations") or []
    payload = {
        "session_id": session_id,
        "status": session["status"],
        "recommendations": recommendations,
        "advisor_result": results.get("advisor_result"),
    }
    _log_api_call("GET /recommendations", {"recommendation_count": len(recommendations)}, session_id, outcome="returned")
    return payload


@app.post("/confirm/{session_id}")
async def confirm_selection(session_id: str, request: ConfirmRequest) -> Dict[str, Any]:
    """Record the user's final product selection."""
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if not session:
        _log_api_call("POST /confirm", {"error": "not_found"}, session_id, outcome="not_found")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown session_id.")
    if session["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session must be completed before confirmation.",
        )

    _update_session(
        session_id,
        selected_card=request.selected_card,
        confirmation_notes=request.notes,
        message=f"User confirmed card: {request.selected_card}",
    )
    payload = {
        "session_id": session_id,
        "status": "confirmed",
        "selected_card": request.selected_card,
        "notes": request.notes,
        "message": "Confirmation recorded successfully.",
    }
    _log_api_call("POST /confirm", payload, session_id, outcome="confirmed")
    return payload


@app.get("/health")
async def healthcheck() -> Dict[str, str]:
    """Simple readiness probe for container orchestration."""
    payload = {"status": "ok", "timestamp": _utc_now()}
    _log_api_call("GET /health", payload, session_id=None, outcome="returned")
    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gateway.api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
