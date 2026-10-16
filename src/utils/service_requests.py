"""Ignore explicitly declined service requests, preserving reported missing outcomes."""

from __future__ import annotations

import re

TOPIC = (
    r"订单地址|退款进度|退款流水|发货时间|运单号|商品成分|使用方法"
    r"|退货|退款|退钱|改址|地址|赠品|小样|真伪|真假|假货|批次"
    r"|物流|发货|成分|用法|尾款|价保|保价|发票|开票|质量问题|色号"
)
DECLINE = (
    r"(?:不用|无需|不需要|不打算|不想|不要|先别|暂不|暂时不)(?:再|继续)?"
    r"(?:(?:申请|办理|处理|要求|查询|查看|查|咨询|问|核对|核查|怀疑|改)?)"
    r"|(?:不(?:再|想|要|需要|打算)?|没有|没|并非)"
    r"(?:再|继续)?(?:申请|办理|处理|要求|查询|查看|查|咨询|问|核对|核查|怀疑|改)"
    r"|(?:不是|并非)(?:要|想要|想)(?=(?:" + TOPIC + r"))"
    r"|(?:不是|并非)(?=(?:" + TOPIC + r")(?:问题|的问题|咨询))"
)
DECLINED = re.compile(
    rf"(?:{DECLINE})(?:这个|这笔|一下|相关)?(?:{TOPIC})"
    rf"(?:(?:和|或|及|与|、|/)?(?:{TOPIC}))*(?:问题|的问题|咨询)?(?:了)?"
)
MISSING_OUTCOME_CUES = {
    "退款", "退钱", "退货", "赠品", "小样", "赠送", "附赠", "试用装",
    "发货", "发出", "物流", "运单", "签收", "到账",
}


def current_request_text(text: str) -> str:
    """Create a classification view only; original chat and safety input stay intact."""
    view = DECLINED.sub(lambda match: " " * len(match[0]), text)
    # Topic-first postponements differ from missing results such as 退款没到账.
    return re.sub(
        rf"(?:{TOPIC})(?:先|暂时|暂且)(?:不用|不要|不办|别办)(?:了)?",
        lambda match: " " * len(match[0]), view,
    )


REQUEST_TOPICS = (
    ("refund_request", "退款/退货", r"退款|退钱|退货|退的款|退的钱|钱.{0,4}(?:没回来|没到账)|给我退了"),
    ("order_query", "修改地址", r"改地址|改址|地址.{0,6}(?:改|填错)|修改地址"),
    ("logistics_query", "物流/发货", r"物流|发货|运单|配送|快递|签收"),
    ("quality_issue", "商品问题", r"漏液|渗漏|破损|损坏|泵头|少件|空包|色号.{0,5}(?:不对|错)|发错|换货|能换"),
    ("activity_inquiry", "活动/赠品", r"赠品|小样|赠送|尾款|活动"),
    ("authenticity_check", "真伪核查", r"假货|真假|真伪"),
    ("invoice_request", "发票", r"发票|开票"),
)
CLAUSES = re.compile(r"(?:(?!但是|不过|但|却)[^，,。；;！？?!\n])+")
ORDER_SCOPE = re.compile(r"另一(?:笔|个)?(?:订单|单)|这(?:笔|个)?(?:订单|单)|那(?:笔|个)?(?:订单|单)|订单(?:号)?\s*[A-Za-z0-9_-]{5,}")


