import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.redis_client import publish

logger = logging.getLogger(__name__)

CHANNEL: Literal["advisor"] = "advisor"

router = APIRouter(prefix="/product", tags=["Product Advisor"])


class AdviceRequest(BaseModel):
    user_id: str = Field(..., description="User or task identifier returned by onboarding.")
    query: str = Field(..., description="Advisor question.")


class AdviceResponse(BaseModel):
    advice: str


@router.post("/advice", response_model=AdviceResponse)
async def get_product_advice(payload: AdviceRequest) -> AdviceResponse:
    """Forward product advice questions to the advisor agent and return a demo response."""
    user_id = payload.user_id.strip()
    query = payload.query.strip()
    if not user_id or not query:
        raise HTTPException(status_code=400, detail="user_id and query are required.")

    logger.info("Advisor query received for user_id=%s", user_id)
    message = {
        "task_id": user_id,
        "user_id": user_id,
        "step": "advisor_query",
        "query": query,
    }
    publish(CHANNEL, message)

    demo_advice = "Based on your profile, we recommend the SmartSaver Account."
    return AdviceResponse(advice=demo_advice)
