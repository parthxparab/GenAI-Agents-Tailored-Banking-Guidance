"""Advisor agent providing credit-card recommendations via LangChain."""

from __future__ import annotations

import json
import logging
import os
import random
from typing import Any, Dict, List

from langchain_community.chat_models import ChatOllama

from agents.base_agent import BaseAgent
from agents.advisor.credit_cards import CREDIT_CARDS
from agents.advisor.langchain_client import get_credit_card_recommendations

LOGGER = logging.getLogger("advisor_agent")


class AdvisorAgent(BaseAgent):
    """Generates validated credit-card recommendations for a given user profile.

    CrewAI now invokes this agent directly, so the previous Redis pub/sub loop has been removed.
    """

    def __init__(self, model: str | None = None, recommendation_count: int | None = None) -> None:
        super().__init__(model=model or os.getenv("ADVISOR_LLM_MODEL", "llama3"))
        self.recommendation_count = recommendation_count or int(os.getenv("ADVISOR_RECOMMENDATIONS", "3"))
        self.card_lookup = {card["card_name"]: card for card in CREDIT_CARDS}
        self.llm_ready = False
        self.chat_llm: ChatOllama | None = None
        self._initialise_llm()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

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
                LOGGER.exception("AdvisorAgent LLM path failed, using fallback: %s", exc)
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
                    "why_recommended": "Rule-based fallback recommendation while advisor AI warms up.",
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
