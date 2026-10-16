import json

import pytest

from evaluation.evaluate_five_stage import run


def test_checkpoint_survives_interruption_and_resumes(monkeypatch, tmp_path):
    from evaluation import evaluate_five_stage as evaluation
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"scope": "engineering", "cases": [
        {"id": str(i), "message": "退款没到账", "intent": "refund_request",
         "focus": "refund_status_or_amount"} for i in range(3)]}))
    checkpoint = tmp_path / "checkpoint.json"
    original = evaluation.IntentAgent.classify
    calls = []
    def interrupt(self, message):
        calls.append(message)
        if len(calls) == 2:
            raise KeyboardInterrupt()
        return original(self, message)
    monkeypatch.setattr(evaluation.IntentAgent, "classify", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run(protocol, checkpoint=checkpoint)
    assert len(json.loads(checkpoint.read_text())["rows"]) == 1
    monkeypatch.setattr(evaluation.IntentAgent, "classify", original)
    result = run(protocol, checkpoint=checkpoint, resume=True)
    assert result["n"] == result["intent_matches"] == 3
    saved = json.loads(checkpoint.read_text()); saved["revision"] = "wrong"
    checkpoint.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="mismatch"):
        run(protocol, checkpoint=checkpoint, resume=True)


def test_model_configuration_change_cannot_reuse_checkpoint(monkeypatch, tmp_path):
    from evaluation import evaluate_five_stage as evaluation
    class Assistant:
        prompt_version = "fixture-revision"
        def __init__(self, **kwargs):
            pass
        def assist(self, *args):
            return {"intent": "refund_request", "service_focus": {"category": "refund_status_or_amount"},
                    "model_status": "local_qwen", "usage": {"input_tokens": 10, "output_tokens": 5}}
    monkeypatch.setattr(evaluation, "AssistAgent", Assistant)
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"scope": "engineering", "cases": [
        {"id": "one", "message": "退款没到账", "intent": "refund_request", "focus": "refund_status_or_amount"}]}))
    checkpoint = tmp_path / "checkpoint.json"
    monkeypatch.setenv("QWEN_MODEL_SMALL", "fixture-a")
    monkeypatch.setenv("QWEN_API_KEY", "fixture-secret-not-for-output")
    result = run(protocol, model=True, checkpoint=checkpoint)
    assert result["generated_n"] == 1 and result["generated_p50_ms"] is not None
    assert "fixture-secret-not-for-output" not in checkpoint.read_text()
    monkeypatch.setenv("QWEN_MODEL_SMALL", "fixture-b")
    with pytest.raises(ValueError, match="mismatch"):
        run(protocol, model=True, checkpoint=checkpoint, resume=True)


def test_invalid_protocol_cannot_silently_duplicate_results(tmp_path):
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"scope": "engineering", "cases": [{"id": "same"}, {"id": "same"}]}))
    with pytest.raises(ValueError, match="unique"):
        run(protocol)
    with pytest.raises(ValueError, match="nonnegative"):
        run(protocol, limit=-1)