def request_plan(text: str) -> dict:
    """Extract bounded request candidates, not verified order bindings or full NLU.

    Offsets always refer to the original input. Unknown expressions are left for
    the same generation/human review; no historical identity is inferred here.
    """
    view = current_request_text(text)
    items, reasons = [], []
    scope = "当前会话，订单待核"
    for clause_match in CLAUSES.finditer(text):
        clause = clause_match[0]
        inherited_scope = scope
        scopes = list(ORDER_SCOPE.finditer(clause))
        if scopes:
            scope = scopes[-1][0]
        historical = bool(re.search(r"上次|之前|此前|原先|原来", clause)) and not re.search(
            r"现在|这次|目前|还没|仍|一直|没到账|没回来|未解决", clause)
        inquiry = bool(re.search(r"规则|政策|条件|流程|怎么规定|能否", clause))
        for intent, label, pattern in REQUEST_TOPICS:
            for match in re.finditer(pattern, clause):
                start, end = clause_match.start() + match.start(), clause_match.start() + match.end()
                preceding_scopes = [ref for ref in scopes if ref.start() <= match.start()]
                item_scope = preceding_scopes[-1][0] if preceding_scopes else inherited_scope
                masked = not view[start:end].strip()
                cancelled = bool(re.search(r"(?:取消|撤销)(?:申请|办理)?$", clause[:match.start()])
                                 and intent in {"refund_request", "invoice_request"})
                conditional = bool(re.search(r"如果|假如|实在|否则|若|要是", clause[:match.start()])
                                   and re.search(r"再|就|考虑", clause))
                status = "historical" if historical else "conditional" if conditional else "cancelled" if cancelled else "deferred" if masked else "active"
                if inquiry and status == "active":
                    status = "inquiry"
                # A negated defect is not an active report of seller error.
                if intent == "quality_issue" and re.search(r"不是|并非|没有", clause[:match.start()][-6:]):
                    status = "rejected"
                # A reported result is no longer an instruction to keep doing
                # the same thing. Keep it visible with its original source.
                outcome = ((intent == "refund_request" and re.search(r"已(?:经)?到账|到账了|已(?:经)?收到退款", clause))
                           or (intent == "quality_issue" and re.search(r"已(?:经)?解决了|处理好了|修好了", clause[match.end():])))
                uncertain = re.search(r"没|未|是否|吗|如果|假如|要是|预计|可能|客服说|朋友说|别人说|少了|差额", clause)
                if intent == "refund_request" and re.search(r"(?:还少|少了|还差|差额)[^。；\n]{0,12}(?:元|块|到账)", text):
                    uncertain = True
                if status == "active" and outcome and not uncertain:
                    status = "buyer_reported_resolved"
                item = {"intent": intent, "label": label, "status": status,
                        "order_scope": item_scope, "quote": clause.strip(),
                        "start": clause_match.start(), "end": clause_match.end(),
                        "cue_start": start, "cue_end": end,
                        "binding_status": "unverified", "basis": "explicit_text_candidate"}
                if not any(all(old[k] == item[k] for k in ("intent", "status", "cue_start", "order_scope")) for old in items):
                    items.append(item)
    items.sort(key=lambda item: item["cue_start"])
    active = [item for item in items if item["status"] in {"active", "inquiry"}]
    if any(item["status"] in {"deferred", "conditional", "historical", "rejected", "cancelled", "buyer_reported_resolved"} for item in items):
        reasons.append("存在暂缓、条件、历史或排除诉求，需核对当前处理顺序")
    if len({item["intent"] for item in active}) > 1:
        reasons.append("存在多个诉求，需逐项核对，不能只处理单一标签")
    if len({item["order_scope"] for item in active}) > 1:
        reasons.append("涉及不同订单指代，需确认对应关系，不自动绑定订单")
    if any(item["status"] == "inquiry" for item in active):
        reasons.append("包含规则咨询，不能视为已申请办理")
    return {"items": items[:12], "review_reasons": reasons,
            "requires_review": bool(reasons), "scope": "current_input_candidates_not_business_facts"}


def active_request_text(text: str) -> str:
    """Mask hypothetical actions and old requests for classification, preserving offsets."""
    view = current_request_text(text)
    for item in request_plan(text)["items"]:
        if item["status"] in {"conditional", "historical", "cancelled", "buyer_reported_resolved"}:
            start, end = item["cue_start"], item["cue_end"]
            view = view[:start] + " " * (end - start) + view[end:]
    return view


def primary_request_text(text: str) -> str:
    """Different order references must not contribute keywords to one service focus."""
    plan = request_plan(text)
    active = [item for item in plan["items"] if item["status"] in {"active", "inquiry"}]
    if len({item["order_scope"] for item in active}) > 1:
        first = active[0]
        # Preserve the first request's clause, stopping before another order's
        # reference even if the buyer omitted punctuation.
        following = [item for item in active if item["order_scope"] != first["order_scope"]]
        boundary = following[0]["cue_start"]
        refs = list(ORDER_SCOPE.finditer(text[:boundary]))
        stop = refs[-1].start() if refs and refs[-1][0] != first["order_scope"] else first["end"]
        return active_request_text(text)[first["start"]:min(first["end"], stop)]
    return active_request_text(text)
