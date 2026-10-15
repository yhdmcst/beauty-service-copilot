"""Offline evidence-capture checks; never consume a real model or human trial."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from evaluation.capture_precheck_cases import (
    PROTECTED_TABLES, RecordedQwen, capture, read_protected_records, selected_context,
)
from src.models.qwen_wrapper import Generation, QwenWrapper


def test_first_problem_is_pinned_to_historical_replay():
    calls = []

    def get_session(session_id, **options):
        calls.append((session_id, options))
        return {"message_choices": [{"id": "buyer-first"}, {"id": "buyer-thanks"}]}

    selected_context(SimpleNamespace(get_session=get_session), "S00001")
    assert calls[-1] == ("S00001", {
        "before_message_id": "buyer-first", "analysis_mode": "replay"})


def test_missing_buyer_is_not_silently_replaced_by_staff():
    data = SimpleNamespace(get_session=lambda *args: {"message_choices": []})
    with pytest.raises(ValueError, match="No buyer"):
        selected_context(data, "empty")


def test_capture_refuses_to_overwrite_first_pass_evidence(tmp_path):
    evidence = tmp_path / "reply_cases.json"
    evidence.write_text('{"first":"kept"}', encoding="utf-8")
    with pytest.raises(FileExistsError, match="Existing evidence"):
        capture(tmp_path)
    assert json.loads(evidence.read_text(encoding="utf-8")) == {"first": "kept"}


def test_read_only_fingerprint_preserves_human_rows(tmp_path):
    path = tmp_path / "evaluation.sqlite"
    db = sqlite3.connect(path)
    for table in PROTECTED_TABLES:
        db.execute(f'CREATE TABLE "{table}" (task_id TEXT, position INTEGER)')
        db.execute(f'INSERT INTO "{table}" VALUES (?, ?)', ("original", 1))
    db.commit()
    db.close()
    before, tasks = read_protected_records(path)
    after, _ = read_protected_records(path)
    assert before == after
    assert all(item["n"] == 1 for item in before.values())
    assert tasks == [{"task_id": "original", "position": 1}]


def test_raw_output_is_retained_before_draft_validation(monkeypatch):
    recorder = object.__new__(RecordedQwen)
    recorder.calls = []
    monkeypatch.setattr(
        QwenWrapper, "generate_with_usage",
        lambda *args: Generation('{"unsafe":"original"}', 10, 8, "test-model"))
    result = recorder.generate_structured("test input", {"type": "object"})
    assert result.text == '{"unsafe":"original"}'
    assert recorder.calls[0]["raw_text"] == result.text
    assert recorder.calls[0]["response_schema"] == {"type": "object"}
    assert recorder.calls[0]["input_tokens"] == 10


def test_provider_failure_is_retained(monkeypatch):
    recorder = object.__new__(RecordedQwen)
    recorder.calls = []

    def fail(*args):
        raise TimeoutError("local timeout")

    monkeypatch.setattr(QwenWrapper, "generate_with_usage", fail)
    with pytest.raises(TimeoutError):
        recorder.generate_with_usage("test input")
    assert recorder.calls[0]["error_type"] == "TimeoutError"
    assert "raw_text" not in recorder.calls[0]
