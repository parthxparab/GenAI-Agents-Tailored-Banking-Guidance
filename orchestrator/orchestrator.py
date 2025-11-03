import json
import logging
import os
from typing import Any, Dict, Optional

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
ORCHESTRATOR_CHANNEL = os.getenv("ORCHESTRATOR_CHANNEL", "orchestrator")
CONVERSATION_CHANNEL = os.getenv("CONVERSATION_CHANNEL", "conversation")
KYC_CHANNEL = os.getenv("KYC_CHANNEL", "kyc")
ADVISOR_CHANNEL = os.getenv("ADVISOR_CHANNEL", "advisor")
AUDIT_CHANNEL = os.getenv("AUDIT_CHANNEL", "audit")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
LOGGER = logging.getLogger("orchestrator")

# Summary: Maintain per-task state so we can enrich downstream messages with captured results
# and trigger each agent only when its prerequisites (conversation data, documents, etc.) are ready.

TASK_STATE: Dict[str, Dict[str, Any]] = {}


def get_redis_connection() -> redis.Redis:
    return redis.from_url(REDIS_URL)


def ensure_state(task_id: str, user_id: str) -> Dict[str, Any]:
    state = TASK_STATE.setdefault(task_id, {"task_id": task_id, "user_id": user_id})
    state["user_id"] = user_id
    return state


def publish_next_step(conn: redis.Redis, channel: str, message: Dict[str, Any]) -> None:
    conn.publish(channel, json.dumps(message, default=str))
    LOGGER.info("Dispatched step '%s' to channel '%s'", message.get("step"), channel)


def build_user_profile(state: Dict[str, Any]) -> Dict[str, Any]:
    conversation = state.get("conversation_result") or {}
    collected = conversation.get("collected_data") or {}
    profile = {
        "intent": conversation.get("intent"),
        "full_name": collected.get("full_name"),
        "dob": collected.get("dob"),
        "country": collected.get("country"),
    }
    return {k: v for k, v in profile.items() if v}


def trigger_kyc_if_ready(conn: redis.Redis, state: Dict[str, Any]) -> None:
    if state.get("kyc_started"):
        return
    documents = state.get("documents")
    conversation = state.get("conversation_result")
    if not documents:
        LOGGER.debug("KYC not triggered yet for task %s: awaiting documents.", state["task_id"])
        return
    if not conversation:
        LOGGER.debug("KYC not triggered yet for task %s: awaiting conversation result.", state["task_id"])
        return

    user_data = conversation.get("collected_data") or {}
    message = {
        "task_id": state["task_id"],
        "user_id": state["user_id"],
        "step": "kyc_start",
        "documents": documents,
        "user_data": user_data,
    }
    publish_next_step(conn, KYC_CHANNEL, message)
    state["kyc_started"] = True


def trigger_advisor(conn: redis.Redis, state: Dict[str, Any]) -> None:
    if state.get("advisor_started"):
        return
    if not state.get("kyc_result"):
        LOGGER.debug("Advisor not triggered for task %s: awaiting KYC result.", state["task_id"])
        return
    profile = build_user_profile(state)
    message = {
        "task_id": state["task_id"],
        "user_id": state["user_id"],
        "step": "advisor_start",
        "user_profile": profile,
        "conversation_result": state.get("conversation_result"),
        "kyc_result": state.get("kyc_result"),
    }
    publish_next_step(conn, ADVISOR_CHANNEL, message)
    state["advisor_started"] = True


def trigger_audit(conn: redis.Redis, state: Dict[str, Any]) -> None:
    if state.get("audit_started"):
        return
    if not state.get("advisor_result"):
        LOGGER.debug("Audit not triggered for task %s: awaiting advisor result.", state["task_id"])
        return

    message = {
        "task_id": state["task_id"],
        "user_id": state["user_id"],
        "step": "audit_start",
        "conversation_result": state.get("conversation_result"),
        "kyc_result": state.get("kyc_result"),
        "advisor_result": state.get("advisor_result"),
    }
    publish_next_step(conn, AUDIT_CHANNEL, message)
    state["audit_started"] = True


