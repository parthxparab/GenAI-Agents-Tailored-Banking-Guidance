"""Unit tests for the AdvisorAgent questionnaire integration."""

from __future__ import annotations

import os

import pytest

from agents.advisor.advisor_agent import AdvisorAgent


@pytest.fixture(autouse=True)
def disable_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable Ollama so tests exercise the deterministic fallback path."""
    monkeypatch.setenv("ENABLE_OLLAMA", "false")


def test_advisor_agent_returns_structured_recommendations() -> None:
    agent = AdvisorAgent(recommendation_count=2)
    payload = {
        "case_id": "unit_test_case",
        "address": "123 Test Lane",
        "yearly_income": 55000,
        "questions": {
            "q1_credit_history": "established",
            "q2_payment_style": "full_payment",
            "q3_cashback": "yes",
            "q4_travel": "no",
            "q5_simple_card": "yes",
        },
    }

    result = agent.run(payload)

    assert result["source"] == "fallback"
    assert len(result["recommendations"]) == 2
    for card in result["recommendations"]:
        assert {"card_name", "annual_fee", "interest_rate", "rewards", "requirements", "why_recommended"} <= card.keys()


def test_advisor_agent_maps_legacy_profile() -> None:
    agent = AdvisorAgent(recommendation_count=1)
    payload = {
        "user_profile": {
            "intent": "student credit builder",
            "preferences": "cashback with no fee",
            "yearly_income": 25000,
        }
    }

    result = agent.run(payload)

    assert result["source"] == "fallback"
    profile = result["profile"]
    assert profile["questions"]["q1_credit_history"] == "building"
    assert profile["questions"]["q3_cashback"] == "yes"
    assert profile["questions"]["q5_simple_card"] == "yes"
