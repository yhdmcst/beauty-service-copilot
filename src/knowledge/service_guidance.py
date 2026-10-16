"""Operational checks for assistance drafts, not business execution or medical triage."""

from __future__ import annotations

import re

from src.risk.beauty_risk_rules import detect_risks, is_active_keyword
from src.utils.service_requests import primary_request_text, request_plan
from src.utils.service_issue_cues import reported_item_issues
from src.knowledge.provided_information import supplied_information


FOCUS = {
    "adverse_reaction_report": (
        "用后不适是买家自述，先人工核当前状况，不诊断或推定产品因果",
        ["当前状况", "商品/使用时间", "处理诉求"],
    ),
    "return_refund": (
        "退货后的退款受阻，仓库签收不是买家收货，需核售后流程",
        ["退货入库/签收记录", "售后关闭原因", "退款流水"],
    ),
    "refund_status_or_amount": (
        "退款进度/差额待核，实付、退款、费用和自述金额分开",
        ["退款流水/明细", "费用拆分/原支付去向", "反馈进度"],
    ),
    "address_change": (
        "改址请求不是改址成功，需结合物流节点核可行性",
        ["配送节点", "拦截/改址可行性", "安全渠道核对新地址"],
    ),
    "pre_sale_payment": (
        "尾款窗口按订单页及活动规则，不能把定金记录当尾款时间",
        ["定金记录", "活动支付窗口", "未提供时继续核实"],
    ),
    "product_usability_or_damage": (
        "先核商品问题与售后诉求，不预判物流责任",
        ["商品问题/现有材料", "订单/出库核查", "协商处理"],
    ),
    "promotion_or_gift": (
        "对照买家所述活动、订单赠品和资格，装箱/分包由客服核查",
        ["购买时活动/资格", "订单赠品", "装箱/分包记录"],
    ),
    "missing_items": (
        "买家所述少件/空包与物流送达分开，客服先核实收情况和出库装箱",
        ["已知购买/实收数量", "订单与装箱出库", "分包及处理反馈"],
    ),
    "authenticity_concern": (
        "气味或颜色差异不证实真假或批次原因",
        ["规格/批次", "可核验渠道依据", "反馈核查结果"],
    ),
    "sku_mismatch": (
        "订单规格和买家所述实收规格分开，不重复问已说过的色号",
        ["订单规格", "实收底标/现有材料", "出库记录"],
    ),
    "delivery_conflict": (
        "签收为买家说法时保留归属，签收不等于本人收货",
        ["承运方签收凭证/投递位置", "代收信息", "客服反馈"],
    ),
    "shipment_query": (
        "已有发货时间/运单直接引用记录，最新配送节点未知就核查",
        ["已有发货/运单", "承运方当前轨迹", "反馈"],
    ),
    "general_service": (
        "定位当前主诉求，引用已有记录，信息不足再问",
        ["当前问题", "关联证据", "人工下一步"],
    ),
}

NEXT_ACTION = {
    "adverse_reaction_report": "人工优先核当前状况、使用商品/时间和处理诉求，记录跟进",
    "return_refund": "客服核退货入库、售后关闭原因及退款流水，反馈可办理路径",
    "refund_status_or_amount": "客服核退款流水、费用明细及原支付去向，反馈查得进度",
    "address_change": "客服核配送节点及拦截/改址可行性，经安全渠道核对新地址",
    "pre_sale_payment": "客服核对应预售活动尾款窗口及订单提示，未确认继续跟进",
    "product_usability_or_damage": "核商品问题及现有材料，对照订单/出库记录后协商售后",
    "missing_items": "客服对照购买和实收数量，查出库装箱及分包记录，反馈处理方案",
    "promotion_or_gift": "客服对照活动资格与订单赠品，核装箱/分包记录后反馈",
    "authenticity_concern": "客服核商品规格/批次与可核验渠道依据，不预判真假",
    "sku_mismatch": "客服对照订单规格、实收底标和出库记录，核实后协商处理",
    "delivery_conflict": "客服向承运方核签收凭证和投递位置，核有无代收后反馈",
    "shipment_query": "客服核已有发货/运单记录及最新配送轨迹后反馈",
    "general_service": "核对当前诉求和关联记录，确认后续处理事项",
}

