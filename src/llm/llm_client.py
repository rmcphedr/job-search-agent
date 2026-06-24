"""Ollama LLM client for structured fit scoring."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import requests
import yaml

from src.database.db import get_project_root

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = get_project_root() / "config" / "llm.yaml"
REQUEST_TIMEOUT_SECONDS = 60


class LLMClientError(Exception):
    """Raised when the LLM client cannot complete a request."""


def load_llm_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load LLM configuration from config/llm.yaml."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise LLMClientError(f"LLM config not found: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise LLMClientError(f"Failed to load LLM config from {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise LLMClientError(f"LLM config {path} must contain a YAML mapping.")

    provider = data.get("provider")
    if provider != "ollama":
        raise LLMClientError(f"Unsupported LLM provider: {provider!r}. Only 'ollama' is supported.")

    return data


class OllamaClient:
    """Client for local Ollama inference."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_llm_config()
        ollama_cfg = self.config.get("ollama", {})
        if not isinstance(ollama_cfg, dict):
            raise LLMClientError("Invalid ollama configuration block in config/llm.yaml.")

        base_url = str(ollama_cfg.get("base_url", "http://localhost:11434")).rstrip("/")
        self.base_url = base_url
        self.model = str(ollama_cfg.get("model", "qwen3:30b"))
        self.temperature = float(ollama_cfg.get("temperature", 0.1))

    def generate(self, prompt: str) -> str:
        """Generate a plain-text response from Ollama."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"temperature": self.temperature},
        }
        response_text = self._post_generate(payload)
        return response_text.strip()

    def generate_json(self, prompt: str) -> dict[str, Any]:
        """Generate and parse a JSON object from Ollama, retrying once on parse failure."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": self.temperature},
        }

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response_text = self._post_generate(payload)
                return self._parse_json_response(response_text)
            except LLMClientError as exc:
                last_error = exc
                if attempt == 0 and "Malformed JSON response" in str(exc):
                    logger.warning("JSON parse failed, retrying once.")
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise LLMClientError("Malformed JSON response")

    def _post_generate(self, payload: dict[str, Any]) -> str:
        url = f"{self.base_url}/api/generate"
        try:
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.ConnectionError as exc:
            raise LLMClientError(
                f"Unable to connect to Ollama at {self.base_url}. "
                "Ensure Ollama is running (try: ollama serve)."
            ) from exc
        except requests.Timeout as exc:
            raise LLMClientError(
                f"Timeout after {REQUEST_TIMEOUT_SECONDS} seconds waiting for Ollama."
            ) from exc
        except requests.RequestException as exc:
            raise LLMClientError(f"Ollama request failed: {exc}") from exc

        if response.status_code == 404:
            raise LLMClientError(
                f"Model not installed: {self.model}. Install it with: ollama pull {self.model}"
            )

        if not response.ok:
            detail = response.text.strip() or response.reason
            raise LLMClientError(f"Ollama API error ({response.status_code}): {detail}")

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMClientError("Malformed JSON response from Ollama API.") from exc

        response_text = body.get("response")
        if not isinstance(response_text, str):
            raise LLMClientError("Malformed JSON response: missing 'response' field.")

        return response_text

    @staticmethod
    def _parse_json_response(response_text: str) -> dict[str, Any]:
        text = response_text.strip()
        if not text:
            raise LLMClientError("Malformed JSON response: empty model output.")

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            extracted = _extract_json_object(text)
            if extracted is None:
                raise LLMClientError("Malformed JSON response: could not parse model output.")
            try:
                parsed = json.loads(extracted)
            except json.JSONDecodeError as exc:
                raise LLMClientError("Malformed JSON response: could not parse model output.") from exc

        if not isinstance(parsed, dict):
            raise LLMClientError("Malformed JSON response: expected a JSON object.")

        return parsed


def _extract_json_object(text: str) -> str | None:
    """Extract the first JSON object from text that may contain extra content."""
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match is None:
        return None
    return match.group(0)
