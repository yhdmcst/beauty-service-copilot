"""Exercise an original missing-item message on an isolated release server."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from scripts.rehearse_final_demo import EDGE, generate, select_context
from src.agents.assist_agent import AssistAgent

SESSION = "S00006"
POINT = "77241371613918.PNM"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Keep earlier UI evidence.")
    args.output.mkdir(parents=True)
    errors, checks = [], []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=EDGE, headless=True)
        try:
            for width, height in ((1440, 1000), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.on("pageerror", lambda error: errors.append(str(error)))
                assert page.request.get(args.base + "/health").json()["assistance_revision"] == AssistAgent.prompt_version
                samples = page.request.get(
                    args.base + "/api/evaluation/annotations?split=heldout").json()["samples"]
                assert all(row["status"] == "pending" for row in samples)
                select_context(page, args.base, SESSION, POINT, "replay")
                original = page.locator("#message-input").input_value()
                assert "少了洗发水" in original
                result = generate(page, args.base, SESSION)
                assert result["intent"] == "quality_issue"
                assert result["service_focus"]["category"] == "missing_items"
                assert "装箱" in result["next_action"] and "数量" in result["next_action"]
                assert "请您提供订单" not in result["suggested_reply"]
                assert "已有订单记录" in page.locator("#provided-information").text_content()
                page.locator("#provided-information").evaluate("(el) => el.parentElement.open = true")
                bounds = page.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
                assert bounds[0] <= bounds[1]
                page.screenshot(path=str(args.output / f"missing_items_{width}.png"), full_page=True)
                checks.append({
                    "width": width, "height": height, "session_id": SESSION, "analysis_point": POINT,
                    "buyer_message": original, "intent": result["intent"],
                    "focus": result["service_focus"]["category"], "next_action": result["next_action"],
                    "reply": result["suggested_reply"], "horizontal_overflow": False,
                })
                page.close()
            assert not errors
        finally:
            browser.close()
    (args.output / "item_issue_ui.json").write_text(json.dumps({
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Software UI rehearsal on original MOCK message and isolated runtime; not human quality",
        "revision": AssistAgent.prompt_version, "human_review_completed": False,
        "checks": checks, "page_errors": errors,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": len(checks), "page_errors": errors}))


if __name__ == "__main__":
    main()