REPLIES = {
    "adverse_reaction_report": "用后不舒服，确实会让人担心。您现在的情况还好吗，也请告诉我们您希望怎样处理。您提到的使用情况需要优先人工跟进，商品和使用时间还有不清楚的地方，再请您补充。",
    "return_refund": "退货后还没拿到退款，难怪您着急。需要先核对退货入库、售后关闭原因和退款流水，确认卡在哪一步，再向您说明处理办法。",
    "refund_status_or_amount": "退款金额或进度和预期不一致，这笔款需要查清楚。需要核对退款流水、费用明细和原支付去向，确认后再向您解释差异。",
    "address_change": "地址填错了，确实需要尽快确认。能否改址还要看包裹当前的配送节点，新地址请通过订单指定的安全渠道核对，确认结果后再反馈。",
    "pre_sale_payment": "您问的这笔预售尾款时间，当前记录里还没有明确窗口。需要对照活动规则和订单提示，确认开始、结束时间后再告诉您。",
    "product_usability_or_damage": "收到的商品不能正常使用，确实影响体验。需要先对照您反馈的问题、已有材料和订单记录；照片还缺的话再请您补充，核实后协商售后。",
    "missing_items": "您反馈收到的件数不对，这项需要查清楚。已有订单信息先沿用，由客服核对购买与实收数量、出库装箱和分包记录，确认后再反馈处理方案。",
    "promotion_or_gift": "赠品没有收到，您关心的这项需要查清楚。需要对照购买时的活动资格、订单赠品以及装箱和分包记录，确认后再与您沟通处理。",
    "authenticity_concern": "商品和您熟悉的气味或颜色不一样，担心真伪可以理解。原因目前还不能确定，需要核对规格、批次和可核验的渠道资料，再向您反馈。",
    "sku_mismatch": "收到的规格和购买的不一致，确实影响使用。需要对照订单、您已经反馈的实收情况和出库记录；底标照片还缺的话再请您补充，核实后协商处理。",
    "delivery_conflict": "物流显示签收，您却没收到，确实让人着急。需要由客服向承运方核对签收凭证、投递位置和代收情况，查清后再反馈。",
    "shipment_query": "您好，需要按订单发货记录和运单核对最新配送轨迹，确认后再向您反馈。",
}

# Only repair a concrete omission; valid model prose is left intact.
ACTION_REQUIREMENTS = {
    "adverse_reaction_report": (("当前", "现状", "状况"), ("诉求", "希望", "处理")),
    "return_refund": (("退货", "入库", "仓库"), ("售后", "关闭"), ("退款", "流水")),
    "refund_status_or_amount": (("退款", "流水"), ("明细", "费用", "渠道", "支付")),
    "address_change": (("节点", "配送", "物流"), ("改址", "拦截", "修改地址")),
    "pre_sale_payment": (("尾款", "支付窗口"), ("活动", "规则", "订单提示")),
    "product_usability_or_damage": (("商品", "泵头", "破损", "损坏"), ("材料", "售后", "协商")),
    "missing_items": (("数量", "实收", "件数"), ("装箱", "出库"), ("分包", "处理", "反馈")),
    "promotion_or_gift": (("活动", "资格"), ("赠品",), ("装箱", "出库", "分包")),
    "authenticity_concern": (("批次", "规格"), ("渠道", "依据", "来源")),
    "sku_mismatch": (("订单", "规格"), ("底标", "包装", "出库")),
    "delivery_conflict": (("承运", "快递"), ("凭证", "投递", "代收")),
}


