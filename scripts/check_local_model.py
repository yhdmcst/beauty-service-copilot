"""Verify and warm up the configured localhost model without cloud requests."""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import urlsplit
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.qwen_wrapper import QwenWrapper


def main() -> None:
    """Fail closed unless explicitly configured for the local Ollama provider."""
    load_dotenv(ROOT / ".env")
    if os.getenv("QWEN_PROVIDER") != "ollama":
        raise SystemExit("Local check requires QWEN_PROVIDER=ollama; no request was sent.")
    model = QwenWrapper()
    started = time.perf_counter()
    try:
        result = model.generate_with_usage(
            "请只回复一句中文：本地千问已就绪。", max_tokens=24)
        if not result.text.strip():
            raise RuntimeError("The model returned empty content")
        import httpx

        parsed = urlsplit(str(model.client.base_url))
        base = f"{parsed.scheme}://{parsed.netloc}"
        with httpx.Client(trust_env=False, timeout=5) as probe:
            status = probe.get(base + "/api/ps")
            status.raise_for_status()
            runtime = [
                {"model": item.get("name"), "model_bytes": item.get("size"),
                 "gpu_bytes": item.get("size_vram"), "context_length": item.get("context_length")}
                for item in status.json().get("models", [])
            ]
        print(json.dumps({
            "provider": model.provider, "model": result.model,
            "text": result.text,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "thinking_enabled": model.thinking,
            "runtime": runtime,
            "gpu_allocation_observed": any((item.get("gpu_bytes") or 0) > 0 for item in runtime),
        }, ensure_ascii=False, indent=2))
    finally:
        model.close()


if __name__ == "__main__":
    main()
