import json
import os
import subprocess
from typing import Any, Dict, Optional

import requests
from requests import HTTPError, RequestException

DEFAULT_MODEL = os.getenv("ADVISOR_LLM_MODEL", "llama3")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
REQUEST_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))


def _call_ollama_http(prompt: str, model: str) -> Optional[str]:
    endpoint = f"{OLLAMA_URL.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    response = requests.post(endpoint, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return (data.get("response") or "").strip()


def _call_ollama_cli(prompt: str, model: str) -> Optional[str]:
    process = subprocess.run(
        ["ollama", "run", model],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = process.stdout.decode("utf-8").strip()
    if not output:
        output = process.stderr.decode("utf-8").strip()
    return output or None


def _parse_json_output(output: str) -> Dict[str, Any]:
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        start = output.find("{")
        end = output.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = output[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                pass
        raise


def run_llm(prompt: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Invoke a local Ollama model and return parsed JSON or error details."""
    selected_model = model or DEFAULT_MODEL

    try:
        output = _call_ollama_http(prompt, selected_model)
    except HTTPError as http_err:
        status_code = http_err.response.status_code if http_err.response else "unknown"
        details: Optional[str] = None
        if http_err.response is not None:
            try:
                payload = http_err.response.json()
                if isinstance(payload, dict):
                    details = payload.get("error") or payload.get("detail") or str(payload)
                else:
                    details = str(payload)
            except ValueError:
                details = http_err.response.text or str(http_err)
        else:
            details = str(http_err)
        return {
            "error": f"Ollama HTTP error {status_code}",
            "details": details or "Unknown error from Ollama.",
        }
    except RequestException:
        try:
            output = _call_ollama_cli(prompt, selected_model)
        except FileNotFoundError as exc:
            return {"error": f"Ollama CLI not found: {exc}"}
        except Exception as exc:  # pragma: no cover - safety net
            return {"error": f"Failed to invoke Ollama: {exc}"}

    if not output:
        return {"error": "Ollama returned an empty response."}

    try:
        return _parse_json_output(output)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON", "raw_output": output}