def service_focus(message: str, intent: str) -> dict:
    alerts = detect_risks(message)
    adverse = any(item["code"] == "allergy" for item in alerts) or any(
        is_active_keyword(message, term)
        for term in ("脸肿", "肿了", "接触性皮炎")
    )
    message = primary_request_text(message)
    item_issues = reported_item_issues(message)
    damage = any(issue["category"] == "product_usability_or_damage" for issue in item_issues)
    missing = any(issue["category"] == "missing_items" for issue in item_issues)
    gift_context = any(cue in message for cue in ("赠品", "小样", "赠送", "活动", "买一送一"))
    if adverse:
        category = "adverse_reaction_report"
    elif any(word in message for word in ("退款", "退钱", "退的款", "退的钱")) and (
        re.search(r"(?:少了?|差了?)\s*\d", message) or "差额" in message
    ):
        category = "refund_status_or_amount"
    elif "退货" in message and any(term in message for term in ("退款", "售后", "退不出", "钱")):
        category = "return_refund"
    elif ("地址" in message and any(term in message for term in ("改", "填错", "错误", "转寄"))) or "改址" in message:
        category = "address_change"
    elif "尾款" in message or ("预售" in message and any(term in message for term in ("付", "定金"))):
        category = "pre_sale_payment"
    elif any(term in message for term in ("退款", "退钱", "到账", "退不出", "少款")) or re.search(
        r"退的(?:钱|款)|钱.{0,4}没回来|(?:给我|帮我|还是)退了", message
    ):
        category = "refund_status_or_amount"
    elif damage:
        category = "product_usability_or_damage"
    elif missing and not gift_context:
        category = "missing_items"
    elif gift_context or any(is_active_keyword(message, term) for term in ("漏发",)):
        category = "promotion_or_gift"
    elif any(term in message for term in ("真假", "假货", "假的", "正品", "专柜", "批次")):
        category = "authenticity_concern"
    elif any(term in message for term in ("色号", "颜色", "错色", "发错")) or re.search(r"#\s*\d+", message):
        category = "sku_mismatch"
    elif any(term in message for term in ("签收", "没收到", "未收到", "物流显示")):
        category = "delivery_conflict"
    elif any(term in message for term in ("发货", "运单", "单号", "快递到", "物流")) or intent == "logistics_query":
        category = "shipment_query"
    else:
        category = "general_service"
    issue, checks = FOCUS[category]
    return {"category": category, "current_issue": issue, "must_check": checks}


def cited_order(context: dict, ids: list[str]) -> dict | None:
    orders = [item for item in context.get("evidence", [])
              if item.get("type") == "order" and item["id"] in ids]
    return orders[0] if len(orders) == 1 else None