def handle_start(conn: redis.Redis, payload: Dict[str, Any]) -> None:
    state = ensure_state(payload["task_id"], payload["user_id"])
    LOGGER.info("Onboarding start received for task %s", state["task_id"])
    message = {
        "task_id": state["task_id"],
        "user_id": state["user_id"],
        "step": "conversation_start",
    }
    publish_next_step(conn, CONVERSATION_CHANNEL, message)


def handle_conversation_done(conn: redis.Redis, payload: Dict[str, Any]) -> None:
    state = ensure_state(payload["task_id"], payload["user_id"])
    state["conversation_result"] = payload.get("result")
    LOGGER.info("Conversation completed for task %s", state["task_id"])
    trigger_kyc_if_ready(conn, state)


def handle_documents_uploaded(conn: redis.Redis, payload: Dict[str, Any]) -> None:
    state = ensure_state(payload["task_id"], payload["user_id"])
    documents = payload.get("documents") or []
    if not documents:
        LOGGER.warning("No documents provided for task %s; waiting for upload.", state["task_id"])
        return
    existing_docs = state.get("documents", [])
    state["documents"] = existing_docs + documents
    LOGGER.info(
        "KYC documents received for task %s (total=%d)",
        state["task_id"],
        len(state["documents"]),
    )
    trigger_kyc_if_ready(conn, state)


def handle_kyc_done(conn: redis.Redis, payload: Dict[str, Any]) -> None:
    state = ensure_state(payload["task_id"], payload["user_id"])
    state["kyc_result"] = payload.get("result")
    LOGGER.info("KYC completed for task %s", state["task_id"])
    trigger_advisor(conn, state)


def handle_advisor_done(conn: redis.Redis, payload: Dict[str, Any]) -> None:
    state = ensure_state(payload["task_id"], payload["user_id"])
    state["advisor_result"] = payload.get("result")
    LOGGER.info("Advisor completed for task %s", state["task_id"])
    trigger_audit(conn, state)


def handle_audit_done(payload: Dict[str, Any]) -> None:
    task_id = payload.get("task_id")
    user_id = payload.get("user_id")
    LOGGER.info(
        "Audit complete for task %s; onboarding finished for user %s with verdict=%s",
        task_id,
        user_id,
        (payload.get("result") or {}).get("verdict"),
    )
    TASK_STATE.pop(task_id, None)


STEP_HANDLERS = {
    "start": handle_start,
    "conversation_done": handle_conversation_done,
    "kyc_documents_uploaded": handle_documents_uploaded,
    "kyc_done": handle_kyc_done,
    "advisor_done": handle_advisor_done,
}


def route_message(conn: redis.Redis, payload: Dict[str, Any]) -> None:
    task_id = payload.get("task_id")
    user_id = payload.get("user_id")
    step = payload.get("step")

    if not task_id or not user_id or not step:
        raise ValueError("Payload must include 'task_id', 'user_id', and 'step'")

    LOGGER.info("Received step '%s' for user %s (task %s)", step, user_id, task_id)

    if step == "audit_done":
        handle_audit_done(payload)
        return

    handler = STEP_HANDLERS.get(step)
    if not handler:
        LOGGER.warning("No handler defined for step '%s'; message ignored.", step)
        return

    handler(conn, payload)


def listen() -> None:
    conn = get_redis_connection()
    pubsub = conn.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(ORCHESTRATOR_CHANNEL)
    LOGGER.info("✅ Orchestrator started and listening on '%s'", ORCHESTRATOR_CHANNEL)

    while True:
        try:
            message = pubsub.get_message(timeout=1.0)
            if not message:
                continue
            payload_raw: Optional[bytes] = message.get("data")
            if not payload_raw:
                continue
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError as exc:
                LOGGER.error("Invalid JSON received: %s", exc)
                continue
            route_message(conn, payload)
        except Exception as exc:
            LOGGER.exception("Error processing message: %s", exc)


if __name__ == "__main__":
    listen()
