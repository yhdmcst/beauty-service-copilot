"""Tiered response generation restricted by evidence and risk decisions."""

from __future__ import annotations

import logging
import threading

from src.models.qwen_wrapper import QwenWrapper, configured_model
from src.optimization.cost_tracker import CostTracker
from src.optimization.smart_cache import SmartCache
from src.utils.prompt_templates import EMPATHY_PROMPT, inject

logger = logging.getLogger(__name__)

HIGH_RISK = {"allergy_reaction", "quality_issue", "refund_request", "authenticity_check"}
RULES = {
    "usage_method": "请按商品说明书的使用顺序和频率操作；若出现不适请停用，并由客服进一步核实。",
    "skin_type_match": "理解您对肤质适配的顾虑。请提供具体商品名称和配方信息，我们核实后再给您建议。",
}


class ResponseAgent:
    """Choose rule, 7B or 72B by complexity, not by arbitrary traffic quota."""

    def __init__(
        self, small_model: QwenWrapper | None = None,
        large_model: QwenWrapper | None = None,
        cache: SmartCache | None = None, tracker: CostTracker | None = None,
    ) -> None:
        self.small = small_model
        self.large = large_model
        self.cache = cache or SmartCache()
        self.tracker = tracker or CostTracker()
        self._model_lock = threading.Lock()

    def _get_model(self, strategy: str) -> QwenWrapper:
        """Reuse model clients; either tier may explicitly map to the same local model."""
        attribute = "large" if strategy == "large_model" else "small"
        with self._model_lock:
            model = getattr(self, attribute)
            if model is None:
                model = QwenWrapper(configured_model(attribute))
                setattr(self, attribute, model)
            return model

    def select_strategy(self, intent: str, docs: list[dict], query: str = "") -> str:
        """Pick smallest suitable tier; complex comparison merits larger model."""
        if intent in HIGH_RISK or intent in RULES or not docs:
            return "rule"
        return "large_model" if intent == "product_comparison" or len(query) > 120 else "small_model"

    def generate(
        self, user_input: str, intent: str, emotion: dict,
        knowledge_docs: list[dict], user_profile: dict,
        session_id: str = "", can_auto_reply: bool = False,
    ) -> dict:
        """Generate a safe draft, tracking only real model usage."""
        if not can_auto_reply or intent in HIGH_RISK:
            return {"response": "已为您转接人工客服进一步核实，请稍候。", "strategy": "handoff",
                    "confidence": 0.0, "cost_info": {}}
        verified = [doc for doc in knowledge_docs if doc.get("verified") is True]
        if not verified:
            return {"response": "已为您转接人工客服进一步核实，请稍候。", "strategy": "handoff",
                    "confidence": 0.0, "cost_info": {}}
        strategy = self.select_strategy(intent, verified, user_input)
        key = self.cache.key(user_input, intent, emotion, user_profile.get("skin_type"),
                             configured_model("large" if strategy == "large_model" else "small"),
                             [(doc.get("id"), doc.get("content")) for doc in verified[:3]])
        cached = self.cache.get(key)
        if cached:
            return {**cached, "cache_hit": True, "cost_info": self.tracker.log_inference(
                "rule", 0, 0, session_id)}
        if strategy == "rule":
            text = RULES.get(intent, "感谢您的咨询，请以已核实的商品说明为准。")
            usage = self.tracker.log_inference("rule", 0, 0, session_id)
        else:
            prompt = inject(
                EMPATHY_PROMPT, query=user_input[:500], emotion=str(emotion)[:120],
                skin_type=str(user_profile.get("skin_type", "未提供"))[:30],
                context="\n".join(doc.get("content", "")[:350] for doc in verified[:3]),
            )
            try:
                model = self._get_model(strategy)
                result = model.generate_with_usage(prompt)
                text = result.text.strip()
                usage = self.tracker.log_inference(
                    strategy, result.input_tokens, result.output_tokens, session_id)
            except Exception:
                logger.exception("Model unavailable; escalating without unsupported answer")
                return {"response": "暂时无法核实准确答复，已转接人工客服。", "strategy": "handoff",
                        "confidence": 0.0, "cost_info": {}}
        if not text or len(text) > 150 or any(word in text for word in ("保证治愈", "绝对不会过敏")):
            return {"response": "已为您转接人工客服进一步核实。", "strategy": "handoff",
                    "confidence": 0.0, "cost_info": usage}
        response = {"response": text, "strategy": strategy, "confidence": 0.85}
        self.cache.set(key, response)
        return {**response, "cost_info": usage, "cache_hit": False}
