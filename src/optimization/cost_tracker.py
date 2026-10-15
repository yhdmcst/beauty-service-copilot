"""Measured token usage and configurable CNY rate accounting."""

from __future__ import annotations

import os
import threading
from collections import Counter, defaultdict
from datetime import date


class CostTracker:
    """Track actual model token usage; prices are illustrative config values."""

    def __init__(self) -> None:
        self.rates = {
            "small_model": (float(os.getenv("QWEN_7B_INPUT_CNY_PER_M", "0")),
                            float(os.getenv("QWEN_7B_OUTPUT_CNY_PER_M", "0"))),
            "large_model": (float(os.getenv("QWEN_72B_INPUT_CNY_PER_M", "0")),
                            float(os.getenv("QWEN_72B_OUTPUT_CNY_PER_M", "0"))),
        }
        self.usage: Counter = Counter()
        self.days: dict[str, float] = defaultdict(float)
        self.tokens = 0
        self.cost = 0.0
        self.sessions: set[str] = set()
        self._lock = threading.RLock()

    def log_inference(
        self, model: str, input_tokens: int, output_tokens: int, session_id: str = "",
    ) -> dict:
        """Record real provider usage, never estimates as measurements."""
        if min(input_tokens, output_tokens) < 0:
            raise ValueError("token counts must be nonnegative")
        rates = self.rates.get(model, (0.0, 0.0))
        cost = (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
        with self._lock:
            self.usage[model] += 1
            self.tokens += input_tokens + output_tokens
            self.cost += cost
            self.days[date.today().isoformat()] += cost
            if session_id:
                self.sessions.add(session_id)
        return {"model": model, "input_tokens": input_tokens,
                "output_tokens": output_tokens, "cost_cny": round(cost, 8),
                "pricing_configured": model == "rule" or rates != (0.0, 0.0)}

    def record_session(self, session_id: str) -> None:
        """Count served sessions even when the safety gate avoids model calls."""
        if session_id:
            with self._lock:
                self.sessions.add(session_id)

    def get_stats(self) -> dict:
        """Return observed totals, with explicit price configuration state."""
        with self._lock:
            return {"total_tokens": self.tokens, "total_cost_cny": round(self.cost, 6),
                    "avg_cost_per_session_cny": round(self.cost / len(self.sessions), 6)
                    if self.sessions else 0, "sessions": len(self.sessions),
                    "model_distribution": dict(self.usage), "daily_cost_cny": dict(self.days),
                    "pricing_configured": all(rate != (0, 0) for rate in self.rates.values())}
