"""Conservative checks for explicit money and completion claims, not general entailment."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

MONEY = re.compile(r"(\d+(?:\.\d+)?)\s*元")
REPORTED_MONEY = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)")
SCOPES = re.compile(r"退款|打款|退运费|赔偿|实付|付款|支付|订单金额")
REFUND_DONE = re.compile(r"已退款|已打款|退款(?:已经|已)?(?:到账|完成|成功)|转账成功")
SHIPPED = re.compile(r"(?:已经|已)发货|发货(?:已经|已)?完成")
UNSHIPPED = re.compile(r"未发货|尚未发货|还没发货|没有发货")
RESHIPPED = re.compile(r"已补发|补发(?:已经|已)?(?:完成|发货)")
COMPLETE = {"成功", "转账成功", "已退款", "退款成功", "已完成", "已到账"}
NONASSERTED = re.compile(
    r"(?:没有|尚未|还未|未|并非|不是|不代表|不表示|不能确认|无法确认|是否|如果)[\s]*$"
)
UNSUPPORTED_COMMITMENTS = re.compile(
    r"已(?:经)?(?:为您|给您|为你|给你|帮您|帮你)?(?:提交|安排|建立|转接|转人工|加急|核实)"
    r"|将(?:会)?(?:为您|给您|为你|给你)?(?:补发|补款|报销|赔付)"
    r"|一定(?:可以|到账|送达)|保证(?:退款|到货|送达|治愈)"
)
UNSUPPORTED_EXECUTION = re.compile(
    r"(?:我们|我|客服|平台)(?:已经|已|正在)(?:为您|给您|帮您)?"
    r"(?:核实|核查|查询|查到|记录|登记|受理|联系|跟进)"
)
UNSUPPORTED_STATUS_ASSERTION = re.compile(
    r"(?:尾款|退款(?:状态|时间)?|物流(?:状态|信息)?|订单状态|处理结果)"
    r"[^。；\n]{0,10}(?:已确认|已随订单|已在订单|已提供)"
)
DELIVERY_TIME = re.compile(r"预计[^。；\n]{0,16}(?:送达|到货)|\d+[-至到]\d+(?:个)?(?:工作日|天)[^。；\n]{0,6}(?:到账|送达|到货)")
MEDICAL_CONCLUSION = re.compile(
    r"产品(?:导致|引发)|(?:确认|确诊|诊断)为|"
    r"(?:出现|属于|就是|是)?过敏反应|接触性皮炎|保证治愈|建议(?:服用|使用药)"
)
EXTERNAL_DELIVERY_OBSERVATION = re.compile(
    r"(?:我们|客服|系统)(?:注意到|看到|显示)[^。；\n]{0,20}"
    r"(?:物流)?(?:显示)?(?:已签收|签收)"
)
SIGNED = re.compile(r"已签收|签收成功")
INTERCEPT_DONE = re.compile(
    r"拦截(?:已经|已)?成功|改址(?:已经|已)?成功|地址修改成功|地址(?:已经|已)?修改成功"
    r"|物流已转寄|包裹(?:已经|已)?转寄")
ATTRIBUTED_REPORT = re.compile(
    r"(?:买家|用户|客户)(?:称|说|反馈|表示|提到|自述|反映)|"
    r"(?:您|我)(?:称|说|反馈|表示|提到|自述|付了|收到|没收到|未收到)|"
    r"(?:买家|用户|客户)自述|医生说"
)
REPORTED_AMOUNT = re.compile(r"(?:少了|少|差了|差|未收到|没收到|只收到)")


def decimal(value: object) -> Decimal | None:
    """Normalize numeric fields while rejecting nonfinite values."""
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else None
    except InvalidOperation:
        return None


def _records(evidence: list[dict], ids: list[str]) -> list[dict]:
    return [record for record in evidence if record["id"] in ids]


def named_records(text: str, records: list[dict]) -> list[dict]:
    """Match complete IDs, not O1 as a substring of O10."""
    return [record for record in records if re.search(
        rf"(?<![A-Za-z0-9_-]){re.escape(record['id'])}(?![A-Za-z0-9_-])", text)]


def unknown_reference(text: str, records: list[dict]) -> bool:
    """An explicit order/ticket identifier needs a matching cited record."""
    references = re.findall(r"(?:订单|工单)\s*([A-Za-z0-9][A-Za-z0-9_-]*)", text)
    return bool(set(references) - {record["id"] for record in records})


def _sentence_prefix(text: str, position: int) -> str:
    """Return the current clause so attribution is not lost across a long prefix."""
    return re.split(r"[，。；！？,\n]", text[:position])[-1]


def _is_attributed(text: str, position: int) -> bool:
    sentence = re.split(r"[。；！？\n]", text[:position])[-1]
    matches = list(ATTRIBUTED_REPORT.finditer(sentence))
    if not matches:
        return False
    return not re.search(
        r"后台|订单记录|系统查询|经核实|已查证",
        sentence[matches[-1].end():],
    )


def _is_attributed_medical(text: str, position: int) -> bool:
    return _is_attributed(text, position)


def _is_reported_amount(clause: str) -> bool:
    attribution = list(ATTRIBUTED_REPORT.finditer(clause))
    if not attribution:
        return False
    tail = clause[attribution[-1].end():]
    return bool(REPORTED_AMOUNT.search(tail)) and not re.search(
        r"后台|记录|实际退款|实付|核实|确认", tail
    )


def _source_reports_amount(source_text: str, amount: Decimal | None) -> bool:
    """A mentioned payment is not evidence for a different reported shortfall."""
    for match in REPORTED_MONEY.finditer(source_text):
        clause = _sentence_prefix(source_text, match.start())
        if decimal(match[1]) == amount and REPORTED_AMOUNT.search(clause) and not re.search(
            r"实付|付款|支付|后台", clause
        ):
            return True
    return False


def check_claims(
    text: str, evidence: list[dict], ids: list[str], *,
    source_text: str | None = None, analysis_at: str = "",
) -> dict:
    """Verify a narrow set of literal claims against explicitly cited structured fields."""
    records = _records(evidence, ids)
    checks, flags = [], []
    for code, pattern in (
        ("unsupported_commitment", UNSUPPORTED_COMMITMENTS),
        ("unsupported_execution_claim", UNSUPPORTED_EXECUTION),
        ("unsupported_status_assertion", UNSUPPORTED_STATUS_ASSERTION),
        ("unsupported_time_promise", DELIVERY_TIME),
        ("unsupported_medical_conclusion", MEDICAL_CONCLUSION),
    ):
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 24):match.start()]
            if NONASSERTED.search(prefix):
                status = "not_asserted"
            elif (code == "unsupported_medical_conclusion"
                  and _is_attributed_medical(text, match.start())
                  and not re.search(r"保证|建议(?:服用|使用药)", match[0])
                  and (source_text is None or match[0] in source_text)):
                status = "reported_claim"
            else:
                status = "unsupported"
                flags.append(code)
            checks.append({"claim": match[0], "scope": code,
                           "status": status, "bindings": []})
    for match in EXTERNAL_DELIVERY_OBSERVATION.finditer(text):
        clause = _sentence_prefix(text, match.start())
        mentioned = named_records(clause + match[0], records)
        candidates = mentioned or records
        bindings = [
            {"evidence_id": record["id"]}
            for record in candidates
            if record.get("fields", {}).get("订单状态") == "已签收"
        ]
        if not candidates or len(bindings) != len(candidates) or unknown_reference(clause + match[0], records):
            bindings = []
        status = "supported" if bindings else "unsupported"
        checks.append({
            "claim": match[0], "scope": "external_delivery_observation",
            "status": status, "bindings": bindings,
        })
        if not bindings:
            flags.append("unsupported_external_delivery_observation")
    for match in MONEY.finditer(text):
        amount = decimal(match[1])
        prefix = text[:match.start()]
        prefix = re.split(r"[，。；！？,\n]", prefix)[-1]
        if NONASSERTED.search(prefix):
            checks.append({"claim": match[0], "scope": "unspecified",
                           "status": "not_asserted", "bindings": []})
            continue
        if _is_reported_amount(prefix) and (
            source_text is None or _source_reports_amount(source_text, amount)
        ):
            checks.append({"claim": match[0], "scope": "reported_amount",
                           "status": "reported_claim", "bindings": []})
            continue
        scope_matches = list(SCOPES.finditer(prefix))
        scope = scope_matches[-1][0] if scope_matches else ""
        refund = scope in {"退款", "打款", "退运费", "赔偿"}
        payment = scope in {"实付", "付款", "支付", "订单金额"}
        allowed = {"退款金额(元)"} if refund else {"实付金额(元)"} if payment else {
            "退款金额(元)", "实付金额(元)",
        }
        candidates = [record for record in records if any(
            field in record.get("fields", {}) for field in allowed)]
        mentioned = named_records(prefix + match[0], records)
        if mentioned:
            candidates = mentioned
        values = {decimal(value) for record in candidates
                  for field, value in record.get("fields", {}).items()
                  if field in allowed and decimal(value) is not None}
        bindings = [{
            "evidence_id": record["id"], "field": field, "value": str(value),
        } for record in candidates for field, value in record.get("fields", {}).items()
                    if field in allowed and decimal(value) == amount]
        if not mentioned and len(values) > 1:
            bindings = []
        if unknown_reference(prefix + match[0], records):
            bindings = []
        checks.append({
            "claim": match[0], "scope": scope or "unspecified",
            "status": "supported" if bindings else "unsupported",
            "bindings": bindings,
        })
        if not bindings:
            flags.append("unsupported_amount")

    predicates = [
        ("signed", SIGNED, {"订单状态", "签收状态"}, lambda fields: any(
            fields.get(key) == "已签收" for key in ("订单状态", "签收状态"))),
        ("intercept_complete", INTERCEPT_DONE, {"工单状态", "任务状态"}, lambda fields: any(
            fields.get(key) == "拦截成功" for key in ("工单状态", "任务状态"))),
        ("refund_complete", REFUND_DONE, {"转账状态", "退款状态"}, lambda fields: any(
            fields.get(key) in COMPLETE for key in ("转账状态", "退款状态"))),
        ("shipped", SHIPPED, {"订单状态", "发货时间"}, lambda fields: fields.get("订单状态") in {
            "已发货", "待收货", "已签收",
        } or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", str(fields.get("发货时间", "")))
                  and (not analysis_at or fields["发货时间"] <= analysis_at))),
        ("unshipped", UNSHIPPED, {"订单状态"}, lambda fields: fields.get("订单状态") in {
            "待发货", "未发货", "待付款", "未付款",
        }),
        ("replacement_shipped", RESHIPPED, {"补发物流单号"}, lambda fields: bool(
            fields.get("补发物流单号")) and fields.get("工单状态") in {
                "已发货", "已完成", "完成", "已关闭",
            }),
    ]
    for code, pattern, keys, predicate in predicates:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 6):match.start()]
            if NONASSERTED.search(prefix):
                checks.append({"claim": match[0], "scope": code,
                               "status": "not_asserted", "bindings": []})
                continue
            if _is_attributed(text, match.start()) and (
                source_text is None
                or match[0] in source_text
                or (code == "refund_complete" and any(
                    word in source_text for word in ("退款到账", "退款成功", "已退款")))
            ):
                checks.append({"claim": match[0], "scope": code,
                               "status": "reported_claim", "bindings": []})
                continue
            clause_prefix = re.split(r"[，。；！？,\n]", text[:match.start()])[-1]
            mentioned = named_records(clause_prefix + match[0], records)
            candidates = mentioned or [record for record in records if keys & record.get("fields", {}).keys()]
            bindings = [{
                "evidence_id": record["id"],
                "fields": {key: value for key, value in record.get("fields", {}).items()
                           if "状态" in key or "物流" in key or key == "发货时间"},
            } for record in candidates if predicate(record.get("fields", {}))]
            if len(bindings) != len(candidates):
                bindings = []
            if unknown_reference(clause_prefix + match[0], records):
                bindings = []
            checks.append({"claim": match[0], "scope": code,
                           "status": "supported" if bindings else "unsupported",
                           "bindings": bindings})
            if not bindings:
                flags.append(f"unsupported_{code}")
    return {"checks": checks, "flags": list(dict.fromkeys(flags))}
