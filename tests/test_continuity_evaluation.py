import json

import pytest

from evaluation.evaluate_five_stage import run


def protocol(tmp_path):
    target = tmp_path / "protocol.json"
    target.write_text(json.dumps({
        "scope": "engineering_fixture_not_human_gold",
        "cases": [
            {"id": "a", "message": "退款没到账",
             "intent": "refund_request", "focus": "refund_status_or_amount"},
            {"id": "b", "message": "先查物流如果找不到再退款",
             "intent": "logistics_query", "focus": "shipment_query"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return target


def test_resume_reuses_finished_prefix_without_reclassifying(tmp_path, monkeypatch):
    source = protocol(tmp_path)
    checkpoint = tmp_path / "run.checkpoint"
    first = run(source, limit=1, checkpoint=checkpoint)
    assert first["n"] == 1
    from src.agents.intent_agent import IntentAgent

    classify = IntentAgent.classify
    seen = []

    def record(self, message):
        seen.append(message)
        return classify(self, message)

    monkeypatch.setattr(IntentAgent, "classify", record)
    completed = run(source, checkpoint=checkpoint, resume=True)
    assert completed["n"] == completed["intent_matches"] == completed["focus_matches"] == 2
    assert seen == ["先查物流如果找不到再退款"]
    assert completed["rows"][0] == first["rows"][0]


def test_resume_rejects_changed_protocol_without_overwriting_checkpoint(tmp_path):
    source = protocol(tmp_path)
    checkpoint = tmp_path / "run.checkpoint"
    run(source, limit=1, checkpoint=checkpoint)
    before = checkpoint.read_bytes()
    data = json.loads(source.read_text(encoding="utf-8"))
    data["cases"][0]["message"] = "改地址"
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        run(source, checkpoint=checkpoint, resume=True)
    assert checkpoint.read_bytes() == before


def test_existing_checkpoint_is_not_silently_replaced(tmp_path):
    source = protocol(tmp_path)
    checkpoint = tmp_path / "run.checkpoint"
    run(source, checkpoint=checkpoint)
    before = checkpoint.read_bytes()
    with pytest.raises(FileExistsError):
        run(source, checkpoint=checkpoint)
    assert checkpoint.read_bytes() == before


def test_resume_rejects_excess_rows_and_missing_checkpoint(tmp_path):
    source = protocol(tmp_path)
    checkpoint = tmp_path / "run.checkpoint"
    with pytest.raises(ValueError, match="existing"):
        run(source, checkpoint=checkpoint, resume=True)
    run(source, checkpoint=checkpoint)
    with pytest.raises(ValueError, match="cases"):
        run(source, limit=1, checkpoint=checkpoint, resume=True)
    with pytest.raises(ValueError, match="nonnegative"):
        run(source, limit=-1)
