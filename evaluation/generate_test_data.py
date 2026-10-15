"""Produce deterministic synthetic fixtures, not independent test labels."""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "test_data"

INTENTS = {
    "ingredient_query": ["成分里有烟酰胺吗", "含玻尿酸吗", "这个精华的成分是什么", "里面有没有水杨酸"],
    "skin_type_match": ["敏感肌能用吗", "我是油性皮肤适合吗", "这个面霜适合干性肤质吗", "混合皮用这款合适吗"],
    "usage_method": ["这个面霜怎么用", "精华的使用方法是什么", "晚上先用哪个步骤", "护肤顺序怎么排"],
    "authenticity_check": ["这是假货吗", "怎么鉴别正品", "怎么看真假", "这瓶是不是正品"],
    "effect_inquiry": ["多久见效", "能美白吗", "这个产品有效果吗", "能淡斑吗"],
    "allergy_concern": ["会不会过敏", "敏感皮肤用着会刺激吗", "孕妇能用吗", "怕过敏可以试吗"],
    "product_comparison": ["和SK-II相比哪个好", "两个精华区别是什么", "这款和另一款哪个好", "两种面霜对比"],
    "order_query": ["我的订单在哪", "订单号怎么查", "已下单的订单在哪里", "买的那单如何查询"],
    "logistics_query": ["快递什么时候到", "物流查不到", "什么时候发货", "配送几天到"],
    "refund_request": ["我要退款", "如何申请退货", "不想要了要退", "退款怎么操作"],
    "quality_issue": ["瓶子破了质量有问题", "收到的产品漏了", "商品坏了", "货不对版怎么处理"],
    "allergy_reaction": ["用了过敏了", "涂了脸上红肿", "精华用了刺痛", "用后起疹怎么办"],
    "coupon_query": ["优惠券在哪里", "现在有折扣吗", "怎么领券", "有优惠吗"],
    "activity_inquiry": ["现在有什么活动", "满减活动什么时候结束", "什么时候促销", "打折活动有吗"],
    "invoice_request": ["可以开发票吗", "发票抬头怎么填写", "电子发票在哪里", "我要补开发票"],
    "general_consultation": ["您好", "有人在线吗", "谢谢你", "可以联系人工吗"],
}
EMOTIONS = {
    "allergy_anxiety": ["过敏了，很担心", "红肿刺痛，害怕", "脸过敏了很焦虑", "皮肤烂了，很害怕"],
    "effect_disappointment": ["用了一个月没效果，失望", "白花钱了，没用", "效果很差，失望", "效果不好，白买了"],
    "price_dissatisfaction": ["太贵了，不满意", "价格比别家贵", "怎么这么贵啊", "这价格真不值"],
    "purchase_hesitation": ["纠结要不要买", "犹豫买哪个", "怕不合适，不确定要买", "先考虑一下，纠结"],
}
RISK = [
    ("用了之后脸上红肿刺痛", {}),
    ("过敏了，起疹子", {}),
    ("呼吸困难，脸很肿", {}),
    ("要投诉到12315", {}),
    ("我要给你们差评", {}),
    ("这件事我要曝光", {}),
    ("想退货", {"refund_count_30d": 2}),
    ("再退款一次", {"refund_count_30d": 3}),
    ("和SK-II比较", {}),
    ("雅诗兰黛比你们好", {}),
]
RISK_NEGATIVE = [
    "会不会过敏？",
    "敏感肌能用吗",
    "今天发货吗",
    "如何申请发票",
    "谢谢你",
    "这款面霜含烟酰胺吗",
    "为什么价格比另一款贵",
    "帮我看看适合干皮吗",
    "多久能见效",
    "怎么用",
]


def main() -> None:
    """Write labelled synthetic variants with explicit provenance."""
    OUT.mkdir(parents=True, exist_ok=True)
    intent_rows = []
    for intent, queries in INTENTS.items():
        for index in range(13 if intent in list(INTENTS)[:8] else 12):
            intent_rows.append({"query": queries[index % len(queries)],
                                "ground_truth": intent, "origin": "synthetic_template"})
    emotion_rows = []
    for emotion, queries in EMOTIONS.items():
        for index in range(25):
            emotion_rows.append({"query": queries[index % len(queries)],
                                 "ground_truth": emotion, "origin": "synthetic_template"})
    risk_rows = []
    for index in range(50):
        query, history = RISK[index % len(RISK)]
        risk_rows.append({"query": query, "history": history, "ground_truth": True,
                          "origin": "synthetic_template"})
    negative_rows = [{"query": query, "history": {}, "ground_truth": False,
                      "origin": "synthetic_template"} for query in RISK_NEGATIVE]
    for name, rows in [("intent_test", intent_rows), ("emotion_test", emotion_rows),
                       ("risk_test", risk_rows), ("risk_negative_test", negative_rows)]:
        (OUT / f"{name}.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {len(rows)} synthetic samples")


if __name__ == "__main__":
    main()
