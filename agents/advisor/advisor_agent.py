from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import threading
import time
from typing import Any, Dict, List

import redis

from credit_cards import CREDIT_CARDS
from genai_client import run_llm

LOG_FORMAT = "[%(asctime)s] [ADVISOR_AGENT] %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("advisor_agent")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
ADVISOR_CHANNEL = os.getenv("ADVISOR_CHANNEL", "advisor")
ORCHESTRATOR_CHANNEL = os.getenv("ORCHESTRATOR_CHANNEL", "orchestrator")
RECOMMENDATION_COUNT = int(os.getenv("ADVISOR_RECOMMENDATIONS", "3"))


def connect_redis() -> redis.Redis:
    logger.info("Connecting to Redis at %s", REDIS_URL)
    return redis.from_url(REDIS_URL)


def build_prompt(user_profile: Dict[str, Any], cards: List[Dict[str, str]]) -> str:
    return f"""
You are a helpful banking product advisor working for a regulated bank.
The user is seeking a credit card recommendation as part of an onboarding journey.

USER PROFILE:
{json.dumps(user_profile, indent=2)}

AVAILABLE CREDIT CARDS:
{json.dumps(cards, indent=2)}

Choose the top {RECOMMENDATION_COUNT} cards that best match the user's intent and profile.
For each card include the keys: card_name, annual_fee, interest_rate, rewards, requirements, why_recommended.
Return ONLY valid JSON matching this structure:
{{
  "recommendations": [
    {{
      "card_name": "...",
      "annual_fee": "...",
      "interest_rate": "...",
      "rewards": "...",
      "requirements": "...",
      "why_recommended": "..."
    }}
  ]
}}
    """.strip()


def validate_recommendations(payload: Dict[str, Any]) -> Dict[str, Any]:
    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        raise ValueError("Missing recommendations list.")

    cleaned: List[Dict[str, str]] = []
    for item in recommendations[:RECOMMENDATION_COUNT]:
        if not isinstance(item, dict):
            continue
        required_keys = {"card_name", "annual_fee", "interest_rate", "rewards", "requirements", "why_recommended"}
        if not required_keys.issubset(item):
            continue
        normalized = {key: str(item.get(key, "")).strip() for key in required_keys}
        if any(not normalized[key] for key in required_keys):
            continue
        cleaned.append(normalized)

    if len(cleaned) < RECOMMENDATION_COUNT:
        raise ValueError("Insufficient structured recommendations.")

    return {"recommendations": cleaned}


def fallback_recommendations() -> Dict[str, Any]:
    choices = random.sample(CREDIT_CARDS, k=min(RECOMMENDATION_COUNT, len(CREDIT_CARDS)))
    enriched = []
    for card in choices:
        enriched.append(
            {
                **card,
                "why_recommended": "Recommended by rule-based fallback due to unavailable advisor response.",
            }
        )
    return {"recommendations": enriched}


def recommend_credit_cards(user_profile: Dict[str, Any]) -> Dict[str, Any]:
    prompt = build_prompt(user_profile, CREDIT_CARDS)
    logger.info("Prompting LLM for advisor recommendations.")
    response = run_llm(prompt)

    if isinstance(response, dict) and "error" in response:
        logger.error("LLM returned error: %s", response)
        return fallback_recommendations()

    try:
        validated = validate_recommendations(response)
        logger.info("Validated recommendations from LLM.")
        return validated
    except Exception as exc:
        logger.error("Failed to validate LLM response (%s). Falling back.", exc)
        return fallback_recommendations()


def publish_result(redis_client: redis.Redis, payload: Dict[str, Any]) -> None:
    message = json.dumps(payload, default=str)
    redis_client.publish(ORCHESTRATOR_CHANNEL, message)
    logger.info("Published advisor result to orchestrator.")


def handle_message(redis_client: redis.Redis, message: Dict[str, Any]) -> None:
    task_id = message.get("task_id")
    user_id = message.get("user_id")
    step = message.get("step")
    user_profile = message.get("user_profile", {})

    valid_steps = {"advisor_start", "advisor_query"}
    if step not in valid_steps:
        logger.debug("Ignoring message with step=%s", step)
        return

    if not task_id or not user_id:
        logger.error("Invalid advisor message payload: %s", message)
        return

    logger.info("Processing advisor_start for task_id=%s user_id=%s", task_id, user_id)
    recommendations = recommend_credit_cards(user_profile)

    outgoing = {
        "task_id": task_id,
        "user_id": user_id,
        "step": "advisor_done",
        "result": recommendations,
    }
    publish_result(redis_client, outgoing)


def listen_for_messages() -> None:
    redis_client = connect_redis()
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(ADVISOR_CHANNEL)
    logger.info("Subscribed to Redis channel '%s'", ADVISOR_CHANNEL)

    stop_event = threading.Event()

    def shutdown(signum: int, frame: Any) -> None:
        logger.info("Received signal %s, shutting down advisor agent.", signum)
        stop_event.set()
        pubsub.close()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

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
            logger.info("Received message from advisor channel: %s", data)
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                logger.error("Failed to decode advisor message: %s", data)
                continue
            handle_message(redis_client, payload)
        except redis.ConnectionError as exc:
            logger.error("Redis connection error: %s. Retrying in 5 seconds.", exc)
            time.sleep(5)
            redis_client = connect_redis()
            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(ADVISOR_CHANNEL)
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected error in advisor loop: %s", exc)

    logger.info("Advisor agent stopped.")


def simulate_mode() -> None:
    logger.info("Simulation mode activated.")
    sample_profile = {
        "full_name": "Simulated User",
        "dob": "1990-01-01",
        "country": "Canada",
        "intent": "credit_card",
        "preferences": "cashback and low fees",
    }
    recommendations = recommend_credit_cards(sample_profile)
    logger.info("Simulation recommendations: %s", json.dumps(recommendations, indent=2))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1].lower() == "simulate":
        simulate_mode()
        return
    listen_for_messages()


if __name__ == "__main__":
    main()
