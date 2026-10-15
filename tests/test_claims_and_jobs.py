"""Business-field semantics and bounded asynchronous inference contracts."""

import threading
import time

import pytest

from src.knowledge.business_claims import check_claims
from src.orchestration.analysis_jobs import AnalysisJobs, QueueFull
from tests.test_workbench_v2 import Model, app_with


def evidence():
    return [
        {"id": "O1", "fields": {"实付金额(元)": "118", "订单状态": "待发货"}},
        {"id": "T1", "fields": {"退款金额(元)": "10", "转账状态": "待审核"}},
        {"id": "O2", "fields": {"实付金额(元)": "99", "订单状态": "已发货"}},
    ]


@pytest.mark.parametrize("text,supported", [
    ("订单O1实付118元，退款10元", True),
    ("退款118元", False), ("实付10元", False),
    ("订单O1实付99元", False),
    ("订单O2实付99元", True),
    ("退款已经完成", False), ("已退款", False),
    ("订单已发货", False), ("订单未发货", False),
    ("订单O1已发货", False), ("订单O2已发货", True),
    ("订单O1未发货", True),
    ("订单O10实付118元", False),
])
def test_money_roles_and_completion(text, supported):
    result = check_claims(text, evidence(), ["O1", "O2", "T1"])
    assert (not result["flags"]) is supported


def test_claim_requires_explicitly_cited_fields():
    assert check_claims("退款10元", evidence(), ["O1"])["flags"]
    assert check_claims("已退款", [{"id": "T1", "fields": {"转账状态": "成功"}}], ["T1"])["checks"]
    assert not check_claims("已退款", [{"id": "T1", "fields": {"转账状态": "成功"}}], ["T1"])["flags"]
    assert check_claims("已退款", [{"id": "T1", "fields": {"转账状态": "历史状态未提供"}}], ["T1"])["flags"]
    assert check_claims("订单O10已发货", evidence(), ["O2"])["flags"]
    assert check_claims("订单O10实付118元", evidence(), ["O1"])["flags"]


def test_reported_amount_is_not_treated_as_confirmed_refund_amount():
    result = check_claims(
        "用户称退款少了23.5元，订单实付118元",
        evidence(),
        ["O1"],
    )
    assert "unsupported_amount" not in result["flags"]
    reported = [item for item in result["checks"] if item["scope"] == "reported_amount"]
    assert reported and reported[0]["status"] == "reported_claim"


def test_attributed_medical_wording_is_allowed_but_unattributed_is_blocked():
    attributed = check_claims("买家称使用后出现过敏反应，需人工核实", [], [])
    assert "unsupported_medical_conclusion" not in attributed["flags"]
    assert any(item["status"] == "reported_claim" for item in attributed["checks"])

    asserted = check_claims("用户使用后出现过敏反应，需紧急处理", [], [])
    assert "unsupported_medical_conclusion" in asserted["flags"]


def test_external_delivery_observation_requires_signed_status():
    text = "我们注意到物流显示已签收，但买家说没有收到"
    assert "unsupported_external_delivery_observation" in check_claims(
        text, evidence(), ["O1"]
    )["flags"]
    signed = [{"id": "O2", "fields": {"订单状态": "已签收"}}]
    assert "unsupported_external_delivery_observation" not in check_claims(
        text, signed, ["O2"]
    )["flags"]


def test_unrecorded_execution_claim_is_blocked():
    result = check_claims("我们正在核实退款状态，稍后回复", [], [])
    assert "unsupported_execution_claim" in result["flags"]
    planned = check_claims("需要先核实物流状态，以便我们核实", [], [])
    assert "unsupported_execution_claim" not in planned["flags"]


def test_unverified_business_status_is_not_presented_as_confirmed():
    result = check_claims("尾款支付时间已确认", [], [])
    assert "unsupported_status_assertion" in result["flags"]


