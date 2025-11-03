"""Advisor agent providing credit-card recommendations via LangChain."""

from __future__ import annotations

import json
import logging
import os
import random
from typing import Any, Dict, List

from langchain_community.chat_models import ChatOllama

from credit_cards import CREDIT_CARDS
from langchain_client import get_credit_card_recommendations

LOG_FORMAT = "[%(asctime)s] [ADVISOR_AGENT] %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("advisor_agent")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
ADVISOR_CHANNEL = os.getenv("ADVISOR_CHANNEL", "advisor")
ORCHESTRATOR_CHANNEL = os.getenv("ORCHESTRATOR_CHANNEL", "orchestrator")
RECOMMENDATION_COUNT = int(os.getenv("ADVISOR_RECOMMENDATIONS", "3"))
ADVISOR_LLM_MODEL = os.getenv("ADVISOR_LLM_MODEL", "llama3")


def connect_redis() -> redis.Redis:
    logger.info("Connecting to Redis at %s", REDIS_URL)
    return redis.from_url(REDIS_URL)


def extract_user_profile(message: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and normalize user profile from message.
    Supports both new format (case_id, address, yearly_income, questions) and old format.
    """
    # Check for new format
    if "case_id" in message or "yearly_income" in message or "questions" in message:
        case_id = message.get("case_id") or message.get("task_id", "unknown")
        address = message.get("address", "")
        yearly_income = message.get("yearly_income", 0)
        questions = message.get("questions", {})
        
        # Ensure questions is a dict
        if not isinstance(questions, dict):
            questions = {}
        
        return {
            "case_id": case_id,
            "address": address,
            "yearly_income": yearly_income,
            "questions": questions,
        }
    
    # Old format compatibility - map to new format
    user_profile = message.get("user_profile", {})
    old_intent = user_profile.get("intent", "")
    old_preferences = user_profile.get("preferences", "")
    
    # Try to infer question answers from old format
    questions = {}
    if "student" in old_intent.lower() or "building" in old_preferences.lower():
        questions["q1_credit_history"] = "building"
    elif "established" in old_preferences.lower():
        questions["q1_credit_history"] = "established"
    
    if "low" in old_preferences.lower() and "apr" in old_preferences.lower():
        questions["q2_payment_style"] = "lower apr"
    else:
        questions["q2_payment_style"] = "full payment"
    
    if "cashback" in old_preferences.lower():
        questions["q3_cashback"] = "yes"
    else:
        questions["q3_cashback"] = "no"
    
    if "travel" in old_preferences.lower():
        questions["q4_travel"] = "yes"
    else:
        questions["q4_travel"] = "no"
    
    if "no fee" in old_preferences.lower() or "simple" in old_preferences.lower():
        questions["q5_simple_card"] = "yes"
    else:
        questions["q5_simple_card"] = "no"
    
    return {
        "case_id": message.get("task_id", "unknown"),
        "address": user_profile.get("address", ""),
        "yearly_income": user_profile.get("yearly_income", 30000),  # Default fallback
        "questions": questions,
    }


def validate_recommendations(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate recommendations and ensure card names exist in CREDIT_CARDS.
    """
    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        raise ValueError("Missing recommendations list.")

    # Get valid card names from CREDIT_CARDS
    valid_card_names = {card["card_name"] for card in CREDIT_CARDS}
    
    # Create a lookup for card details
    card_lookup = {card["card_name"]: card for card in CREDIT_CARDS}

    cleaned: List[Dict[str, str]] = []
    for item in recommendations[:RECOMMENDATION_COUNT]:
        if not isinstance(item, dict):
            continue
        required_keys = {"card_name", "annual_fee", "interest_rate", "rewards", "requirements", "why_recommended"}
        if not required_keys.issubset(item):
            continue
        
        card_name = str(item.get("card_name", "")).strip()
        
        # Validate card name exists in CREDIT_CARDS
        if card_name not in valid_card_names:
            logger.warning("Invalid card name '%s' not found in CREDIT_CARDS, skipping", card_name)
            continue
        
        # Ensure card details match the original card data
        original_card = card_lookup.get(card_name, {})
        normalized = {
            "card_name": card_name,
            "annual_fee": str(item.get("annual_fee", original_card.get("annual_fee", ""))).strip(),
            "interest_rate": str(item.get("interest_rate", original_card.get("interest_rate", ""))).strip(),
            "rewards": str(item.get("rewards", original_card.get("rewards", ""))).strip(),
            "requirements": str(item.get("requirements", original_card.get("requirements", ""))).strip(),
            "why_recommended": str(item.get("why_recommended", "")).strip(),
        }
        
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
    """
    Get credit card recommendations using Langchain.
    Accepts new format with case_id, address, yearly_income, and questions.
    """
    logger.info("Getting credit card recommendations using Langchain.")
    
    try:
        # Use Langchain client
        response = get_credit_card_recommendations(user_profile, CREDIT_CARDS)
        
        # Validate the response
        validated = validate_recommendations(response)
        logger.info("Validated recommendations from Langchain.")
        return validated
    except Exception as exc:
        logger.error("Failed to get Langchain recommendations (%s). Falling back.", exc)
        return fallback_recommendations()


def publish_result(redis_client: redis.Redis, payload: Dict[str, Any]) -> None:
    message = json.dumps(payload, default=str)
    redis_client.publish(ORCHESTRATOR_CHANNEL, message)
    logger.info("Published advisor result to orchestrator.")


def handle_message(redis_client: redis.Redis, message: Dict[str, Any]) -> None:
    task_id = message.get("task_id")
    user_id = message.get("user_id")
    step = message.get("step")

    valid_steps = {"advisor_start", "advisor_query"}
    if step not in valid_steps:
        logger.debug("Ignoring message with step=%s", step)
        return

    if not task_id or not user_id:
        logger.error("Invalid advisor message payload: %s", message)
        return

    logger.info("Processing advisor_start for task_id=%s user_id=%s", task_id, user_id)
    
    # Extract user profile using new format with backward compatibility
    user_profile = extract_user_profile(message)
    
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

    def __init__(self, model: str | None = None, recommendation_count: int | None = None) -> None:
        super().__init__(model=model or os.getenv("ADVISOR_LLM_MODEL", "llama3"))
        self.recommendation_count = recommendation_count or int(os.getenv("ADVISOR_RECOMMENDATIONS", "3"))
        self.card_lookup = {card["card_name"]: card for card in CREDIT_CARDS}
        self.llm_ready = False
        self.chat_llm: ChatOllama | None = None
        self._initialise_llm()

def simulate_mode() -> None:
    logger.info("Simulation mode activated.")
    sample_profile = {
        "case_id": "sim_001",
        "address": "123 Main St, Toronto, ON, Canada",
        "yearly_income": 45000,
        "questions": {
            "q1_credit_history": "established",
            "q2_payment_style": "full payment",
            "q3_cashback": "yes",
            "q4_travel": "no",
            "q5_simple_card": "yes",
        },
    }
    agent = AdvisorAgent()
    print(agent.run({"user_profile": sample_profile}))

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        LOGGER.info("AdvisorAgent invoked with payload keys: %s", list(input_data.keys()))
        profile = self._extract_user_profile(input_data)

        recommendations: Dict[str, Any]
        source = "fallback"

        # Keep the shared Ollama chat model warm so we avoid re-instantiation across requests.
        self._initialise_llm()

        if self.llm_ready and self.chat_llm:
            try:
                llm_response = get_credit_card_recommendations(
                    profile,
                    CREDIT_CARDS,
                    llm=self.chat_llm,
                    recommendation_count=self.recommendation_count,
                )
                validated = self._validate_recommendations(llm_response)
                recommendations = {"recommendations": validated}
                source = "langchain"
                LOGGER.debug("AdvisorAgent produced %d LangChain-backed recommendations.", len(validated))
            except Exception as exc:  # pragma: no cover - defensive safety net
                LOGGER.exception("AdvisorAgent LLM path failed, using local AI: %s", exc)
                recommendations = self._fallback_recommendations()
        else:
            LOGGER.info("AdvisorAgent operating in fallback mode (LLM disabled/unavailable).")
            recommendations = self._fallback_recommendations()

        recommendations["source"] = source
        recommendations["profile"] = profile
        return recommendations

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _extract_user_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise incoming payloads from legacy or new orchestrator steps."""
        if "case_id" in payload or "questions" in payload:
            questions = payload.get("questions", {})
            if not isinstance(questions, dict):
                questions = {}
            return {
                "case_id": payload.get("case_id") or payload.get("task_id", "unknown"),
                "address": payload.get("address", ""),
                "yearly_income": payload.get("yearly_income", 0),
                "questions": questions,
            }

        user_profile = payload.get("user_profile", {})
        questions = self._map_legacy_preferences(user_profile)
        return {
            "case_id": payload.get("task_id", "unknown"),
            "address": user_profile.get("address", ""),
            "yearly_income": user_profile.get("yearly_income", 30000),
            "questions": questions,
        }

    @staticmethod
    def _map_legacy_preferences(user_profile: Dict[str, Any]) -> Dict[str, str]:
        """Translate the earlier preference schema into the questionnaire format.

        This maintains backward compatibility with the pre-CrewAI payloads.
        """
        intent = str(user_profile.get("intent", "")).lower()
        preferences = str(user_profile.get("preferences", "")).lower()

        questions = {}
        if "student" in intent or "building" in preferences:
            questions["q1_credit_history"] = "building"
        elif "established" in preferences:
            questions["q1_credit_history"] = "established"
        else:
            questions["q1_credit_history"] = "established"

        questions["q2_payment_style"] = "lower apr" if "low" in preferences and "apr" in preferences else "full payment"
        questions["q3_cashback"] = "yes" if "cashback" in preferences else "no"
        questions["q4_travel"] = "yes" if "travel" in preferences else "no"
        questions["q5_simple_card"] = "yes" if any(term in preferences for term in ["no fee", "simple"]) else "no"
        return questions

    def _validate_recommendations(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        recommendations = payload.get("recommendations")
        if not isinstance(recommendations, list):
            raise ValueError("AdvisorAgent expected recommendations list.")

        cleaned: List[Dict[str, Any]] = []
        for item in recommendations[: self.recommendation_count]:
            if not isinstance(item, dict):
                continue

            card_name = str(item.get("card_name", "")).strip()
            if card_name not in self.card_lookup:
                LOGGER.warning("Discarding recommendation for unknown card '%s'", card_name)
                continue

            original = self.card_lookup[card_name]
            normalized = {
                "card_name": card_name,
                "annual_fee": str(item.get("annual_fee", original.get("annual_fee", ""))).strip(),
                "interest_rate": str(item.get("interest_rate", original.get("interest_rate", ""))).strip(),
                "rewards": str(item.get("rewards", original.get("rewards", ""))).strip(),
                "requirements": str(item.get("requirements", original.get("requirements", ""))).strip(),
                "why_recommended": str(item.get("why_recommended", "")).strip()
                or "Matches the provided profile based on LangChain analysis.",
            }

            if any(not normalized[key] for key in ("card_name", "annual_fee", "interest_rate", "rewards", "requirements")):
                LOGGER.warning("Discarding incomplete recommendation payload: %s", normalized)
                continue
            cleaned.append(normalized)

        if len(cleaned) < self.recommendation_count:
            raise ValueError("AdvisorAgent received insufficient structured recommendations.")
        return cleaned

    def _fallback_recommendations(self) -> Dict[str, Any]:
        choices = random.sample(CREDIT_CARDS, k=min(self.recommendation_count, len(CREDIT_CARDS)))
        enriched = []
        for card in choices:
            enriched.append(
                {
                    "card_name": card["card_name"],
                    "annual_fee": card["annual_fee"],
                    "interest_rate": card["interest_rate"],
                    "rewards": card["rewards"],
                    "requirements": card["requirements"],
                    "why_recommended": "Rule-based AI recommendation",
                }
            )
        return {"recommendations": enriched}

    def _initialise_llm(self) -> None:
        if self.llm_ready and self.chat_llm:
            return
        llm_available = self.is_llm_available(refresh=not self.llm_ready)
        if not llm_available:
            self.llm_ready = False
            self.chat_llm = None
            return
        if not self.chat_llm:
            self.chat_llm = ChatOllama(
                model=self.model_name,
                base_url=self.base_url,
                temperature=0.3,
            )
        self.llm_ready = True
