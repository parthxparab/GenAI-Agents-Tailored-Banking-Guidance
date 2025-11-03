from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Dict

import redis

from genai_client import run_llm

LOG_FORMAT = "[%(asctime)s] [CONVERSATION_AGENT] %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("conversation_agent")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CONVERSATION_CHANNEL = os.getenv("CONVERSATION_CHANNEL", "conversation")
ORCHESTRATOR_CHANNEL = os.getenv("ORCHESTRATOR_CHANNEL", "orchestrator")
LLM_MODEL = os.getenv("CONVERSATION_LLM_MODEL", "llama3")


def connect_redis() -> redis.Redis:
    logger.info("Connecting to Redis at %s", REDIS_URL)
    return redis.from_url(REDIS_URL)


def extract_structured_data(llm_output: Dict[str, Any]) -> Dict[str, Any]:
    intent = llm_output.get("intent")
    full_name = llm_output.get("full_name")
    dob = llm_output.get("dob")
    country = llm_output.get("country")

    missing_fields = [field for field, value in [("intent", intent), ("full_name", full_name), ("dob", dob), ("country", country)] if not value]
    if missing_fields:
        logger.warning("LLM output missing fields %s; falling back to manual review", missing_fields)
        return {
            "intent": "manual_review",
            "collected_data": {
                "full_name": full_name or "",
                "dob": dob or "",
                "country": country or "",
                "notes": llm_output.get("raw_output") or llm_output,
            },
        }

    collected = {
        "full_name": str(full_name),
        "dob": str(dob),
        "country": str(country),
    }
    return {"intent": str(intent), "collected_data": collected}


def run_conversation(task_id: str, user_id: str) -> Dict[str, Any]:
    prompt = f"""
You are a friendly onboarding assistant for a bank.
The user has just started onboarding (task_id: {task_id}, user_id: {user_id}).
Please have a short conversation to gather their full name, date of birth (YYYY-MM-DD), and country of residence.
Understand what banking product they are interested in (e.g., open account, savings, credit card).
Respond ONLY with JSON in the following format once you have the information:
{{
  "intent": "<detected_intent>",
  "full_name": "<full name>",
  "dob": "<YYYY-MM-DD>",
  "country": "<country>"
}}
Do not include any additional text outside the JSON payload.
"""

    logger.info("Prompting LLM model %s for task_id=%s user_id=%s", LLM_MODEL, task_id, user_id)
    llm_response = run_llm(prompt.strip(), model=LLM_MODEL)
    logger.info("Raw LLM response: %s", llm_response)

    if llm_response is None:
        logger.error("LLM returned no response; marking for manual review")
        return {
            "intent": "manual_review",
            "collected_data": {
                "full_name": "",
                "dob": "",
                "country": "",
                "notes": "LLM returned no response.",
            },
        }

    if isinstance(llm_response, dict) and "error" in llm_response:
        logger.error("LLM invocation failed: %s", llm_response)
        return {
            "intent": "manual_review",
            "collected_data": {
                "full_name": "",
                "dob": "",
                "country": "",
                "notes": llm_response,
            },
        }

    if not isinstance(llm_response, dict):
        logger.warning("Unexpected LLM response type: %s", type(llm_response))
        return {
            "intent": "manual_review",
            "collected_data": {
                "full_name": "",
                "dob": "",
                "country": "",
                "notes": llm_response,
            },
        }

    return extract_structured_data(llm_response)


def publish_result(redis_client: redis.Redis, message: Dict[str, Any]) -> None:
    payload = json.dumps(message, default=str)
    redis_client.publish(ORCHESTRATOR_CHANNEL, payload)
    logger.info("Published result to orchestrator: %s", payload)


def handle_message(redis_client: redis.Redis, data: Dict[str, Any]) -> None:
    task_id = data.get("task_id")
    user_id = data.get("user_id")
    step = data.get("step")

    if step != "conversation_start":
        logger.debug("Ignoring message for step=%s task_id=%s", step, task_id)
        return

    if not task_id or not user_id:
        logger.error("Invalid conversation message payload: %s", data)
        return

    logger.info("Processing conversation_start for task_id=%s user_id=%s", task_id, user_id)
    structured_result = run_conversation(task_id, user_id)

    outgoing_message = {
        "task_id": task_id,
        "user_id": user_id,
        "step": "conversation_done",
        "result": structured_result,
    }
    publish_result(redis_client, outgoing_message)


def listen_for_messages() -> None:
    redis_client = connect_redis()
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(CONVERSATION_CHANNEL)
    logger.info("Subscribed to Redis channel '%s'", CONVERSATION_CHANNEL)

    stop_event = threading.Event()

    def handle_shutdown(signum: int, frame: Any) -> None:
        logger.info("Received signal %s, shutting down conversation agent.", signum)
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
            logger.info("Received message from conversation channel: %s", data)
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                logger.error("Failed to decode message: %s", data)
                continue
            handle_message(redis_client, payload)
        except redis.ConnectionError as exc:
            logger.error("Redis connection error: %s. Retrying in 5 seconds.", exc)
            time.sleep(5)
            redis_client = connect_redis()
            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(CONVERSATION_CHANNEL)
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Unexpected error while processing messages: %s", exc)

    logger.info("Conversation agent stopped.")


def simulate_mode() -> None:
    logger.info("Simulation mode activated; no Redis interactions will occur.")
    sample_message = {"task_id": "simulated-task", "user_id": "simulated-user", "step": "conversation_start"}
    structured_result = run_conversation(sample_message["task_id"], sample_message["user_id"])
    simulated_payload = {
        "task_id": sample_message["task_id"],
        "user_id": sample_message["user_id"],
        "step": "conversation_done",
        "result": structured_result,
    }
    logger.info("Simulation result: %s", json.dumps(simulated_payload, indent=2))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1].lower() == "simulate":
        simulate_mode()
        return

    listen_for_messages()


if __name__ == "__main__":
    main()