def _review_guidance(draft: dict, context: dict, message: str, focus: dict) -> dict:
    """Return bounded quality issues with optional context-grounded corrections."""
    category = focus.get("category", "general_service")
    plan = request_plan(message)
    active = [item for item in plan["items"] if item["status"] in {"active", "inquiry"}]
    if category != "adverse_reaction_report" and len({item["order_scope"] for item in active}) > 1:
        # No reliable mapping from demonstratives to supplied order records.
        # Never let a single cited order silently cover two different requests.
        requests = list(dict.fromkeys(f"{item['order_scope']}：{item['label']}" for item in active))
        description = "；".join(requests)
        corrected = {
            "summary": f"买家提出不同订单的事项：{description}，对应订单待核。",
            "suggested_reply": f"您提到的事项需要分开处理：{description}。先对照已有订单记录确认对应关系，只补充尚不明确的信息，再分别核查可办理路径。",
            "next_action": "客服对照已有订单确认各诉求的对应关系，再逐项核查处理路径",
            "missing_info": list(dict.fromkeys(draft.get("missing_info", []) + ["不同订单指代与具体订单的对应关系"]))[:5],
        }
        return {"issues": [{"field": field, "code": "multiple_order_binding_unconfirmed"}
                           for field, value in corrected.items() if draft.get(field) != value],
                "changes": {field: value for field, value in corrected.items() if draft.get(field) != value}}
    reply, action = draft["suggested_reply"], draft["next_action"]
    issues, changes = [], {}
    requirements = ACTION_REQUIREMENTS.get(category, ())
    if any(not any(word in action for word in group) for group in requirements):
        issues.append({"field": "next_action", "code": "service_action_incomplete"})
        changes["next_action"] = NEXT_ACTION[category]

    asks_for_record = re.search(
        r"(?:请您|烦请|麻烦您|能否|请提供|请问您|您是否)[^。；！？\n]{0,30}"
        r"(?:提供|发送|补充)?[^。；！？\n]{0,10}"
        r"(?:签收凭证|签收详情|装箱单|装箱记录|出库记录|退款流水)",
        reply,
    )
    if asks_for_record:
        issues.append({"field": "suggested_reply", "code": "internal_record_requested_from_buyer"})
        changes["suggested_reply"] = REPLIES.get(category, "需要由客服核查相关业务记录，再确认处理方案。")
    has_order = any(item.get("type") == "order" and item.get("id") for item in context.get("evidence", []))
    if has_order and re.search(
        r"(?:请您|麻烦您|能否|可|请|需要)[^。；\n]{0,12}"
        r"(?:提供|告知|填写)[^。；\n]{0,8}订单(?:号|信息)", reply
    ):
        issues.append({"field": "suggested_reply", "code": "known_order_requested_again"})
        changes["suggested_reply"] = REPLIES.get(category, "已有订单记录，需要客服核对当前问题后再确认处理。")
    if category == "sku_mismatch" and re.search(r"#\s*\d+", message) and re.search(
        r"(?:提供|告知|告诉|请问)[^。；\n]{0,15}(?:色号|颜色)", reply
    ):
        issues.append({"field": "suggested_reply", "code": "known_variant_requested_again"})
        changes["suggested_reply"] = REPLIES[category]
    if category == "return_refund" and re.search(
        r"麻烦(?:您)?[^。；\n]{0,10}核实[^。；\n]{0,20}(?:入库|售后)", reply
    ):
        issues.append({"field": "suggested_reply", "code": "after_sales_work_shifted_to_buyer"})
        changes["suggested_reply"] = REPLIES[category]
    unsupported_cause = re.search(
        r"(?:可能(?:是|由于|因|由)?|是由于|属于|源于|因为|由于)"
        r"[^。；！？\n]{0,24}(?:批次|包装|运输|环境|温度)"
        r"|(?:批次|包装|运输|环境|温度)[^。；！？\n]{0,12}(?:导致|造成|引起)",
        reply,
    )
    cause_asserted = bool(unsupported_cause and not re.search(
        r"(?:不能|无法|尚未|未能)(?:确认|判断|确定)[^。；！？\n]{0,20}$"
        r"|(?:先|需|需要)(?:核实|核对|核查|确认)[^。；！？\n]{0,20}$",
        reply[:unsupported_cause.start()],
    ))
    if category == "authenticity_concern" and cause_asserted:
        issues.append({"field": "suggested_reply", "code": "batch_explanation_not_verified"})
        changes["suggested_reply"] = REPLIES[category]
    if category == "product_usability_or_damage" and cause_asserted:
        issues.append({"field": "suggested_reply", "code": "damage_cause_not_verified"})
        changes["suggested_reply"] = REPLIES[category]
    if category == "shipment_query" and re.search(
        r"(?:麻烦您|建议您|请您|您自行)[^。；\n]{0,10}"
        r"(?:查|看|核对)[^。；\n]{0,8}(?:物流|配送|签收)", reply
    ):
        issues.append({"field": "suggested_reply", "code": "tracking_work_shifted_to_buyer"})
        changes["suggested_reply"] = REPLIES[category]
    if category == "product_usability_or_damage" and re.search(
        r"是否[^。；\n]{0,12}(?:完好|正常)|先[^。；\n]{0,12}(?:物流|签收)", reply
    ):
        issues.append({"field": "suggested_reply", "code": "reported_defect_not_addressed"})
        changes["suggested_reply"] = REPLIES[category]
    if category == "adverse_reaction_report" and (
        not any(term in reply for term in ("当前", "状况", "现状", "现在"))
        or "是否已联系客服" in reply
    ):
        issues.append({"field": "suggested_reply", "code": "current_condition_not_addressed"})
        changes["suggested_reply"] = REPLIES[category]

    provided = supplied_information(context, message, context.get("session_id", ""))
    materials = {
        item["value"] for item in provided
        if item["kind"] == "reported_material"
        and item["status"] == "buyer_reported_upload_unverified"
    }
    candidate = changes.get("suggested_reply", reply)
    for material in sorted(materials):
        pattern = re.compile(
            rf"(?:请您|请|麻烦您|烦请|能否|需要您)[^。；！？\n]{{0,16}}"
            rf"(?:提供|发送|上传|补充)[^。；！？\n]{{0,12}}{re.escape(material)}"
        )
        replaced = False
        for match in list(pattern.finditer(candidate))[::-1]:
            start = max((candidate.rfind(mark, 0, match.start()) for mark in "。；！？\n"), default=-1) + 1
            previous = candidate[start:match.start()]
            if re.search(r"若|如果|如未|还缺|尚缺|不清|找不到|无法找到", previous):
                continue
            end = min((position for mark in "。；！？\n"
                       if (position := candidate.find(mark, match.end())) >= 0), default=len(candidate))
            if end < len(candidate):
                end += 1
            candidate = (
                candidate[:start] + f"您提到已提供{material}，先核材料是否收到及可用，"
                "确有缺失或不清晰再补充。" + candidate[end:]
            )
            replaced = True
        if replaced:
            issues.append({"field": "suggested_reply", "code": "reported_material_requested_again"})
            changes["suggested_reply"] = candidate

    order = cited_order(context, draft["evidence_ids"])
    fields = order.get("fields", {}) if order else {}
    if category == "promotion_or_gift" and fields.get("赠品") and fields["赠品"] not in message:
        # Different wording is a possible discrepancy, not proof of a wrong gift.
        summary = f"买家反馈赠品问题；订单赠品字段为{fields['赠品']}，与买家所述活动的对应关系待核实。"
        if fields["赠品"] not in draft["summary"]:
            issues.append({"field": "summary", "code": "gift_evidence_not_compared"})
            changes["summary"] = summary
    if category == "pre_sale_payment" and fields.get("付款时间", "").endswith("（定金）") and "定金" not in draft["summary"]:
        issues.append({"field": "summary", "code": "deposit_record_not_used"})
        changes["summary"] = "买家咨询预售尾款窗口；订单有定金付款记录，尾款支付窗口待核对应活动规则。"
    if category == "shipment_query" and fields.get("发货时间") and fields.get("物流单号"):
        shipped = fields["发货时间"]
        at = context.get("analysis_at", "")
        if at and shipped <= at and (
            fields["物流单号"] not in reply or "suggested_reply" in changes
        ):
            issues.append({"field": "suggested_reply", "code": "available_shipment_record_not_used"})
            changes["suggested_reply"] = (
                f"您好，订单记录显示于{shipped[:10]}发货，"
                f"{fields.get('快递公司', '物流')}运单号为{fields['物流单号']}。"
                "最新配送节点需再核承运方轨迹，不承诺到货时间。"
            )
        if at and shipped <= at:
            changes.setdefault("next_action", NEXT_ACTION["shipment_query"])
    return {"issues": issues, "changes": changes}


