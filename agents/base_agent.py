"""Common base utilities for BankBot Crew agents."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests
from langchain_community.llms import Ollama

LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s %(levelname)s [BaseAgent] %(message)s")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format=LOG_FORMAT)
LOGGER = logging.getLogger("bankbot_base_agent")


class BaseAgent:
    """Shared scaffolding for all agents to ensure consistent interface and setup."""

    def __init__(self, model: Optional[str] = None) -> None:
        self.model_name = model or os.getenv("DEFAULT_AGENT_MODEL", "llama3")
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.enable_llm = os.getenv("ENABLE_OLLAMA", "false").lower() in {"1", "true", "yes"}
        self._llm: Optional[Ollama] = None
        self._llm_available_cache: Optional[bool] = None
        if self.enable_llm:
            try:
                self._llm = Ollama(model=self.model_name, base_url=self.base_url)
            except Exception as exc:  # pragma: no cover - initialization guard
                LOGGER.warning("Failed to initialize Ollama model %s: %s", self.model_name, exc)
                self._llm = None

    @property
    def llm(self) -> Optional[Ollama]:
        """Expose the lazily-initialised Ollama client."""
        if not self.enable_llm:
            return None
        if self._llm is None:
            try:
                self._llm = Ollama(model=self.model_name, base_url=self.base_url)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Deferred Ollama init failed for %s: %s", self.model_name, exc)
                return None
        return self._llm

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - interface definition only
        raise NotImplementedError("Subclasses must implement run() returning a JSON-serialisable dict.")

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    def is_llm_available(self, refresh: bool = False) -> bool:
        """Quickly probe the Ollama endpoint when LLM usage is enabled."""
        if not self.enable_llm:
            return False
        if refresh:
            self._llm_available_cache = None
        if self._llm_available_cache is not None:
            return self._llm_available_cache
        if not self.llm:
            self._llm_available_cache = False
            return False
        try:
            response = requests.get(f"{self.base_url.rstrip('/')}/api/tags", timeout=0.5)
            self._llm_available_cache = response.ok
            return self._llm_available_cache
        except requests.RequestException:
            self._llm_available_cache = False
            return False
