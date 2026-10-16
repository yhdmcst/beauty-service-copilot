"""Source-bound communication needs and stated preferences for human support."""

from __future__ import annotations

import re

from src.utils.service_requests import current_request_text
from src.knowledge.provided_information import supplied_information

FOCUS_STRATEGIES = {
    "return_refund": "回应退货后退款受阻的等待，说明入库、售后原因和流水待核",
    "refund_status_or_amount": "回应款项进度或金额困扰，说明需要核实的具体差异",
    "address_change": "回应送错地址的担忧，先核配送节点和改址可行性",
    "promotion_or_gift": "回应活动预期与实收差异，先对照资格、装箱和分包",
    "authenticity_concern": "回应商品差异的疑虑，提供可核验方向，不猜真假或原因",
    "delivery_conflict": "回应签收却未收到的困扰，客服查签收证据及投递位置",
    "missing_items": "回应少件或空包带来的困扰，沿用购买及实收信息，再核装箱和分包",
    "adverse_reaction_report": "了解当前状况和处理诉求，优先人工跟进，不判断病因",
}
REPEAT_CUE = re.compile(
    r"别再问|别让我重复|重复(?:说|提供|询问)|说了(?:两|三|四|五|[2-9])遍"
    r"|(?:订单号|单号|资料|信息|照片|肤质|问题)[^。；！？\n]{0,10}"
    r"(?:已经(?:提供|给|说)|(?:给|说|提供)过|提供(?:两|三|四|五|[2-9])次)"
    r"|已经(?:提供|给|说)[^。；！？\n]{0,10}(?:订单号|单号|资料|信息|照片|肤质|问题)")
UNRESOLVED_CUE = re.compile(r"还没|未到账|没到账|没收到|一直没|收不到|退不出|又让我等|问题.{0,4}没解决")
SKIN_CUE = re.compile(
    r"(?:我是|我的肤质(?:是|为)?|我(?:属于|是个)?|本人(?:是)?)\s*"
    r"(敏感肌|敏感皮肤|混合偏油|混合偏干|油皮|干皮|油性皮肤|干性皮肤|混合肌)")


def communication_brief(context: dict, message: str, signals: dict) -> dict:
    """Never infer personality, diagnosis, product fit or an unconfirmed identity."""
    history = context.get("service_history", {})
    own = context.get("session_id") or signals.get("session_id", "")
    confirmed = set(history.get("confirmed_session_ids", [])) if history.get("identity_basis", "unconfirmed") != "unconfirmed" else set()
    rows = context.get("messages", []) + [row for row in history.get("messages", [])
                                            if row.get("session_id") in confirmed]
    point = context.get("analysis_point", "")
    cutoff = context.get("analysis_at", "")
    buyers = [
        row for row in rows if row.get("角色") == "买家"
        and row.get("message_id") != point
        and (not row.get("session_id") or row["session_id"] == own or row["session_id"] in confirmed)
        and (not cutoff or row.get("发送时间") and row["发送时间"] <= cutoff)
    ]
    buyers.sort(key=lambda row: row.get("发送时间", ""))
    current = {
        "message_id": point, "发送时间": cutoff, "message_text": message,
        "session_id": signals.get("session_id", ""), "scope": "current_analysis_input",
    }
    runtime = []
    if context.get("analysis_mode") == "snapshot":
        runtime = [{**row, "scope": "local_snapshot_input"}
                   for row in context.get("runtime_inputs", [])
                   if row.get("session_id") == own and row.get("analysis_point") == point
                   and row.get("角色") == "买家"][-6:]
    buyers = buyers[-6:] + runtime + [current]
    needs, preferences, reasons = [], [], []
    seen = set()
    for row in buyers:
        text = row.get("message_text", "")
        source = {
            "message_id": row.get("message_id", ""),
            "session_id": row.get("session_id", signals.get("session_id", "")),
            "time": row.get("发送时间", ""),
            "scope": row.get("scope", "past_buyer_message"),
        }
        request = current_request_text(text)
        if REPEAT_CUE.search(request) and "repeated_information" not in seen:
            seen.add("repeated_information")
            needs.append({
                "code": "repeated_information", "label": "已提供信息，避免重复询问",
                "basis": {**source, "quote": text[:100]},
                "action": "先对照已有消息和订单字段，仅补尚缺内容",
            })
        if row is current and UNRESOLVED_CUE.search(request):
            needs.append({
                "code": "waiting_for_resolution", "label": "等待核查或处理结果",
                "basis": {**source, "quote": text[:100]},
                "action": "说明具体核查对象和反馈路径，不把礼貌致谢当作已解决",
            })
        for match in SKIN_CUE.finditer(text):
            key = ("skin_type", match[1])
            if key in seen:
                continue
            seen.add(key)
            preferences.append({
                "field": "skin_type", "label": "已自述肤质", "value": match[1],
                "basis": {**source, "quote": match[0]},
                "status": "buyer_reported_not_product_approval",
            })
    if len({item["value"] for item in preferences}) > 1:
        reasons.append("肤质自述存在不同表达，需人工核对，不自动合并")
    basic = signals.get("emotion_basic", "neutral")
    if signals.get("emotion_confidence", 0) < .90:
        reasons.append("当前情绪缺少强线索或表达间接，需结合上下文复核")
    if re.search(r"可真(?:行|厉害|会)", message):
        reasons.append("可能有反讽，不能只按字面正向词判断")
    strategy = FOCUS_STRATEGIES.get(signals.get("service_focus", {}).get("category"))
    if needs and any(item["code"] == "repeated_information" for item in needs) and \
            signals.get("service_focus", {}).get("category") != "adverse_reaction_report":
        strategy = "先回应重复说明的负担，沿用已有信息，再说清本次核查"
    if not strategy:
        strategy = {
            "angry": "回应具体不满和未解决事项，给清楚的核查下一步",
            "fearful": "回应具体担忧，确认尚缺信息和可核验依据",
            "sad": "回应预期落差，依据已有信息核查可办理路径",
            "happy": "确认消费者表达的结果，避免把礼貌话当作满意证据",
        }.get(basic, "先回应当前问题，沿用已知信息，必要时补问")
    return {
        "needs": needs[:3], "stated_preferences": preferences[:3],
        "provided_information": supplied_information(context, message, signals.get("session_id", "")),
        "strategy": strategy, "human_review_reasons": reasons[:3],
        "scope": "communication aid based on buyer statements; not diagnosis or calibrated emotional probability",
        "additional_model_calls": 0,
    }
