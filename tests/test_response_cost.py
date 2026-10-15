"""Tier selection, cost accounting and caching tests."""

from types import SimpleNamespace

from src.agents.response_agent import ResponseAgent
from src.optimization.cost_tracker import CostTracker
from src.optimization.smart_cache import SmartCache
from src.models.qwen_wrapper import QwenWrapper


class FakeModel:
    """Deterministic fake, not a claim that Qwen was contacted."""

    def __init__(self):
        self.calls = 0

    def generate_with_usage(self, prompt: str):
        self.calls += 1
        return SimpleNamespace(text="理解您的担心，已核实这款产品的用法。", input_tokens=100, output_tokens=20)


def test_response_cache_and_usage(monkeypatch):
    monkeypatch.setenv("QWEN_7B_INPUT_CNY_PER_M", "1")
    monkeypatch.setenv("QWEN_7B_OUTPUT_CNY_PER_M", "2")
    model = FakeModel()
    agent = ResponseAgent(small_model=model, cache=SmartCache(), tracker=CostTracker())
    docs = [{"id": "abc", "title": "使用说明", "content": "已审核说明", "verified": True}]
    args = dict(user_input="效果怎么样", intent="effect_inquiry", emotion={},
                knowledge_docs=docs, user_profile={}, can_auto_reply=True, session_id="one")
    first = agent.generate(**args)
    second = agent.generate(**args)
    assert first["strategy"] == "small_model" and second["cache_hit"]
    assert model.calls == 1 and agent.tracker.get_stats()["total_tokens"] == 120
    assert agent.tracker.get_stats()["total_cost_cny"] == 0.00014
    assert agent.cache.stats()["hit_rate"] == 0.5
    assert agent.generate(**{**args, "can_auto_reply": False})["strategy"] == "handoff"


def test_cache_ttl_and_unknown_price():
    cache = SmartCache(ttl=0)
    cache.set("x", "value")
    assert cache.get("x") is None
    tracker = CostTracker()
    assert tracker.log_inference("rule", 0, 0)["cost_cny"] == 0
    assert not tracker.get_stats()["pricing_configured"]


def test_qwen_compatible_response_contract():
    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=8)
    choice = SimpleNamespace(message=SimpleNamespace(content="您好"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(usage=usage, choices=[choice]))))
    result = QwenWrapper(model_name="fake-qwen", client=client).generate_with_usage("测试")
    assert (result.text, result.input_tokens, result.output_tokens) == ("您好", 12, 8)
