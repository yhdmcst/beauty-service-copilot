"""Specific reported item issues shared by intent and operational focus."""

from __future__ import annotations

import re

from src.risk.beauty_risk_rules import is_active_keyword
from src.utils.service_requests import current_request_text

NUMBERS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
NUMBER = r"[一两二三四五六七八九十]|\d{1,2}"
ITEM = r"洗发水|洁面乳|洁面|精华|乳液|面霜|眼影盘|眼影|粉底液|遮瑕|商品|正装"
QUANTITY = re.compile(
    rf"(?P<ordered>{NUMBER})(?P<ordered_unit>件|支|盒|瓶|袋|套)?[^。；！？\n]{{0,12}}"
    rf"(?:只(?:有|放|收到|发来)|仅(?:有|收到))(?P<received>{NUMBER})(?P<received_unit>件|支|盒|瓶|袋|套)"
)
PATTERNS = (
    ("product_usability_or_damage", re.compile(
        r"(?:瓶子|瓶身|瓶盖|盖子|封口|管子|泵头)[^，。；！？\n]{0,8}"
        r"(?:碎(?:了)?|开裂|裂(?:了)?|破裂|破损|损坏|坏了|漏液)"
        r"|空管|空瓶|(?:管子|管身)[^，。；！？\n]{0,4}是空的"
        r"|泵头|按不出|挤不出|漏液|玻璃渣|破损|渗漏")),
    ("missing_items", re.compile(
        r"(?:少|缺|漏)(?:了|发|装)?(?:一|两|二|三|\d{1,2})(?:件|支|盒|瓶|袋|套)"
        r"|少件|缺件|漏发|(?:箱子|盒子|包装|包裹)[^，。；！？\n]{0,6}(?:是空的|里面是空的|空的)"
        r"|空包裹"
        rf"|(?:少了|缺了|漏了|没放)(?:{ITEM})"
        rf"|(?:{ITEM})(?:没放|未放)(?:进去|进来|在箱内)")),
)


def _active_issue(text: str, match: re.Match) -> bool:
    prefix = re.split(r"[，,。！？?!；;]|但是|不过|但|却", text[:match.start()])[-1][-16:]
    if re.search(r"不是|并非|没有|未发生|不怀疑|不认为|不觉得|无需查|不查", prefix):
        return False
    if re.search(r"会不会|是否会|如果|假如|担心会|怕会", prefix):
        return False
    missing_placement = re.search(r"没放|未放", match[0]) is not None
    if re.search(r"没有|没(?:有)?|未|不是|并非", match[0]) and not missing_placement:
        return False
    if re.search(r"空瓶回收|空管回收|回收空瓶|用完的空瓶", text):
        if re.search(r"空瓶|空管", match[0]):
            return False
    if re.search(r"(?:他|她|朋友|别人|客服)(?:说|表示|认为|觉得)[^，。；！？\n]{0,4}$", prefix):
        return False
    return is_active_keyword(text[max(0, match.start() - 12):match.end()], match[0])


def reported_item_issues(message: str) -> list[dict]:
    """Use original spans; denials, hypotheticals and refund amounts are not defects."""
    text = current_request_text(message)
    issues = []
    for category, pattern in PATTERNS:
        for match in pattern.finditer(text):
            if _active_issue(text, match):
                issues.append({
                    "category": category, "quote": message[match.start():match.end()],
                    "start": match.start(), "end": match.end(),
                    "basis": "buyer_reported_item_issue_not_verified_cause",
                })
    for match in QUANTITY.finditer(text):
        def number(value: str) -> int:
            return NUMBERS[value] if value in NUMBERS else int(value)
        same_unit = not match["ordered_unit"] or match["ordered_unit"] == match["received_unit"]
        if same_unit and number(match["received"]) < number(match["ordered"]) and _active_issue(text, match):
            issues.append({
                "category": "missing_items", "quote": message[match.start():match.end()],
                "start": match.start(), "end": match.end(),
                "basis": "buyer_reported_quantity_difference_not_warehouse_confirmation",
            })
    return issues[:6]
