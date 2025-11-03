import json
import logging
import os
from typing import Any, Dict, Iterable, List

import redis

from .compare_utils import ComparisonResult, evaluate_user_data
from .genai_validator import assess_document_authenticity
from .ocr_utils import extract_text

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
LOGGER = logging.getLogger("kyc_agent")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
KYC_CHANNEL = os.getenv("KYC_CHANNEL", "kyc")
ORCHESTRATOR_CHANNEL = os.getenv("ORCHESTRATOR_CHANNEL", "orchestrator")
MATCH_SCORE_THRESHOLD = float(os.getenv("MATCH_SCORE_THRESHOLD", "0.65"))


def _combine_status(
    comparison: ComparisonResult, llm_assessment: Dict[str, Any], flags: Iterable[str]
) -> str:
    base_status = llm_assessment.get("status", "manual_review")
    if comparison.match_score < MATCH_SCORE_THRESHOLD and base_status == "verified":
        return "manual_review"
    if "llm_evaluation_failed" in flags:
        return "manual_review"
    return base_status


def _aggregate_flags(initial_flags: Iterable[str], extra_flags: Iterable[str]) -> List[str]:
    unique_flags = []
    for flag in list(initial_flags) + list(extra_flags):
        if flag and flag not in unique_flags:
            unique_flags.append(flag)
    return unique_flags


def evaluate_document(document: Dict[str, Any], user_data: Dict[str, Any]) -> Dict[str, Any]:
    file_path = document.get("file_path")
    document_type = document.get("type", "unknown")
    extracted = extract_text(file_path)

    comparison = evaluate_user_data(
        extracted.get("lines", []),
        user_data.get("full_name"),
        user_data.get("dob"),
    )

    llm_assessment = assess_document_authenticity(
        document_type=document_type,
        extracted_text=extracted.get("text", ""),
        expected_data=user_data,
    )

    flags = list(llm_assessment.get("flags", []))
    if comparison.match_score < MATCH_SCORE_THRESHOLD:
        flags.append("low_match_score")
    if comparison.name_score == 0:
        flags.append("name_not_found")
    if comparison.dob_score == 0 and user_data.get("dob"):
        flags.append("dob_not_found")

    final_status = _combine_status(comparison, llm_assessment, flags)
    flags = _aggregate_flags(flags, [])

    metadata = {
        "document_type": document_type,
        "ocr_name": comparison.ocr_name,
        "ocr_dob": comparison.ocr_dob,
        "name_score": round(comparison.name_score, 4),
        "dob_score": round(comparison.dob_score, 4),
        "llm_confidence": llm_assessment.get("confidence"),
        "llm_rationale": llm_assessment.get("rationale"),
    }

    return {
        "document_type": document_type,
        "status": final_status,
        "match_score": round(comparison.match_score, 4),
        "flags": flags,
        "metadata": metadata,
    }


def _determine_overall_status(document_results: Iterable[Dict[str, Any]]) -> str:
    overall_status = "verified"
    for result in document_results:
        status = result.get("status", "manual_review")
        if status == "rejected":
            return "rejected"
        if status == "manual_review":
            overall_status = "manual_review"
    return overall_status


def _average_match_score(document_results: Iterable[Dict[str, Any]]) -> float:
    scores = [result.get("match_score", 0.0) for result in document_results]
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def publish(redis_client: redis.Redis, channel: str, payload: Dict[str, Any]) -> None:
    redis_client.publish(channel, json.dumps(payload))
    LOGGER.info("Published result for task %s to %s", payload.get("task_id"), channel)


def handle_message(redis_client: redis.Redis, message: Dict[str, Any]) -> None:
    task_id = message.get("task_id")
    user_id = message.get("user_id")
    documents = message.get("documents", [])
    user_data = message.get("user_data", {})

    LOGGER.info("Processing KYC task %s for user %s with %d document(s)", task_id, user_id, len(documents))

    document_results: List[Dict[str, Any]] = []
    aggregated_flags: List[str] = []

    for document in documents:
        try:
            result = evaluate_document(document, user_data)
        except FileNotFoundError as error:
            LOGGER.exception("Document missing for task %s: %s", task_id, error)
            result = {
                "document_type": document.get("type", "unknown"),
                "status": "manual_review",
                "match_score": 0.0,
                "flags": ["document_missing"],
                "metadata": {"error": str(error)},
            }
        except Exception as error:  # Catch-all for unexpected issues
            LOGGER.exception("Failed to process document for task %s: %s", task_id, error)
            result = {
                "document_type": document.get("type", "unknown"),
                "status": "manual_review",
                "match_score": 0.0,
                "flags": ["processing_error"],
                "metadata": {"error": str(error)},
            }

        aggregated_flags = _aggregate_flags(aggregated_flags, result.get("flags", []))
        document_results.append(result)

    overall_status = _determine_overall_status(document_results)
    overall_match_score = _average_match_score(document_results)

    orchestrator_payload = {
        "task_id": task_id,
        "user_id": user_id,
        "step": "kyc_done",
        "result": {
            "status": overall_status,
            "match_score": overall_match_score,
            "flags": aggregated_flags,
            "metadata": {
                "documents": document_results,
                "user": {"full_name": user_data.get("full_name"), "dob": user_data.get("dob")},
            },
        },
    }

    publish(redis_client, ORCHESTRATOR_CHANNEL, orchestrator_payload)


def run() -> None:
    redis_client = redis.from_url(REDIS_URL)
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(KYC_CHANNEL)
    LOGGER.info("KYC Validator Agent listening on Redis channel '%s'", KYC_CHANNEL)

    for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        try:
            payload = json.loads(message.get("data"))
        except json.JSONDecodeError as error:
            LOGGER.error("Received invalid JSON payload: %s", error)
            continue

        if payload.get("step") != "kyc_start":
            LOGGER.debug("Ignoring message with step %s", payload.get("step"))
            continue

        handle_message(redis_client, payload)


if __name__ == "__main__":
    run()
