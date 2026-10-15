"""OpenAI-compatible Qwen adapter with bounded retries and usage reporting."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def configured_model(tier: str = "small") -> str:
    """Resolve actual model names independently of historical parameter-size labels."""
    if tier not in ("small", "large"):
        raise ValueError("tier must be small or large")
    legacy_key = "QWEN_MODEL_7B" if tier == "small" else "QWEN_MODEL_72B"
    fallback = "qwen2.5-7b-instruct" if tier == "small" else "qwen2.5-72b-instruct"
    return os.getenv(f"QWEN_MODEL_{tier.upper()}") or os.getenv(legacy_key) or fallback


def is_loopback_url(url: str) -> bool:
    """Restrict unauthenticated local inference to a literal loopback address."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        return False
    if parsed.hostname == "localhost":
        return True
    try:
        return ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        return False


@dataclass
class Generation:
    """Provider output and measured token usage."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str


class QwenWrapper:
    """Call explicit cloud or localhost Ollama endpoints without cross-provider fallback."""

    def __init__(
        self, model_name: str | None = None, client: object | None = None,
        provider: str | None = None,
    ) -> None:
        self.provider = provider or os.getenv("QWEN_PROVIDER", "openai")
        if self.provider not in ("openai", "ollama"):
            raise ValueError("QWEN_PROVIDER must be openai or ollama")
        self.model = model_name or configured_model()
        self.timeout = float(os.getenv(
            "QWEN_TIMEOUT_SECONDS", "60" if self.provider == "ollama" else "30"))
        self.max_attempts = int(os.getenv(
            "QWEN_MAX_ATTEMPTS", "1" if self.provider == "ollama" else "3"))
        if self.timeout <= 0 or not 1 <= self.max_attempts <= 3:
            raise ValueError("Timeout must be positive and max attempts must be 1-3")
        self.thinking = os.getenv("QWEN_THINKING", "false").lower() == "true"
        self.client = client
        if client is None:
            from openai import OpenAI

            local = self.provider == "ollama"
            base_url = os.getenv(
                "QWEN_API_BASE", "http://127.0.0.1:11434/v1" if local
                else "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            key = os.getenv("QWEN_API_KEY", "")
            if local and not is_loopback_url(base_url):
                raise ValueError("Ollama mode requires a loopback QWEN_API_BASE")
            if not local and (not key or key.startswith("your_")):
                raise RuntimeError("QWEN_API_KEY is not configured")
            http_client = None
            if local:
                import httpx

                http_client = httpx.Client(trust_env=False, timeout=self.timeout)
            self.client = OpenAI(
                api_key="ollama-local" if local else key, base_url=base_url,
                timeout=self.timeout, max_retries=0, http_client=http_client,
            )

    def generate_with_usage(
        self, prompt: str, max_tokens: int = 300, response_schema: dict | None = None,
    ) -> Generation:
        """Call provider with up to three attempts; preserve actual usage."""
        if not prompt.strip():
            raise ValueError("prompt is empty")
        options = {}
        if self.provider == "ollama":
            options["reasoning_effort"] = "medium" if self.thinking else "none"
            options["temperature"] = 0
        if response_schema is not None:
            options["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "assistance", "strict": True,
                                "schema": response_schema},
            }
        for attempt in range(self.max_attempts):
            try:
                result = self.client.chat.completions.create(
                    model=self.model, messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens, timeout=self.timeout, **options,
                )
                usage = result.usage
                return Generation(
                    text=result.choices[0].message.content or "",
                    input_tokens=usage.prompt_tokens if usage else 0,
                    output_tokens=usage.completion_tokens if usage else 0,
                    model=self.model,
                )
            except Exception as exc:
                logger.warning("Qwen attempt %s failed: %s", attempt + 1, type(exc).__name__)
                if attempt == self.max_attempts - 1:
                    raise
                time.sleep(0.2 * 2 ** attempt)
        raise RuntimeError("Unreachable")

    def generate_structured(
        self, prompt: str, schema: dict, max_tokens: int = 360,
    ) -> Generation:
        """Constrain output at the provider as well as validate locally."""
        return self.generate_with_usage(prompt, max_tokens, response_schema=schema)

    def generate(self, prompt: str, max_tokens: int = 300) -> str:
        """Return response text for compatibility with existing agents."""
        return self.generate_with_usage(prompt, max_tokens).text

    def close(self) -> None:
        """Release the reusable HTTP client."""
        self.client.close()
