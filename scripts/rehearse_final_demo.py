"""Rehearse the actual recording sequence on isolated in-memory demo databases."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from src.agents.assist_agent import AssistAgent

EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
REFUND_POINT = "13694977354478.PNM"
COMPLAINT_POINT = "92900836378476.PNM"


def select_context(page, base: str, session: str, point: str, mode: str) -> None:
    page.goto(f"{base}/workbench?session={session}", wait_until="domcontentloaded")
    page.wait_for_function("!document.querySelector('#assist-btn').disabled")
    page.locator("#analysis-mode").select_option(mode)
    page.wait_for_function(
        "(mode) => document.querySelector('#analysis-mode').value === mode && !document.querySelector('#assist-btn').disabled",
        arg=mode)
    page.locator("#analysis-point").select_option(point)
    page.wait_for_function(
        "(point) => document.querySelector('#analysis-point').value === point && !document.querySelector('#assist-btn').disabled",
        arg=point)


def generate(page, base: str, session: str) -> dict:
    page.locator("#assist-btn").click()
    page.wait_for_function(
        "!document.querySelector('#use-draft').disabled && document.querySelectorAll('#trace li').length === 5",
        timeout=120000)
    analysis_id = page.locator("#analysis-record-id").text_content().split()[-1]
    saved = page.request.get(f"{base}/api/sessions/{session}/analyses").json()
    return next(item for item in saved["analyses"] if item["analysis_id"] == analysis_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    errors, scenes = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=EDGE, headless=True)
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            assert page.request.get(args.base + "/health").json()["assistance_revision"] == AssistAgent.prompt_version
            labels = page.request.get(args.base + "/api/evaluation/annotations?split=heldout").json()["samples"]
            assert all(row["status"] == "pending" for row in labels), "Use an isolated verification server."
            select_context(page, args.base, "S00381", REFUND_POINT, "snapshot")
            snapshot = page.request.get(
                f"{args.base}/api/sessions/S00381?mode=snapshot&before_message_id={REFUND_POINT}").json()
            assert len(snapshot["tickets"]) == 1
            page.screenshot(path=str(args.output / "01_snapshot_records.png"), full_page=True)
            page.locator("#analysis-mode").select_option("replay")
            page.wait_for_function(
                "!document.querySelector('#assist-btn').disabled && document.querySelector('#analysis-mode').value === 'replay'")
            replay = page.request.get(
                f"{args.base}/api/sessions/S00381?mode=replay&before_message_id={REFUND_POINT}").json()
            assert not replay["tickets"] and replay["omitted_future_records"] == 1
            refund = generate(page, args.base, "S00381")
            assert refund["service_focus"]["category"] == "return_refund"
            assert not refund["final_validation_flags"]
            assert "HV1005604873" not in refund["evidence_ids"]
            page.locator("#claim-checks").evaluate("(element) => { element.parentElement.open = true; }")
            page.screenshot(path=str(args.output / "02_refund_draft.png"), full_page=True)
            page.locator("#use-draft").click()
            page.locator("#reviewer").fill("SOFTWARE-REHEARSAL")
            page.locator("#review-reason").fill("演示链路彩排，不属于人工回复质量评估；不发送客户消息")
            page.locator("#reply-editor").fill(refund["suggested_reply"] + "核查结果确认后再反馈。")
            page.locator("#approve-reply").click()
            page.wait_for_function("document.querySelector('#review-status').textContent.includes('已保存')")
            page.locator("#create-task").click()
            page.wait_for_selector("#tasks .task")
            pending = page.locator("#tasks .task").filter(
                has=page.get_by_role("button", name="认领", exact=True)).first
            pending.get_by_role("button", name="认领", exact=True).click()
            page.locator("#task-owner").fill("SOFTWARE-REHEARSAL")
            page.locator("#task-note").fill("演示：核退货入库、售后关闭原因和退款流水")
            page.locator("#task-submit").click()
            page.wait_for_selector("button:has-text('完成任务')")
            page.locator("#tasks .task").filter(
                has=page.get_by_role("button", name="完成任务", exact=True)).first.get_by_role(
                    "button", name="完成任务", exact=True).click()
            page.locator("#task-note").fill("仅演示任务生命周期，未确认到账或执行退款")
            page.locator("#task-submit").click()
            page.wait_for_function("document.querySelector('#tasks').textContent.includes('已完成')")
            page.screenshot(path=str(args.output / "03_review_and_followup.png"), full_page=True)
            scenes.append({
                "session_id": "S00381", "analysis_point": REFUND_POINT,
                "buyer_message": replay["latest_buyer_message"],
                "at": replay["analysis_at"],
                "snapshot_ticket_n": len(snapshot["tickets"]), "replay_ticket_n": 0,
                "future_ticket_omitted": replay["omitted_future_records"],
                "analysis_id": refund["analysis_id"], "draft": refund["suggested_reply"],
                "next_action": refund["next_action"],
                "review_and_task_lifecycle_verified": True,
            })
            select_context(page, args.base, "S00076", COMPLAINT_POINT, "replay")
            assert "举报" in page.locator("#message-input").input_value()
            complaint = generate(page, args.base, "S00076")
            assert any(alert["code"] == "bad_review" for alert in complaint["rule_alerts"])
            assert complaint["risk_level"] in {"高", "紧急"}
            page.screenshot(path=str(args.output / "04_complaint_risk.png"), full_page=True)
            page.goto(args.base + "/dashboard", wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#alerts').textContent.includes('S00076')")
            alert = page.locator("#alerts article").filter(has_text="S00076").first
            assert "负责人" in alert.inner_text()
            page.screenshot(path=str(args.output / "05_risk_dashboard.png"), full_page=True)
            alert.get_by_role("link", name="打开会话与处置记录").click()
            page.wait_for_function("!document.querySelector('#assist-btn').disabled")
            risk_task = page.locator("#tasks .task").filter(
                has=page.get_by_role("button", name="认领", exact=True)).first
            risk_task.get_by_role("button", name="认领", exact=True).click()
            page.locator("#task-owner").fill("SOFTWARE-REHEARSAL")
            page.locator("#task-note").fill("待核批次与可核验渠道依据；不判断真假，不推定客户违规")
            page.locator("#task-submit").click()
            page.wait_for_selector("button:has-text('完成任务')")
            page.goto(args.base + "/dashboard", wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#alerts').textContent.includes('SOFTWARE-REHEARSAL')")
            page.screenshot(path=str(args.output / "06_risk_owned.png"), full_page=True)
            scenes.append({
                "session_id": "S00076", "analysis_point": COMPLAINT_POINT,
                "analysis_id": complaint["analysis_id"],
                "buyer_message": "批次号26A27，你查！查不出来我就去平台举报，急",
                "risk_codes": [item["code"] for item in complaint["rule_alerts"]],
                "risk_level": complaint["risk_level"],
                "dashboard_link_and_owner_verified": True,
                "risk_task_left_in_progress": True,
            })
            assert not errors, errors
            result = {
                "recorded_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "scope": "automated software rehearsal on isolated databases; NOT an actual submitted video or human evaluation",
                "assistance_revision": AssistAgent.prompt_version,
                "scene_n": len(scenes), "scenes": scenes,
                "page_errors": errors, "video_recorded": False,
            }
            (args.output / "rehearsal.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=True))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
