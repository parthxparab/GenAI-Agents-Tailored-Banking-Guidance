import requests
from typing import Any, Dict, Optional

BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 15


class APIClientError(RuntimeError):
    """Raised when the backend returns an unexpected response or fails."""


def _handle_response(response: requests.Response) -> Dict[str, Any]:
    """Raise for status and return JSON payload."""
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:  # pragma: no cover - defensive
        raise APIClientError("Backend returned a non-JSON response.") from exc


def start_onboarding(user_id: str) -> Dict[str, Any]:
    payload = {"user_id": user_id}
    response = requests.post(
        f"{BASE_URL}/onboarding/start",
        json=payload,
        timeout=DEFAULT_TIMEOUT,
    )
    return _handle_response(response)


def upload_kyc(user_id: str, file_obj, task_id: Optional[str] = None) -> Dict[str, Any]:
    if not task_id:
        raise APIClientError("task_id is required for KYC upload.")
    file_bytes = file_obj.getvalue()
    files = {
        "file": (file_obj.name, file_bytes, file_obj.type or "application/octet-stream"),
    }
    data = {"user_id": user_id}
    if task_id:
        data["task_id"] = task_id
    response = requests.post(
        f"{BASE_URL}/kyc/upload",
        files=files,
        data=data,
        timeout=DEFAULT_TIMEOUT,
    )
    return _handle_response(response)


def get_advice(user_id: str, query: str) -> Dict[str, Any]:
    payload = {"user_id": user_id, "query": query}
    response = requests.post(
        f"{BASE_URL}/product/advice",
        json=payload,
        timeout=DEFAULT_TIMEOUT,
    )
    return _handle_response(response)


def support_query(user_id: str, query: str) -> Dict[str, Any]:
    payload = {"user_id": user_id, "query": query}
    response = requests.post(
        f"{BASE_URL}/support/query",
        json=payload,
        timeout=DEFAULT_TIMEOUT,
    )
    return _handle_response(response)


def health_check() -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None
