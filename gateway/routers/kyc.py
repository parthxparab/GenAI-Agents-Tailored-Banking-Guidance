import logging
import os
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from utils.redis_client import publish

logger = logging.getLogger(__name__)

CHANNEL: Literal["orchestrator"] = "orchestrator"
UPLOAD_ROOT = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/kyc", tags=["KYC"])


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
