from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from langchain_ollama import ChatOllama
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger("langchain_client")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("ADVISOR_LLM_MODEL", "llama3")
RECOMMENDATION_COUNT = int(os.getenv("ADVISOR_RECOMMENDATIONS", "3"))


def _build_prompt_template() -> ChatPromptTemplate:
    """Build the Langchain prompt template for credit card recommendations."""
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a helpful banking product advisor working for a regulated bank.
Your task is to recommend credit cards from the provided list that best match the user's profile and preferences.

CRITICAL RULES:
1. You MUST select cards ONLY from the provided AVAILABLE CREDIT CARDS list
2. You MUST use the EXACT card_name as it appears in the list (case-sensitive)
3. You MUST check that the user's yearly_income meets the card's requirements
4. You MUST match the user's preferences based on their question answers
5. Return exactly {recommendation_count} recommendations

Card Matching Logic:
- q1_credit_history: If user is building credit → prefer Secured/Student cards. If established → any card
- q2_payment_style: If full payment → any card. If lower APR needed → prefer cards with lower interest_rate
- q3_cashback: If yes → prefer cards with "cashback" in rewards
- q4_travel: If yes → prefer cards with "travel", "points", "miles", or "airline" in rewards
- q5_simple_card: If yes → prefer cards with "$0" annual_fee

Income Requirements:
- Extract minimum income from card requirements (e.g., "Minimum income $30,000")
- Only recommend cards where user's yearly_income meets or exceeds the requirement
- If no specific requirement stated, consider the card eligible""",
            ),
            (
                "user",
                """Case ID: {case_id}
Address: {address}
Yearly Income: ${yearly_income}

Question Answers:
1. Credit History: {q1_credit_history}
2. Payment Style: {q2_payment_style}
3. Cashback Interest: {q3_cashback}
4. Travel Frequency: {q4_travel}
5. Simple Card Preference: {q5_simple_card}

AVAILABLE CREDIT CARDS:
{available_cards}

Return ONLY valid JSON matching this structure:
{{
  "recommendations": [
    {{
      "card_name": "<exact name from available cards>",
      "annual_fee": "<from card>",
      "interest_rate": "<from card>",
      "rewards": "<from card>",
      "requirements": "<from card>",
      "why_recommended": "<brief explanation why this card matches the user>"
    }}
  ]
}}""",
            ),
        ]
    )


def _parse_income_requirement(requirements: str) -> float:
    """Extract minimum income from requirements string. Returns 0 if no requirement found."""
    import re

    match = re.search(r"Minimum income \$?([\d,]+)", requirements, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", ""))
    return 0.0


def _filter_eligible_cards(cards: List[Dict[str, str]], yearly_income: float) -> List[Dict[str, str]]:
    """Filter cards based on income requirements."""
    eligible = []
    for card in cards:
        req_income = _parse_income_requirement(card.get("requirements", ""))
        if req_income == 0 or yearly_income >= req_income:
            eligible.append(card)
    return eligible if eligible else cards  # Return all if none eligible (fallback)


def get_credit_card_recommendations(user_data: Dict[str, Any], cards: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Get credit card recommendations using Langchain with Ollama.

    Args:
        user_data: Dictionary containing case_id, address, yearly_income, and questions
        cards: List of available credit cards from credit_cards.py

    Returns:
        Dictionary with recommendations list
    """
    try:
        # Extract user data
        case_id = user_data.get("case_id", "unknown")
        address = user_data.get("address", "")
        yearly_income = float(user_data.get("yearly_income", 0))
        questions = user_data.get("questions", {})

        q1_credit_history = questions.get("q1_credit_history", "")
        q2_payment_style = questions.get("q2_payment_style", "")
        q3_cashback = questions.get("q3_cashback", "")
        q4_travel = questions.get("q4_travel", "")
        q5_simple_card = questions.get("q5_simple_card", "")

        # Filter cards by income eligibility
        eligible_cards = _filter_eligible_cards(cards, yearly_income)
        cards_json = json.dumps(eligible_cards, indent=2)

        # Read model and URL dynamically (in case they were updated after import)
        model = os.getenv("ADVISOR_LLM_MODEL", DEFAULT_MODEL)
        ollama_url = os.getenv("OLLAMA_URL", OLLAMA_URL)
        
        logger.info("Using model: %s, URL: %s", model, ollama_url)
        
        # Initialize LLM
        llm = ChatOllama(
            model=model,
            base_url=ollama_url,
            temperature=0.7,
        )

        # Create parser
        parser = JsonOutputParser()

        # Build chain
        prompt = _build_prompt_template()
        chain = prompt | llm | parser

        # Invoke chain
        logger.info("Invoking Langchain chain for case_id=%s", case_id)
        response = chain.invoke(
            {
                "case_id": case_id,
                "address": address,
                "yearly_income": yearly_income,
                "q1_credit_history": q1_credit_history,
                "q2_payment_style": q2_payment_style,
                "q3_cashback": q3_cashback,
                "q4_travel": q4_travel,
                "q5_simple_card": q5_simple_card,
                "available_cards": cards_json,
                "recommendation_count": RECOMMENDATION_COUNT,
            }
        )

        # Validate response structure
        if not isinstance(response, dict):
            raise ValueError(f"Expected dict response, got {type(response)}")

        recommendations = response.get("recommendations", [])
        if not isinstance(recommendations, list):
            raise ValueError("Recommendations must be a list")

        # Validate card names exist in provided cards
        card_names = {card["card_name"] for card in cards}
        validated_recommendations = []
        for rec in recommendations[:RECOMMENDATION_COUNT]:
            card_name = rec.get("card_name", "")
            if card_name in card_names:
                validated_recommendations.append(rec)
            else:
                logger.warning("Recommended card '%s' not found in available cards", card_name)

        if len(validated_recommendations) < RECOMMENDATION_COUNT:
            logger.warning(
                "Only %d valid recommendations found, expected %d",
                len(validated_recommendations),
                RECOMMENDATION_COUNT,
            )

        return {"recommendations": validated_recommendations}

    except Exception as exc:
        logger.error("Error in Langchain recommendation: %s", exc, exc_info=True)
        raise


