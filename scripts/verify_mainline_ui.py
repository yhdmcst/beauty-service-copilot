"""Check the final service workflow on a server with isolated runtime databases."""

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    errors, screenshots = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=EDGE, headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            health = page.request.get(args.base + "/health").json()
            assert health["assistance_revision"] == AssistAgent.prompt_version
            # Stop before simulated reviews if someone supplied the user's live server.
            initial = page.request.get(args.base + "/api/evaluation/annotations?split=heldout").json()
            samples = initial.get("samples", [])
            assert samples and all(row["status"] == "pending" for row in samples)
            session = page.request.get(args.base + "/api/sessions/S00381").json()
            point = session["message_choices"][0]["id"]
            page.goto(args.base + "/workbench?session=S00381", wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#assist-btn').disabled === false")
            page.locator("#analysis-mode").select_option("replay")
            page.wait_for_function(
                "document.querySelector('#analysis-mode').value === 'replay' && !document.querySelector('#assist-btn').disabled")
            page.locator("#analysis-point").select_option(point)
            page.wait_for_function(
                "(point) => document.querySelector('#analysis-point').value === point && !document.querySelector('#assist-btn').disabled",
                arg=point)
            assert "售后" in page.locator("#message-input").input_value()
            page.locator("#assist-btn").click()
            page.wait_for_function(
                "document.querySelector('#model-badge').textContent !== '分析中' && document.querySelector('#trace li') !== null",
                timeout=120000)
            assert page.locator("#trace li").count() == 5
            assert page.locator("#communication-strategy").inner_text()
            assert "等待" in page.locator("#communication-needs").inner_text()
            assert page.locator("#communication-basis li").count() >= 1
            assert "已有订单记录" in page.locator("#provided-information").text_content()
            assert "退款" in page.locator("#next-action").inner_text()
            assert "退货" in page.locator("#next-action").inner_text()
            assert "正在核实" not in page.locator("#draft").inner_text()
            identifier = page.locator("#analysis-record-id").text_content().split()[-1]
            page.locator("#claim-checks").evaluate("(element) => { element.parentElement.open = true; }")
            image = args.output / "workbench_desktop.png"
            page.screenshot(path=str(image), full_page=True)
            screenshots.append(str(image))
            page.locator("#use-draft").click()
            page.locator("#reviewer").fill("UI-SOFTWARE-TEST")
            page.locator("#review-reason").fill("软件审核链路验收，非真实人工效果评估")
            page.locator("#reject-reply").click()
            page.wait_for_function("document.querySelector('#review-status').textContent.includes('已保存')")
            page.locator("#create-task").click()
            page.wait_for_selector("#tasks .task")
            task = page.locator("#tasks .task").filter(
                has=page.get_by_role("button", name="认领", exact=True)).first
            task.get_by_role("button", name="认领", exact=True).click()
            page.locator("#task-owner").fill("UI-SOFTWARE-TEST")
            page.locator("#task-note").fill("软件任务认领验收")
            page.locator("#task-submit").click()
            page.wait_for_selector("button:has-text('完成任务')")
            task = page.locator("#tasks .task").filter(
                has=page.get_by_role("button", name="完成任务", exact=True)).first
            task.get_by_role("button", name="完成任务", exact=True).click()
            page.locator("#task-note").fill("软件闭环验收，未执行实际业务")
            page.locator("#task-submit").click()
            page.wait_for_function("document.querySelector('#tasks').textContent.includes('已完成')")
            viewport_checks = []
            for path in ("/workbench?session=S00381", "/dashboard", "/evaluation"):
                mobile = browser.new_page(viewport={"width": 390, "height": 844})
                mobile.on("pageerror", lambda error: errors.append(str(error)))
                mobile.goto(args.base + path, wait_until="domcontentloaded")
                if path.startswith("/workbench"):
                    mobile.wait_for_selector(".session-item")
                    mobile.wait_for_function("!document.querySelector('#assist-btn').disabled")
                    mobile.locator("#analysis-mode").select_option("replay")
                    mobile.wait_for_function("!document.querySelector('#assist-btn').disabled")
                    mobile.locator("#analysis-point").select_option(point)
                    mobile.wait_for_function("!document.querySelector('#assist-btn').disabled")
                    mobile.locator("#assist-btn").click()
                    mobile.wait_for_function(
                        "document.querySelectorAll('#trace li').length === 5", timeout=120000)
                elif path == "/evaluation":
                    mobile.wait_for_selector(".ev-sample")
                else:
                    mobile.wait_for_function("document.querySelector('#connection').textContent !== '连接中'")
                width, viewport = mobile.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
                assert width <= viewport, (path, width, viewport)
                name = "workbench" if path.startswith("/workbench") else path.strip("/")
                image = args.output / f"{name}_mobile.png"
                mobile.screenshot(path=str(image), full_page=True)
                screenshots.append(str(image))
                viewport_checks.append({"page": path, "viewport": viewport, "content_width": width})
                mobile.close()
            assert not errors, errors
            result = {
                "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "scope": "software UI only; isolated in-memory runtime databases; NOT human assessment or efficiency",
                "assistance_revision": health["assistance_revision"],
                "analysis_id": identifier, "page_errors": errors,
                "desktop_generation": True, "review_recording": True,
                "task_lifecycle": True, "mobile_checks": viewport_checks,
                "screenshots": screenshots,
            }
            (args.output / "ui_verification.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=True))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
