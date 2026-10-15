"""Real single-machine bounded queue probe, isolated from human/runtime databases."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.assist_agent import AssistAgent
from src.api.app_upgraded import create_app
from src.models.qwen_wrapper import QwenWrapper
from src.ops.case_store import CaseStore
from evaluation.evaluation_center import FrozenAnnotationAgent


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    model = QwenWrapper()
    if model.provider != "ollama":
        raise SystemExit("Only localhost inference is permitted by this probe.")
    model.generate_with_usage("只回复准备完成", max_tokens=16)
    cases, evaluation = CaseStore(), FrozenAnnotationAgent(":memory:")
    app = create_app(assist_agent=AssistAgent(model), case_store=cases, evaluation_store=evaluation)
    client, jobs = app.test_client(), app.extensions["analysis_jobs"]
    rows = []
    try:
        for session in ("S00381", "S00107", "S00029"):
            started = time.perf_counter()
            response = client.post(f"/api/sessions/{session}/assist-jobs", json={
                "message": "请核实订单和工单状态，仅整理证据，不作业务承诺。"})
            if response.status_code != 202:
                raise RuntimeError(response.json)
            rows.append({"session": session, "job_id": response.json["job"]["job_id"],
                         "admission_ms": round((time.perf_counter() - started) * 1000, 2)})
        rejected = client.post("/api/sessions/S00082/assist-jobs",
                               json={"message": "用了后呼吸困难"})
        deadline = time.monotonic() + 180
        pending = {row["job_id"] for row in rows}
        while pending and time.monotonic() < deadline:
            for row in rows:
                if row["job_id"] not in pending:
                    continue
                job = jobs.get(row["job_id"])
                if job["status"] in {"completed", "failed"}:
                    row.update(status=job["status"], queue_wait_ms=job.get("queue_wait_ms"),
                               execution_ms=job.get("execution_ms"),
                               model_status=(job.get("result") or {}).get("model_status"),
                               usage=(job.get("result") or {}).get("usage"))
                    pending.remove(row["job_id"])
            time.sleep(.05)
        if pending:
            raise RuntimeError("Timed out")
        started = time.perf_counter()
        urgent = client.post("/api/sessions/S00082/assist", json={"message": "用了后呼吸困难"})
        urgent_ms = (time.perf_counter() - started) * 1000
        report = {
            "scope": "3 concurrent outstanding localhost jobs, 1 worker, capacity 3; not load P95",
            "requests": rows, "fourth_status": rejected.status_code,
            "fourth_risk_tasks_saved": len(rejected.json.get("task_ids", [])),
            "urgent": {"wall_ms": round(urgent_ms, 2), "status": urgent.status_code,
                       "model_status": urgent.json["model_status"], "usage": urgent.json["usage"]},
            "performance_endpoint": client.get("/api/performance").json,
        }
        (ROOT / "evaluation/results/queue_measurements.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True), flush=True)
    finally:
        jobs.close()
        model.close()
        cases.close()
        evaluation.close()


if __name__ == "__main__":
    main()
