"""Explicit beauty-service risk triggers independent of aggregate risk score."""

from __future__ import annotations

import re

NEGATION_SUFFIX = re.compile(
    r"(?:没有|没|未|不是|并非|不再|无|不)[\s了再也任何明显]*"
    r"(?:[\u4e00-\u9fff]{1,4}[或和、])*$"
)


def is_active_keyword(text: str, keyword: str) -> bool:
    """Ignore a keyword when a nearby negation explicitly cancels it."""
    start = 0
    while True:
        index = text.find(keyword, start)
        if index < 0:
            return False
        prefix = re.split(r"[，,。.!！?？;；]|但是|不过|但|却", text[:index])[-1][-10:]
        if not NEGATION_SUFFIX.search(prefix):
            return True
        start = index + len(keyword)


def detect_risks(text: str, history: dict | None = None) -> list[dict]:
    """Detect actionable risks conservatively; allergies require human attention."""
    history = history or {}
    lowered = text.lower()
    alerts = []
    allergy_reaction = any(is_active_keyword(lowered, keyword) for keyword in (
        "过敏了", "过敏反应", "过敏就医",
        "红肿", "红疹", "脸肿", "脸部肿", "脸肿了", "刺痛", "起疹", "呼吸困难", "发红", "发痒",
        "烂脸", "泛红", "刺痒", "爆痘",
    ))
    for clause in re.split(r"[，,。.!！?？;；]", lowered):
        if any(cue in clause for cue in ("用了", "用后", "涂后", "发生")) and \
                is_active_keyword(clause, "过敏") and not any(
                    question in clause for question in ("会不会", "可能", "担心", "怕")):
            allergy_reaction = True
    # Symptoms can span clauses; a past-use report differs from a pre-sale question.
    if re.search(r"用了|使用后|用后|涂后|用完|涂完", lowered):
        for clause in re.split(r"[，,。.!！?？;；]", lowered):
            symptom = re.search(r"又红又痒|红(?:又|且|还|和)痒", clause)
            if symptom and is_active_keyword(clause, symptom[0]) and not re.search(
                r"会不会|会不会出现|担心会|怕会|如果|假如|是否会", clause
            ):
                allergy_reaction = True
    rules = [
        ("allergy", "过敏反应", "critical", ("__active_allergy_reaction__",),
         "立即停用并转人工，严重症状请就医"),
        ("bad_review", "差评/舆情", "high", ("差评", "曝光", "12315", "投诉", "举报"),
         "人工优先复核"),
        ("competitor", "竞品提及", "medium", ("sk-ii", "雅诗兰黛", "兰蔻", "资生堂"),
         "核实竞品信息后回应"),
    ]
    for code, name, level, keywords, action in rules:
        triggered = allergy_reaction if code == "allergy" else any(
            is_active_keyword(lowered, keyword) for keyword in keywords
        )
        if triggered:
            alerts.append({"code": code, "name": name, "level": level, "action": action})
    if (history.get("refund_count_30d") or 0) >= 2:
        alerts.append({"code": "repeat_refund", "name": "重复退款", "level": "high",
                       "action": "人工复核订单及售后记录"})
    return alerts
