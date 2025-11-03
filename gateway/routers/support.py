import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.redis_client import publish

logger = logging.getLogger(__name__)

CHANNEL: Literal["support"] = "support"

router = APIRouter(prefix="/support", tags=["Support"])


class SupportRequest(BaseModel):
    user_id: str = Field(..., description="User or task identifier.")
    query: str = Field(..., description="Support question raised by the user.")


class SupportResponse(BaseModel):
    answer: str


@router.post("/query", response_model=SupportResponse)
async def submit_support_query(payload: SupportRequest) -> SupportResponse:
    """Forward support questions to the support agent via Redis."""
    user_id = payload.user_id.strip()
    query = payload.query.strip()
    if not user_id or not query:
        raise HTTPException(status_code=400, detail="user_id and query are required.")

    logger.info("Support query received for user_id=%s", user_id)
    message = {
        "task_id": user_id,
        "user_id": user_id,
        "step": "support_query",
        "query": query,
    }
    publish(CHANNEL, message)

    demo_answer = "Typically 5–10 minutes. A human will follow up if needed."
    return SupportResponse(answer=demo_answer)
