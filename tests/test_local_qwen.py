"""Local provider configuration and compatibility without live inference."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.agents.response_agent import ResponseAgent
from src.models.qwen_wrapper import QwenWrapper, configured_model, is_loopback_url


def fake_response() -> SimpleNamespace:
    """Construct the narrow completion interface used by the adapter."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="local ready"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
    )


def test_loopback_endpoint_validation():
    assert is_loopback_url("http://127.0.0.1:11434/v1")
    assert is_loopback_url("http://[::1]:11434/v1")
    assert is_loopback_url("http://localhost:11434/v1")
    assert not is_loopback_url("http://127.0.0.1.example.com/v1")
    assert not is_loopback_url("http://192.168.1.4:11434/v1")
    assert not is_loopback_url("http://secret@127.0.0.1/v1")


def test_local_requires_no_cloud_key(monkeypatch):
    monkeypatch.setenv("QWEN_API_BASE", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    with patch("openai.OpenAI") as constructor:
        model = QwenWrapper("qwen3:8b", provider="ollama")
        options = constructor.call_args.kwargs
        assert options["api_key"] == "ollama-local"
        assert options["base_url"] == "http://127.0.0.1:11434/v1"
        options["http_client"].close()
        model.close()


def test_local_rejects_remote_endpoint(monkeypatch):
    monkeypatch.setenv("QWEN_API_BASE", "https://example.com/v1")
    with pytest.raises(ValueError, match="loopback"):
        QwenWrapper("qwen3:8b", provider="ollama")


def test_cloud_still_requires_key(monkeypatch):
    monkeypatch.setenv("QWEN_API_BASE", "https://example.com/v1")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="QWEN_API_KEY"):
        QwenWrapper("qwen-cloud", provider="openai")


def test_local_disables_thinking_and_records_real_usage(monkeypatch):
    monkeypatch.setenv("QWEN_THINKING", "false")
    client = Mock()
    client.chat.completions.create.return_value = fake_response()
    model = QwenWrapper("qwen3:8b", client=client, provider="ollama")
    result = model.generate_with_usage("test", max_tokens=16)
    assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "none"
    assert result.model == "qwen3:8b"
    assert result.input_tokens == 10 and result.output_tokens == 3


def test_local_timeout_is_not_multiplied_by_retries(monkeypatch):
    monkeypatch.delenv("QWEN_MAX_ATTEMPTS", raising=False)
    client = Mock()
    client.chat.completions.create.side_effect = TimeoutError("offline")
    with pytest.raises(TimeoutError):
        QwenWrapper("qwen3:8b", client=client, provider="ollama").generate("test")
    assert client.chat.completions.create.call_count == 1


def test_tier_names_and_client_reuse(monkeypatch):
    monkeypatch.setenv("QWEN_MODEL_SMALL", "qwen3:8b")
    monkeypatch.setenv("QWEN_MODEL_LARGE", "qwen3:8b")
    assert configured_model("small") == configured_model("large") == "qwen3:8b"
    agent = ResponseAgent()
    with patch("src.agents.response_agent.QwenWrapper") as constructor:
        first = agent._get_model("small_model")
        assert agent._get_model("small_model") is first
        constructor.assert_called_once_with("qwen3:8b")