@pytest.mark.parametrize("text", [
    "待审核不代表已退款", "是否退款成功", "无法确认已发货", "如果退款完成再记录",
])
def test_uncertainty_and_questions_are_not_completed_action_claims(text):
    result = check_claims(text, evidence(), ["O1", "T1"])
    assert result["checks"]
    assert not result["flags"]
    assert result["checks"][0]["status"] == "not_asserted"


def await_job(jobs, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = jobs.get(job_id)
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.01)
    raise AssertionError("Fixture job did not finish")


def test_bounded_queue_and_active_duplicates():
    jobs = AnalysisJobs(workers=1, capacity=2)
    gate, began = threading.Event(), threading.Event()

    def work():
        began.set()
        assert gate.wait(3)
        return {"ok": True}

    try:
        first = jobs.submit("key1", "S1", work)
        assert began.wait(1)
        assert jobs.submit("key1", "S1", work)["job_id"] == first["job_id"]
        second = jobs.submit("key2", "S2", lambda: {"second": True})
        assert jobs.stats() == {"workers": 1, "capacity": 2, "queued": 1, "running": 1}
        with pytest.raises(QueueFull):
            jobs.submit("key3", "S3", lambda: {})
        gate.set()
        assert await_job(jobs, first["job_id"])["result"]["ok"]
        assert await_job(jobs, second["job_id"])["result"]["second"]
    finally:
        gate.set()
        jobs.close()


def test_job_failure_releases_capacity():
    jobs = AnalysisJobs(capacity=1)
    try:
        def fail():
            raise RuntimeError("fixture")

        first = jobs.submit("first", "S1", fail)
        failed = await_job(jobs, first["job_id"])
        assert failed["error"] == "RuntimeError"
        second = jobs.submit("second", "S2", lambda: {"ok": True})
        assert await_job(jobs, second["job_id"])["status"] == "completed"
    finally:
        jobs.close()


def test_http_accepts_job_without_waiting_for_model_and_saves_risk():
    gate, began = threading.Event(), threading.Event()

    class SlowModel(Model):
        def generate_with_usage(self, prompt, max_tokens=420):
            began.set()
            assert gate.wait(3)
            return super().generate_with_usage(prompt, max_tokens)

    app = app_with(SlowModel())
    jobs = app.extensions["analysis_jobs"]
    client = app.test_client()
    try:
        started = time.monotonic()
        submitted = client.post("/api/sessions/S00381/assist-jobs", json={"message": "要投诉12315"})
        assert submitted.status_code == 202
        assert time.monotonic() - started < 1
        assert began.wait(1)
        assert submitted.json["task_ids"]
        assert client.get("/api/tasks?session_id=S00381").json["tasks"]
        gate.set()
        completed = await_job(jobs, submitted.json["job"]["job_id"])
        assert completed["result"]["session_id"] == "S00381"
        assert client.get(f"/api/assist-jobs/{completed['job_id']}").json["job"]["status"] == "completed"
    finally:
        gate.set()
        jobs.close()


def test_queue_rejection_preserves_risk_provenance():
    app = app_with()
    original = app.extensions["analysis_jobs"]
    original.close()
    jobs = AnalysisJobs(capacity=1)
    app.extensions["analysis_jobs"] = jobs
    gate, began = threading.Event(), threading.Event()

    def blocking():
        began.set()
        gate.wait(3)
        return {}

    try:
        first = jobs.submit("busy", "OTHER", blocking)
        assert began.wait(1)
        response = app.test_client().post(
            "/api/sessions/S00381/assist-jobs", json={"message": "红肿呼吸困难"})
        assert response.status_code == 429 and response.json["task_ids"]
        cases = app.extensions["case_store"]
        analysis = cases.get_analysis(response.json["analysis_id"])
        assert analysis["model_status"] == "queue_full"
        assert cases.get_task(response.json["task_ids"][0])["priority"] == "critical"
        gate.set()
        await_job(jobs, first["job_id"])
    finally:
        gate.set()
        jobs.close()
