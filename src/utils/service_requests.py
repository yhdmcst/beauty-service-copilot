"""Ignore explicitly declined service requests, preserving reported missing outcomes."""

from __future__ import annotations

import re

TOPIC = (
    r"订单地址|退款进度|退款流水|发货时间|运单号|商品成分|使用方法"
    r"|退货|退款|退钱|改址|地址|赠品|小样|真伪|真假|假货|批次"
    r"|物流|发货|成分|用法|尾款|价保|保价|发票|质量问题|色号"
)
DECLINE = (
    r"(?:不用|无需|不需要|不打算|不想|不要)(?:再|继续)?"
    r"(?:(?:申请|办理|处理|要求|查询|查看|查|咨询|问|核对|核查|怀疑|改)?)"
    r"|(?:不(?:再|想|要|需要|打算)?|没有|没|并非)"
    r"(?:再|继续)?(?:申请|办理|处理|要求|查询|查看|查|咨询|问|核对|核查|怀疑|改)"
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
    return DECLINED.sub(lambda match: " " * len(match[0]), text)
