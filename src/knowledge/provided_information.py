"""Source-bound supplied information; reported uploads are not verified files."""

from __future__ import annotations

import re

MATERIALS = ("照片", "图片", "截图", "底标")
SENT = re.compile(
    r"(?:照片|图片|截图|底标)[^。；！？\n]{0,8}(?:已经(?:发|提供|传|给)|发过|给过|提供过|传过|已发)"
    r"|(?:已经|已)(?:发|提供|传|给)[^。；！？\n]{0,10}(?:照片|图片|截图|底标)"
    r"|(?:发过|提供过|传过)[^。；！？\n]{0,8}(?:照片|图片|截图|底标)")
SKIN = re.compile(r"(?:我是|我的肤质(?:是|为)?|本人(?:是)?)\s*"
                  r"(敏感肌|敏感皮肤|混合偏油|混合偏干|油皮|干皮|油性皮肤|干性皮肤|混合肌)")
ORDER_FIELDS = {
    "物流单号": "已有运单字段", "商品规格": "已有商品规格", "商品名称": "已有商品名称",
}


def supplied_information(context: dict, message: str, session_id: str) -> list[dict]:
    """Restrict memory to current or confirmed sessions and cutoff-visible sources."""
    history = context.get("service_history", {})
    own = context.get("session_id") or session_id
    cutoff, point = context.get("analysis_at", ""), context.get("analysis_point", "")
    raw_messages = list(context.get("messages", []))
    prior = [row for row in raw_messages if not row.get("session_id") or row["session_id"] == own]
    if history.get("identity_basis", "unconfirmed") != "unconfirmed":
        prior += history.get("messages", [])
    prior = [row for row in prior if row.get("角色") == "买家"
             and row.get("message_id") != point
             and (not cutoff or not row.get("发送时间") or row["发送时间"] <= cutoff)]
    prior.sort(key=lambda row: row.get("发送时间", ""))
    selected = next((row for row in raw_messages
                     if row.get("message_id") == point and row.get("message_text") == message), {})
    current = {
        "message_id": point, "message_text": message, "发送时间": cutoff, "session_id": own,
        "内容类型": selected.get("内容类型", "文本"), "image_available": selected.get("image_available", False),
    }
    rows = prior[-12:] + [current]
    items, seen = [], set()

    def add(kind: str, label: str, value: str, status: str, row: dict, quote: str) -> None:
        key = (kind, value)
        if key in seen:
            return
        seen.add(key)
        items.append({
            "kind": kind, "label": label, "value": value, "status": status,
            "basis": {"message_id": row.get("message_id", ""), "session_id": row.get("session_id", own),
                      "time": row.get("发送时间", ""), "quote": quote[:120]},
        })

    for row in rows:
        text = row.get("message_text", "")
        for clause in re.split(r"[，,。！？?!；;\n]|但是|不过", text):
            sent = SENT.search(clause)
            negated = re.search(r"没有|还没|没发|未发|没提供|未提供|并未", clause)
            question = re.search(r"吗|是否|有没有|是不是", clause)
            other_person = re.search(r"朋友|客服|别人|他|她", clause[:sent.start()] if sent else "")
            if sent and not negated and not question and not other_person:
                material = next((name for name in MATERIALS if name in sent[0]), "材料")
                add("reported_material", "买家称已提供" + material, material,
                    "buyer_reported_upload_unverified", row, sent[0])
            for match in SKIN.finditer(clause):
                if question or re.search(r"不是|并非|朋友|她|他", clause[:match.start()]):
                    continue
                add("skin_type", "已有肤质自述", match[1], "buyer_reported_not_product_approval", row, match[0])
        if row.get("内容类型") == "图片":
            add("attachment_record", "已有图片消息记录", row.get("message_id", "") or "图片",
                "asset_available" if row.get("image_available") is True else "asset_not_provided",
                row, text)
    for evidence in context.get("evidence", []):
        if evidence.get("type") != "order" or not evidence.get("id"):
            continue
        fields = evidence.get("fields", {})
        reference = {
            "message_id": str(evidence["id"]), "session_id": own,
            "发送时间": fields.get("下单时间", ""), "message_text": "",
        }
        add("order_reference", "已有订单记录", str(evidence["id"]), "structured_record", reference,
            "订单关联记录：" + str(evidence["id"]))
        for field, label in ORDER_FIELDS.items():
            value = fields.get(field)
            if value and "未知" not in str(value) and "未提供" not in str(value):
                add("order_field", label, str(value), "structured_record", reference,
                    field + "：" + str(value))
    for item in items:
        if item["kind"] != "reported_material":
            continue
        if re.search(
            rf"(?:{re.escape(item['value'])})[^。；！？\n]{{0,8}}(?:没有|还没|未|没)(?:发|传|提供|给)"
            rf"|(?:没有|还没|未|没)(?:发|传|提供|给)[^。；！？\n]{{0,8}}(?:{re.escape(item['value'])})",
            message,
        ):
            item["status"] = "current_report_conflicts_with_prior_upload"
    return items[:8]
