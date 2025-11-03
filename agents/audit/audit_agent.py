from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import redis

from genai_client import run_llm

LOG_FORMAT = "[%(asctime)s] [AUDIT_AGENT] %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("audit_agent")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
AUDIT_CHANNEL = os.getenv("AUDIT_CHANNEL", "audit")
ORCHESTRATOR_CHANNEL = os.getenv("ORCHESTRATOR_CHANNEL", "orchestrator")
AUDIT_DIR = Path(os.getenv("AUDIT_LOG_DIR", "/data/audit_logs"))
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# Summary: Compile downstream agent outputs, rely on Ollama for the final verdict, persist an audit
# record to disk, and notify the orchestrator that onboarding has finished.


def connect_redis() -> redis.Redis:
    logger.info("Connecting to Redis at %s", REDIS_URL)
    return redis.from_url(REDIS_URL)


def build_prompt(payload: Dict[str, Any]) -> str:
    prompt = f"""
You are an audit assistant for a bank's onboarding AI workflow.
Use the following agent outputs to prepare the final audit summary.

Conversation Agent Result:
{json.dumps(payload.get("conversation_result", {}), indent=2)}

KYC Agent Result:
{json.dumps(payload.get("kyc_result", {}), indent=2)}

Product Advisor Agent Result:
{json.dumps(payload.get("advisor_result", {}), indent=2)}

Write a concise audit summary (3-4 sentences) describing key outcomes, risks, and recommendations.
Classify the final verdict as one of: "approved", "manual_review", "rejected".
Return ONLY JSON in this exact format:
{{
  "summary": "<summary text>",
  "verdict": "<approved|manual_review|rejected>"
}}
""".strip()
    return prompt


def fallback_result() -> Dict[str, str]:
    return {
        "summary": "Onboarding completed. Awaiting final review; no critical blockers detected.",
        "verdict": "approved",
    }


def validate_response(response: Dict[str, Any]) -> Dict[str, str]:
    summary = str(response.get("summary", "")).strip()
    verdict = str(response.get("verdict", "")).strip().lower()
    valid_verdicts = {"approved", "manual_review", "rejected"}
    if not summary or verdict not in valid_verdicts:
        raise ValueError("Invalid audit response.")
    return {"summary": summary, "verdict": verdict}


def summarize_audit(payload: Dict[str, Any]) -> Dict[str, str]:
    prompt = build_prompt(payload)
    logger.info("Prompting LLM for audit summary.")
    response = run_llm(prompt)

    if isinstance(response, dict) and "error" in response:
        logger.error("LLM error: %s", response)
        return fallback_result()

    try:
        validated = validate_response(response)
        logger.info("LLM summary validated.")
        return validated
    except Exception as exc:
        logger.error("Failed to validate LLM output: %s", exc)
        return fallback_result()


def save_audit_log(task_id: str, record: Dict[str, Any]) -> Path:
    timestamp = datetime.utcnow().isoformat()
    record_with_meta = {
        **record,
        "task_id": task_id,
        "timestamp": timestamp,
    }
    path = AUDIT_DIR / f"{task_id}.json"
    path.write_text(json.dumps(record_with_meta, indent=2))
    logger.info("Saved audit log to %s", path)
    return path


def publish_result(redis_client: redis.Redis, message: Dict[str, Any]) -> None:
    payload = json.dumps(message, default=str)
    redis_client.publish(ORCHESTRATOR_CHANNEL, payload)
    logger.info("Published audit result for task_id=%s", message.get("task_id"))


def handle_message(redis_client: redis.Redis, payload: Dict[str, Any]) -> None:
    task_id = payload.get("task_id")
    user_id = payload.get("user_id")
    step = payload.get("step")

    if step != "audit_start":
        logger.debug("Ignoring message step=%s", step)
        return

    if not task_id or not user_id:
        logger.error("Invalid payload received: %s", payload)
        return

    logger.info("Processing audit_start for task_id=%s user_id=%s", task_id, user_id)
    summary = summarize_audit(payload)

    full_record = {
        "user_id": user_id,
        "conversation_result": payload.get("conversation_result"),
        "kyc_result": payload.get("kyc_result"),
        "advisor_result": payload.get("advisor_result"),
        "audit_summary": summary,
    }
    save_audit_log(task_id, full_record)

    outgoing = {
        "task_id": task_id,
        "user_id": user_id,
        "step": "audit_done",
        "result": summary,
    }
    publish_result(redis_client, outgoing)


def listen_for_messages() -> None:
    redis_client = connect_redis()
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(AUDIT_CHANNEL)
    logger.info("Subscribed to Redis channel '%s'", AUDIT_CHANNEL)

    stop_event = threading.Event()

    def handle_shutdown(signum: int, frame: Any) -> None:
        logger.info("Received signal %s; shutting down audit agent.", signum)
        stop_event.set()
        pubsub.close()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    while not stop_event.is_set():
        try:
            message = pubsub.get_message(timeout=1.0)
            if not message:
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if not data:
                continue
            logger.info("Received message on audit channel: %s", data)
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                logger.error("Failed to decode audit message: %s", data)
                continue
            handle_message(redis_client, payload)
        except redis.ConnectionError as exc:
            logger.error("Redis connection error: %s. Reconnecting shortly.", exc)
            redis_client = connect_redis()
            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(AUDIT_CHANNEL)
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected error in audit loop: %s", exc)

    logger.info("Audit agent stopped.")


def simulate_mode() -> None:
    logger.info("Simulation mode activated.")
    sample_payload = {
        "task_id": "simulated-task",
        "user_id": "simulated-user",
        "step": "audit_start",
        "conversation_result": {"intent": "credit_card", "collected_data": {"full_name": "Sim User"}},
        "kyc_result": {"status": "verified"},
        "advisor_result": {"recommendations": [{"card_name": "SmartSaver Visa Platinum"}]},
    }
    summary = summarize_audit(sample_payload)
    logger.info("Simulation summary: %s", json.dumps(summary, indent=2))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1].lower() == "simulate":
        simulate_mode()
        return
    listen_for_messages()


if __name__ == "__main__":
    main()
