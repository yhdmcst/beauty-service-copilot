"""Explicit drafting obligations and bounded follow-up guidance, no model calls."""

from src.knowledge.provided_information import supplied_information
from src.knowledge.service_guidance import NEXT_ACTION


def response_plan(context: dict, message: str, signals: dict) -> dict:
    supplied = supplied_information(context, message, signals.get("session_id", ""))
    plan = signals.get("request_plan", {})
    active = [item for item in plan.get("items", []) if item["status"] in {"active", "inquiry"}]
    orders = [item for item in supplied if item["kind"] == "order_reference"]
    questions = []
    staff_checks = []
    if len({item["order_scope"] for item in active}) > 1:
        questions.append({"field": "order_binding", "action": "先对照已有订单，只有仍无法确定时才请买家说明各诉求对应哪笔订单",
                          "reason": "不同事项对应的订单会改变处理路径",
                          "owner": "customer_only_if_missing"})
    if not orders and signals.get("intent") in {"refund_request", "logistics_query", "order_query", "quality_issue"}:
        questions.append({"field": "order_reference", "action": "先查可关联订单，确无记录时再请买家通过安全渠道补充必要订单信息",
                          "reason": "需要定位业务记录后才能核查当前事项",
                          "owner": "customer_only_if_missing"})
    category = signals.get("service_focus", {}).get("category", "general_service")
    materials = [item for item in supplied if item["kind"] in {"reported_material", "attachment_record"}]
    conflicts = [item for item in supplied if item["status"] == "current_report_conflicts_with_prior_upload"]
    if materials:
        staff_checks.append("先核已有材料记录是否收到、可用及对应当前商品，不直接要求重发")
    if category in {"product_usability_or_damage", "missing_items", "sku_mismatch", "authenticity_concern"} and not materials:
        questions.append({"field": "product_material", "owner": "customer_only_if_missing",
                          "reason": "仅在现有描述与业务记录不足以核查商品差异时需要补充",
                          "action": "先查已有描述及附件；确无可用材料且影响核查时，再请买家补充当前问题的清晰照片"})
    if category == "adverse_reaction_report":
        questions.insert(0, {"field": "current_condition", "owner": "customer_only_if_missing",
                            "reason": "当前状况决定人工跟进的紧迫性，不能用订单追问延误",
                            "action": "先沿用已描述的当前状况，尚不清楚时仅确认现在的情况是否仍在持续或加重"})
    return {"buyer_concern": message[:160],
            "known_information": [{"label": item["label"], "value": item["value"], "status": item["status"]}
                                  for item in supplied[:8]],
            "staff_next_action": NEXT_ACTION[category],
            "staff_checks": staff_checks,
            "information_conflicts": [{"label": item["label"], "status": item["status"], "basis": item["basis"]}
                                      for item in conflicts],
            "followup_candidates": questions[:1],
            "guardrails": ["复用已有信息", "内部核查由客服负责", "仅补会影响处理路径的缺失信息", "一次最多一个关键追问"],
            "scope": "drafting_plan_not_execution", "additional_model_calls": 0}