LOCAL_REPAIRS = {
    "internal_record_requested_from_buyer": "相关内部业务记录由客服核查，再向您反馈。",
    "known_order_requested_again": "已有订单信息先沿用，仅补尚不明确的信息。",
    "known_variant_requested_again": "先对照您已说明的色号和订单规格，确有缺失再补充。",
    "after_sales_work_shifted_to_buyer": "退货入库、售后关闭原因和退款流水由客服核查。",
    "batch_explanation_not_verified": "差异原因目前尚不能确定，需要客服核对规格、批次和渠道依据。",
    "damage_cause_not_verified": "损坏原因尚待核实，由客服对照已有材料和出库记录继续核查。",
    "tracking_work_shifted_to_buyer": "最新配送轨迹由客服按已有运单核查后反馈。",
    "reported_defect_not_addressed": "先对照您反馈的商品问题和现有材料，再由客服核查售后路径。",
}


def review_guidance(draft: dict, context: dict, message: str, focus: dict) -> dict:
    """Repair affected sentences while retaining sound context and empathy.

    Severe safety, multiple-order, and evidence-specific rewrites keep their
    dedicated path. All repaired text still passes downstream claim verification.
    """
    result = _review_guidance(draft, context, message, focus)
    codes = {issue["code"] for issue in result["issues"] if issue["field"] == "suggested_reply"}
    if codes == {"current_condition_not_addressed"}:
        # This is a missing obligation, not proof that every existing sentence
        # is wrong. Remove the specific misdirected question, keep the rest.
        retained = [sentence for sentence in re.findall(r"[^。！？；\n]+[。！？；\n]?", draft["suggested_reply"])
                    if "是否已联系客服" not in sentence]
        candidate = "".join(retained)
        if not any(word in candidate for word in ("当前", "状况", "现状", "现在")):
            candidate += "先沿用您已说明的情况；当前状况若仍不清楚，再确认是否持续或加重，由人工优先跟进。"
        if candidate and len(candidate) <= 500:
            result["changes"]["suggested_reply"] = candidate
        return result
    if not codes or not codes <= LOCAL_REPAIRS.keys() or "suggested_reply" not in result["changes"]:
        return result
    sentences = re.findall(r"[^。！？；\n]+[。！？；\n]?", draft["suggested_reply"])
    repaired, inserted = [], set()
    for sentence in sentences:
        check = _review_guidance({**draft, "suggested_reply": sentence}, context, message, focus)
        affected = [issue["code"] for issue in check["issues"]
                    if issue["field"] == "suggested_reply" and issue["code"] in LOCAL_REPAIRS]
        if not affected:
            repaired.append(sentence)
            continue
        for code in dict.fromkeys(affected):
            if code not in inserted:
                repaired.append(LOCAL_REPAIRS[code]); inserted.add(code)
    candidate = "".join(repaired)
    if candidate and len(candidate) <= 500:
        result["changes"]["suggested_reply"] = candidate
    return result
