import json
import logging
import os
from typing import Any, Dict, Optional

import requests

OLLAMA_DEFAULT_URL = "http://ollama:11434"
OLLAMA_DEFAULT_MODEL = "llama3.1:latest"

LOGGER = logging.getLogger(__name__)


def _build_prompt(
    document_type: str,
    extracted_text: str,
    expected_data: Dict[str, Any],
) -> str:
    instruction = {
        "task": "document_authenticity_review",
        "document_type": document_type,
        "extracted_text": extracted_text,
        "expected_fields": expected_data,
        "output_format": {
            "status": "verified|manual_review|rejected",
            "flags": ["list", "of", "string"],
            "confidence": "0-1 float indicating certainty",
            "rationale": "short explanation of any concerns",
        },
        "guidelines": [
            "Mark status as 'verified' only if the text appears genuine and matches expected data.",
            "Use 'manual_review' when uncertain or when issues require human oversight.",
            "Use 'rejected' if the document looks fraudulent or incorrect.",
            "Always return valid JSON adhering to the output_format specification.",
        ],
    }
    return json.dumps(instruction, ensure_ascii=False)


def assess_document_authenticity(
    document_type: str,
    extracted_text: str,
    expected_data: Dict[str, Any],
    model: Optional[str] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    Calls a local Ollama model to evaluate the authenticity of a document.
    """
    base_url = os.getenv("OLLAMA_URL", OLLAMA_DEFAULT_URL).rstrip("/")
    model_name = model or os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)

    payload = {
        "model": model_name,
        "prompt": _build_prompt(document_type, extracted_text, expected_data),
        "stream": False,
        "format": "json",
    }

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        raw_output = body.get("response", "")
        parsed_output = json.loads(raw_output) if raw_output else {}
        return {
            "status": parsed_output.get("status", "manual_review"),
            "flags": parsed_output.get("flags", []),
            "confidence": parsed_output.get("confidence", 0.0),
            "rationale": parsed_output.get("rationale"),
            "model": model_name,
        }
    except Exception as exc:
        LOGGER.exception("Ollama validation failed: %s", exc)
        return {
            "status": "manual_review",
            "flags": ["llm_evaluation_failed"],
            "confidence": 0.0,
            "rationale": f"LLM validation error: {exc}",
            "model": model_name,
        }
