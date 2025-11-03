import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from utils.redis_client import publish

# Add agents/kyc to path for importing verify_service
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agents" / "kyc"))
from verify_service import verify_driver_license

logger = logging.getLogger(__name__)

CHANNEL: Literal["orchestrator"] = "orchestrator"
UPLOAD_ROOT = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/kyc", tags=["KYC"])


class KYCVerifyRequest(BaseModel):
    """Request model for KYC verification endpoint."""

    name: str = Field(..., description="User's full name")
    address: str = Field(..., description="User's address")
    date_of_birth: str = Field(..., description="User's date of birth in YYYY-MM-DD format")
    driver_license_image: str = Field(
        ..., description="Base64-encoded driver's license image"
    )


class KYCVerifyResponse(BaseModel):
    """Response model for KYC verification endpoint."""

    verified: bool = Field(..., description="Whether verification passed")
    failure_reasons: list[str] = Field(
        default_factory=list, description="List of reasons if verification failed"
    )
    match_details: dict = Field(
        default_factory=dict, description="Detailed match results for each field"
    )


@router.post("/upload", status_code=status.HTTP_200_OK)
async def upload_kyc_document(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    task_id: Optional[str] = Form(None),
):
    """Receive a KYC document, persist it to disk, and notify the KYC agent."""
    user_id = user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")

    task_identifier = (task_id or "").strip()
    if not task_identifier:
        raise HTTPException(status_code=400, detail="task_id is required for KYC processing.")

    original_name = Path(file.filename or "document")
    file_suffix = original_name.suffix or ""
    safe_suffix = file_suffix if len(file_suffix) <= 10 else file_suffix[:10]
    stored_name = f"{task_identifier}_{int(time.time())}_{uuid.uuid4().hex}{safe_suffix}"
    stored_path = UPLOAD_ROOT / stored_name

    logger.info("Received KYC upload for user_id=%s task_id=%s filename=%s", user_id, task_identifier, original_name.name)

    try:
        content = await file.read()
        stored_path.write_bytes(content)
    except OSError as exc:
        logger.error("Failed saving KYC document: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to store the document.") from exc

    # Summary: Notify orchestrator (not the KYC agent directly) so it can merge documents with the
    # conversation output before triggering KYC verification.
    message = {
        "task_id": task_identifier,
        "user_id": user_id,
        "step": "kyc_documents_uploaded",
        "documents": [
            {
                "type": "id",
                "file_path": str(stored_path),
                "original_filename": original_name.name,
            }
        ],
    }

    publish(CHANNEL, message)

    return {"status": "uploaded", "message": "Document received", "task_id": task_identifier}


@router.post("/verify", response_model=KYCVerifyResponse, status_code=status.HTTP_200_OK)
async def verify_kyc_document(payload: KYCVerifyRequest) -> KYCVerifyResponse:
    """
    Verify a driver's license by comparing provided information with OCR-extracted data.
    
    Always returns HTTP 200, with verified=false and failure_reasons if verification fails.
    """
    # Validate input
    if not payload.name or not payload.name.strip():
        return KYCVerifyResponse(
            verified=False,
            failure_reasons=["Name is required"],
            match_details={},
        )

    if not payload.address or not payload.address.strip():
        return KYCVerifyResponse(
            verified=False,
            failure_reasons=["Address is required"],
            match_details={},
        )

    if not payload.date_of_birth or not payload.date_of_birth.strip():
        return KYCVerifyResponse(
            verified=False,
            failure_reasons=["Date of birth is required"],
            match_details={},
        )

    if not payload.driver_license_image or not payload.driver_license_image.strip():
        return KYCVerifyResponse(
            verified=False,
            failure_reasons=["Driver's license image is required"],
            match_details={},
        )

    logger.info(
        "Received KYC verification request for name=%s, address=%s, dob=%s",
        payload.name,
        payload.address,
        payload.date_of_birth,
    )

    try:
        # Call verification service
        result = verify_driver_license(
            name=payload.name.strip(),
            address=payload.address.strip(),
            date_of_birth=payload.date_of_birth.strip(),
            driver_license_image=payload.driver_license_image,
        )

        return KYCVerifyResponse(
            verified=result.get("verified", False),
            failure_reasons=result.get("failure_reasons", []),
            match_details=result.get("match_details", {}),
        )

    except Exception as exc:
        logger.error("Error in KYC verification: %s", exc, exc_info=True)
        return KYCVerifyResponse(
            verified=False,
            failure_reasons=[f"Verification error: {exc}"],
            match_details={},
        )
