"""Rebuild auditable issue state from cutoff-visible buyer statements only."""

from __future__ import annotations

import re
import hashlib

from src.utils.service_requests import request_plan, CLAUSES, ORDER_SCOPE

RESOLUTION = re.compile(r"已(?:经)?(?:到账|收到退款)|退款到账了|(?:问题|漏液|少件|泵头).{0,4}(?:解决了|处理好了|修好了)")
UNCERTAIN_OUTCOME = re.compile(r"没|未|是否|吗|如果|假如|要是|等到|可能|预计|听说|客服说|朋友说|别人说")


def reported_outcome(text: str) -> str | None:
    """An affirmative buyer report is not a forecast or a staff promise."""
    if UNCERTAIN_OUTCOME.search(text):
        return None
    if re.search(r"(?:已(?:经)?到账|到账了|收到退款)", text) and not re.search(r"少|差", text):
        return "refund_request"
    if re.search(r"已(?:经)?收到货|收到货了|收到后", text):
        return "logistics_query"
    return None


def build_service_state(context: dict, message: str, session_id: str) -> dict:
    """No identity inference, no prior generated text, no future-state lookup.

    State is included in each stored analysis, and replay is reconstructed from
    raw messages rather than mutable 'latest' state. Resolution is buyer-reported,
    never a verified financial or order-system result.
    """
    own = context.get("session_id") or session_id
    cutoff, point = context.get("analysis_at", ""), context.get("analysis_point", "")
    history = context.get("service_history", {})
    confirmed = set(history.get("confirmed_session_ids", [])) if history.get("identity_basis", "unconfirmed") != "unconfirmed" else set()
    rows = list(context.get("messages", []))
    rows += [row for row in history.get("messages", []) if row.get("session_id") in confirmed]
    seen, buyers = set(), []
    for row in rows:
        peer = row.get("session_id") or own
        key = (peer, row.get("message_id"), row.get("message_text"))
        if key in seen or row.get("角色") != "买家" or row.get("message_id") == point:
            continue
        if peer != own and peer not in confirmed:
            continue
        if cutoff and (not row.get("发送时间") or row["发送时间"] > cutoff):
            continue
        seen.add(key)
        buyers.append({**row, "session_id": peer})
    buyers.sort(key=lambda row: (row.get("发送时间", ""), row.get("message_id", "")))
    runtime = []
    if context.get("analysis_mode") == "snapshot":
        runtime = [row for row in context.get("runtime_inputs", [])
                   if row.get("session_id") == own and row.get("analysis_point") == point
                   and row.get("角色") == "买家" and row.get("message_text")]
    buyers = buyers[-40:] + runtime[-12:] + [{"message_id": point, "message_text": message,
                             "session_id": own, "发送时间": cutoff, "current": True}]
    issues, events, review_reasons = {}, [], []
    current_items = []
    for row in buyers:
        text = row.get("message_text", "")
        plan = request_plan(text)
        if row.get("current"):
            current_items = plan["items"]
        for clause in CLAUSES.finditer(text):
            outcome = reported_outcome(clause[0])
            if not outcome or any(x["intent"] == outcome and x["quote"] == clause[0] for x in plan["items"]):
                continue
            refs = [ref[0] for ref in ORDER_SCOPE.finditer(clause[0])]
            explicit_refs = [ref for ref in refs if ref.startswith("订单")]
            matches = [x for x in issues.values() if x["intent"] == outcome
                       and (not explicit_refs or x["order_scope"] in explicit_refs)
                       and x["basis"]["session_id"] == row["session_id"] and x["status"] == "active"]
            if len(matches) == 1:
                plan["items"].append({"intent": outcome, "label": matches[0]["label"],
                    "order_scope": matches[0]["order_scope"], "status": "active", "quote": clause[0]})
            elif matches:
                review_reasons.append("解决陈述涉及多个事项，需确认对应关系")
        for candidate in plan["items"]:
            # Generic references in different sessions are never auto-linked.
            detail = ""
            if candidate["intent"] == "quality_issue":
                quote = text[candidate["cue_start"]:candidate["cue_end"]] if "cue_start" in candidate else candidate["quote"]
                detail = ("pump" if "泵头" in quote else "leak" if re.search(r"漏液|渗漏", quote)
                          else "missing" if re.search(r"少件|空包", quote) else "other")
            order_scope = candidate["order_scope"]
            if order_scope in {"这单", "这笔订单", "当前会话，订单待核"}:
                matches = [key for key in issues if key[0] == row["session_id"]
                           and key[2:] == (candidate["intent"], detail)]
                if len(matches) == 1:
                    order_scope = matches[0][1]
                elif len(matches) > 1:
                    review_reasons.append("订单指代不明确，需确认事项对应关系")
                    if RESOLUTION.search(candidate["quote"]):
                        continue
            key = (row["session_id"], order_scope, candidate["intent"], detail)
            status = candidate["status"]
            if status == "historical":
                continue
            quote = candidate["quote"]
            resolved = candidate["intent"] == reported_outcome(quote)
            if candidate["intent"] == "refund_request" and re.search(r"(?:还少|少了|还差|差额)[^。；\n]{0,12}(?:元|块|到账)", text):
                resolved = False
            if status == "active" and resolved and not UNCERTAIN_OUTCOME.search(quote):
                status = "buyer_reported_resolved"
            source = {"message_id": row.get("message_id", ""), "session_id": row["session_id"],
                      "time": row.get("发送时间", ""), "quote": quote,
                      "scope": "local_snapshot_input" if row in runtime else "cutoff_buyer_message"}
            previous = issues.get(key)
            if previous and previous["status"] == "active" and status in {"conditional", "inquiry"}:
                # A hypothetical option or a policy question does not cancel
                # an already outstanding request.
                previous["conditional_basis"] = source
                continue
            if previous and previous["status"] != status:
                events.append({"issue_id": previous["issue_id"], "intent": candidate["intent"], "from": previous["status"],
                               "to": status, "basis": source})
            issues[key] = {"issue_id": hashlib.sha256(repr(key).encode()).hexdigest()[:12],
                           "detail": detail, "intent": candidate["intent"], "label": candidate["label"],
                           "order_scope": order_scope, "status": status,
                           "basis": source, "binding_status": "unverified"}
    open_issues = [item for item in issues.values() if item["status"] in {"active", "inquiry"}]
    # A short follow-up may inherit one unambiguous open issue from this session.
    # An explicit postponement/cancellation does not inherit an old active issue.
    own_open = [item for item in open_issues if item["basis"]["session_id"] == own]
    inherited = None
    if not current_items and len(own_open) == 1 and re.search(r"还没|怎么样|进度|处理到哪|然后呢|还要等|这个问题", message):
        inherited = own_open[0]
    return {"issues": list(issues.values())[-16:], "transitions": events[-12:],
            "open_count": len(open_issues), "inherited_issue": inherited,
            "review_reasons": list(dict.fromkeys(review_reasons)),
            "analysis_at": cutoff, "scope": "buyer_reported_state_not_backend_confirmation",
            "truncated": len(rows) > 40, "additional_model_calls": 0}
