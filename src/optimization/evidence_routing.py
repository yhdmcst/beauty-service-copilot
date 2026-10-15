"""Zero-generation drafts only for unambiguous greetings or cited shipment events."""

from __future__ import annotations

import re
from datetime import datetime


def _past_event(value: str, analysis_at: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S") <= datetime.strptime(
            analysis_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return False


def evidence_draft(context: dict, message: str, signals: dict) -> dict | None:
    """Do not route unresolved history, negative emotions, risks or policy queries."""
    if signals["risk_level_rule"] != "low" or signals["rule_alerts"]:
        return None
    if signals.get("valence", 0) != 0:
        return None
    prior_messages = [
        row for row in (
            context.get("service_history", {}).get("messages", []) + context.get("messages", []))
        if row.get("角色") == "买家" and row.get("message_id") != context.get("analysis_point")
    ]
    if prior_messages:
        return None
    greeting = re.sub(r"[\s!?！？。,.，~～]", "", message.lower())
    if greeting in {"你好", "您好", "在吗", "有人吗", "hi", "hello", "hi在吗", "你好在吗", "您好在吗"} and not context.get("evidence"):
        return {
            "summary": "买家问候，具体服务诉求尚未提供。",
            "emotion": "中性", "emotion_basic_display": "neutral", "emotion_source": "evidence_route",
            "risk_level": "低", "evidence_ids": [],
            "missing_info": ["买家具体咨询或处理事项"],
            "suggested_reply": "您好，在的。请问需要咨询或处理什么问题？",
            "next_action": "了解具体诉求后再核对必要业务信息",
            "routing_reason": "unambiguous_greeting_no_business_claim",
        }
    if signals.get("service_focus", {}).get("category") != "shipment_query":
        return None
    if re.search(
        r"退款|退货|补发|签收|没收到|未收到|错|破|急|投诉|举报|预计|几天|什么时候"
        r"|成分|原料|酒精|疗效|功效|效果|怎么用|用法|肤质|适合|赠品|小样"
        r"|保价|尾款|价差|优惠券|折扣", message
    ):
        return None
    if not re.search(r"发货了(?:吗|没)|发没发|运单号|单号(?:多少|是|呢|[?？])", message):
        return None
    records = context.get("evidence", [])
    orders = [record for record in records if record.get("type") == "order"]
    if len(orders) != 1 or any(record.get("type") == "ticket" for record in records):
        return None
    order = orders[0]
    fields = order.get("fields", {})
    shipment, waybill = fields.get("发货时间", ""), fields.get("物流单号", "")
    if not order.get("id") or not waybill or not _past_event(shipment, context.get("analysis_at", "")):
        return None
    explicit_order = re.search(r"订单(?:号)?\s*([A-Za-z0-9_-]{5,})", message)
    if explicit_order and explicit_order[1] != order["id"]:
        return None
    return {
        "summary": f"买家询问发货及运单；订单{order['id']}有{shipment[:10]}发货记录，最新配送节点待核。",
        "emotion": "中性", "emotion_basic_display": "neutral", "emotion_source": "evidence_route",
        "risk_level": "低", "evidence_ids": [order["id"]],
        "missing_info": ["承运方最新配送轨迹"],
        "suggested_reply": (
            f"您好，订单记录显示于{shipment[:10]}发货，"
            f"{fields.get('快递公司', '承运方')}运单号为{waybill}。"
            "当前配送节点还需核对轨迹，不承诺到货时间。"),
        "next_action": "客服按运单核对最新配送轨迹后反馈",
        "routing_reason": "single_cited_past_shipment_event",
    }
