"""Chat clients for structured fit scoring."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Protocol

import requests
import yaml

from src.database.db import get_project_root

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = get_project_root() / "config" / "llm.yaml"
OLLAMA_TIMEOUT_SECONDS = 60
OPENROUTER_TIMEOUT_SECONDS = 120
HOSTED_PROVIDERS = frozenset({"openrouter"})


class LLMClientError(Exception):
    """Raised when the LLM client cannot complete a request."""


class LLMClient(Protocol):
    """Minimum interface used by the fit scorers."""

    def generate_json(self, prompt: str) -> dict[str, Any]:
        """Return one JSON object from the model."""


def load_project_env() -> None:
    """Load the gitignored project `.env` without overriding existing variables."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(get_project_root() / ".env", override=False)


def load_llm_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load LLM configuration from config/llm.yaml."""
    load_project_env()
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
    if provider not in {"ollama", "openrouter"}:
        raise LLMClientError(
            f"Unsupported LLM provider: {provider!r}. Use 'openrouter' or 'ollama'."
        )

    return data


def build_llm_client(config: dict[str, Any] | None = None) -> LLMClient:
    """Build the client selected by config/llm.yaml."""
    resolved = config or load_llm_config()
    provider = resolved.get("provider")
    if provider == "openrouter":
        return OpenRouterClient(resolved)
    if provider == "ollama":
        return OllamaClient(resolved)
    raise LLMClientError(f"Unsupported LLM provider: {provider!r}.")


def hosted_provider(config: dict[str, Any]) -> bool:
    """Return True when a run can spend a remote API quota."""
    return str(config.get("provider") or "") in HOSTED_PROVIDERS


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
        self.timeout = int(ollama_cfg.get("timeout_seconds", OLLAMA_TIMEOUT_SECONDS))

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
                return parse_json_object(response_text)
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
            response = requests.post(url, json=payload, timeout=self.timeout)
        except requests.ConnectionError as exc:
            raise LLMClientError(
                f"Unable to connect to Ollama at {self.base_url}. "
                "Ensure Ollama is running (try: ollama serve)."
            ) from exc
        except requests.Timeout as exc:
            raise LLMClientError(
                f"Timeout after {self.timeout} seconds waiting for Ollama."
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


class OpenRouterClient:
    """Client for OpenRouter's OpenAI-compatible chat API."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_llm_config()
        remote_cfg = self.config.get("openrouter", {})
        if not isinstance(remote_cfg, dict):
            raise LLMClientError("Invalid openrouter configuration block in config/llm.yaml.")

        self.base_url = str(remote_cfg.get("base_url", "https://openrouter.ai/api/v1")).rstrip("/")
        self.model = str(remote_cfg.get("model", "nvidia/nemotron-3.5-lightning:free"))
        self.temperature = float(remote_cfg.get("temperature", 0.1))
        self.timeout = int(remote_cfg.get("timeout_seconds", OPENROUTER_TIMEOUT_SECONDS))
        self.reasoning_effort = str(remote_cfg.get("reasoning_effort", "")).strip()
        self.app_name = str(remote_cfg.get("app_name", "Job Search Agent")).strip()
        env_name = str(remote_cfg.get("api_key_env", "OPENROUTER_API_KEY")).strip() or "OPENROUTER_API_KEY"
        self.api_key_env = env_name
        self.api_key = os.environ.get(env_name, "").strip()
        if not self.api_key:
            env_path = get_project_root() / ".env"
            raise LLMClientError(
                f"{env_name} is empty. Open {env_path} and paste the key after {env_name}=."
            )

    def generate_json(self, prompt: str) -> dict[str, Any]:
        """Generate and parse a JSON object, retrying once without JSON mode if needed."""
        last_error: Exception | None = None
        for json_mode in (True, False):
            try:
                response_text = self._post_chat(prompt, json_mode=json_mode)
                return parse_json_object(response_text)
            except LLMClientError as exc:
                last_error = exc
                message = str(exc)
                if json_mode and (
                    "response_format" in message.casefold() or "Malformed JSON response" in message
                ):
                    logger.warning("OpenRouter JSON mode failed, retrying once as plain text.")
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise LLMClientError("Malformed JSON response")

    def _post_chat(self, prompt: str, *, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.app_name:
            headers["X-Title"] = self.app_name

        url = f"{self.base_url}/chat/completions"
        response = None
        for attempt in range(4):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            except requests.ConnectionError as exc:
                raise LLMClientError(f"Unable to connect to OpenRouter at {self.base_url}.") from exc
            except requests.Timeout as exc:
                raise LLMClientError(
                    f"Timeout after {self.timeout} seconds waiting for OpenRouter."
                ) from exc
            except requests.RequestException as exc:
                raise LLMClientError(f"OpenRouter request failed: {exc}") from exc
            if response.status_code != 429:
                break
            delay = 5 * (2 ** attempt)
            logger.warning("OpenRouter rate limit, retrying in %s seconds.", delay)
            time.sleep(delay)
        if response is None:
            raise LLMClientError("OpenRouter request failed before a response was received.")

        if response.status_code == 429:
            raise LLMClientError("OpenRouter rate limit reached. Wait and rerun the same command.")

        if response.status_code == 401:
            raise LLMClientError(
                f"OpenRouter rejected {self.api_key_env}. Check the key in .env at the project root."
            )

        if not response.ok:
            detail = (response.text or response.reason or "").strip()
            raise LLMClientError(f"OpenRouter API error ({response.status_code}): {detail[:500]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMClientError("Malformed JSON response from OpenRouter API.") from exc

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMClientError("Malformed JSON response: missing choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
            )
        if not isinstance(content, str):
            raise LLMClientError("Malformed JSON response: missing message content.")
        return content


def parse_json_object(response_text: str) -> dict[str, Any]:
    """Parse a JSON object from model text that may include extra wrapping."""
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
