import logging
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.redis_client import publish

logger = logging.getLogger(__name__)

CHANNEL: Literal["orchestrator"] = "orchestrator"

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


class OnboardingRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=320, description="Unique identifier for the onboarding user.")


class OnboardingResponse(BaseModel):
    message: str = "Onboarding started"
    task_id: str


@router.post("/start", response_model=OnboardingResponse)
async def start_onboarding(payload: OnboardingRequest) -> OnboardingResponse:
    """Kick off the onboarding flow by notifying the orchestrator agent via Redis."""
    user_id = payload.user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")

    task_id = str(uuid.uuid4())
    message = {
        "task_id": task_id,
        "user_id": user_id,
        "step": "start",
    }

    logger.info("Received onboarding start for user_id=%s task_id=%s", user_id, task_id)
    publish(CHANNEL, message)

    return OnboardingResponse(task_id=task_id)
