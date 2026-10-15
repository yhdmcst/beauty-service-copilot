"""Service behavior regressions use new wording, not frozen-label answer matching."""

import json
from types import SimpleNamespace

import pytest

from src.agents.assist_agent import AssistAgent
from src.knowledge.business_claims import check_claims
from src.knowledge.service_guidance import review_guidance, service_focus
from src.risk.beauty_risk_rules import detect_risks


def context():
    return {
        "analysis_point": "buyer-1", "analysis_mode": "replay",
        "analysis_at": "2026-06-08 11:00:00", "messages": [],
        "evidence": [{
            "id": "ORDER-X", "type": "order", "fields": {
                "订单状态": "历史状态未提供", "实付金额(元)": "300",
                "发货时间": "2026-06-07 08:00:00",
                "物流单号": "WAYBILL-X", "快递公司": "示例承运方",
            },
        }],
    }


def draft(**changes):
    return {
        "summary": "买家咨询待核实", "emotion": "担忧",
        "risk_level": "低", "evidence_ids": ["ORDER-X"], "missing_info": [],
        "suggested_reply": "理解您的困扰，需要先核对情况。",
        "next_action": "客服核对记录",
        **changes,
    }


@pytest.mark.parametrize("message,category", [
    ("退货仓库收到后售后关闭了，钱退不出来", "return_refund"),
    ("我的地址写错还没到货，申请改址", "address_change"),
    ("收到货没有赠品，帮查是否分包", "promotion_or_gift"),
    ("买两件少了一件，请查仓库出库", "missing_items"),
    ("退的钱少了12元", "refund_status_or_amount"),
    ("退货退款到了，但是差额少了18.2块", "refund_status_or_amount"),
    ("泵头有问题，我申请退款", "refund_status_or_amount"),
    ("没有红肿或刺痛，只查物流", "shipment_query"),
    ("想买面霜，担心会不会过敏", "general_service"),
    ("眼影颜色和专柜不同，会不会是假货", "authenticity_concern"),
    ("买的是#13，收到#27，帮查色号", "sku_mismatch"),
    ("尾款窗口几点开始，定金付了", "pre_sale_payment"),
    ("面霜用完后脸肿了，医生说是接触性皮炎", "adverse_reaction_report"),
])
def test_current_request_not_incidental_keywords(message, category):
    assert service_focus(message, "general_consultation")["category"] == category


def test_coordinated_negation_does_not_hide_an_explicit_active_symptom():
    assert detect_risks("没有红肿或刺痛，只查物流") == []
    assert detect_risks("没有红肿和发痒") == []
    assert detect_risks("没有红肿，但有刺痛")


@pytest.mark.parametrize("message,reply,code", [
    ("退货仓库收到但退款受阻", "麻烦您提供签收凭证及收货地址", "internal_record_requested_from_buyer"),
    ("赠品少了", "请您提供装箱单以便确认", "internal_record_requested_from_buyer"),
    ("泵头按不出来", "请问是否已检查商品是否完好", "reported_defect_not_addressed"),
    ("买#13收到#27", "能否提供收到的色号", "known_variant_requested_again"),
    ("买#13收到#27", "请问您实际收到的色号是什么", "known_variant_requested_again"),
    ("泵头按不出来", "请问您是否已查看物流签收凭证", "internal_record_requested_from_buyer"),
    ("尾款什么时候付", "若未明确，可提供订单号", "known_order_requested_again"),
    ("物流几天到", "麻烦您查物流进度", "tracking_work_shifted_to_buyer"),
    ("眼影气味与专柜不同", "气味差异可能是批次原因", "batch_explanation_not_verified"),
    ("退货签收但售后关闭", "麻烦核实退货是否已入库及售后原因", "after_sales_work_shifted_to_buyer"),
    ("脸部起疹子", "您是否已联系客服", "current_condition_not_addressed"),
])
def test_wrong_questions_are_repaired_without_customer_work(message, reply, code):
    original = draft(suggested_reply=reply)
    result = review_guidance(original, context(), message, service_focus(message, "general_consultation"))
    assert any(item["code"] == code for item in result["issues"])
    assert result["changes"]["suggested_reply"] != reply
    assert original["suggested_reply"] == reply


def test_return_refund_action_checks_after_sales_not_outbound_delivery():
    message = "退货签收后售后关闭，退款一直没到"
    result = review_guidance(draft(), context(), message, service_focus(message, "refund_request"))
    action = result["changes"]["next_action"]
    assert all(word in action for word in ("退货", "售后", "退款"))
    assert "代收" not in action


def test_valid_specific_model_prose_is_not_replaced_by_rule():
    message = "能核查我这笔退款吗"
    original = draft(
        summary="买家咨询退款处理进度",
        suggested_reply="理解您对退款进度的疑问，需要核对这笔退款明细后再反馈。",
        next_action="核查退款流水及费用明细",
    )
    assert review_guidance(original, context(), message, service_focus(message, "refund_request"))["changes"] == {}


def test_order_request_is_allowed_when_only_ticket_is_known():
    ctx = context()
    ctx["evidence"] = [{"id": "TICKET-X", "type": "ticket", "fields": {"工单状态": "历史状态未提供"}}]
    original = draft(suggested_reply="请您提供订单号，以便核对关联订单")
    result = review_guidance(original, ctx, "想查一下进度", service_focus("想查一下进度", "general_consultation"))
    assert "known_order_requested_again" not in [item["code"] for item in result["issues"]]


def test_known_shipping_record_is_used_only_when_cited_and_before_cutoff():
    original = draft()
    result = review_guidance(original, context(), "发货了吗，单号多少", service_focus("发货了吗", "logistics_query"))
    assert "WAYBILL-X" in result["changes"]["suggested_reply"]
    not_cited = review_guidance(
        draft(evidence_ids=[]), context(), "发货了吗", service_focus("发货了吗", "logistics_query"))
    assert "suggested_reply" not in not_cited["changes"]
    future = context()
    future["evidence"][0]["fields"]["发货时间"] = "2026-06-10 08:00:00"
    assert "suggested_reply" not in review_guidance(
        original, future, "发货了吗", service_focus("发货了吗", "logistics_query"))["changes"]


def test_shipping_pending_is_not_signature_proof():
    records = [{"id": "O1", "fields": {"订单状态": "待收货"}}]
    result = check_claims("我们看到物流已签收", records, ["O1"])
    assert "unsupported_external_delivery_observation" in result["flags"]
    assert "unsupported_signed" in result["flags"]


def test_reported_money_must_exist_in_original_buyer_text():
    records = [{"id": "O1", "fields": {"实付金额(元)": "300"}}]
    reported = check_claims("用户称退款少23.5元", records, ["O1"], source_text="我收到的钱少了23.5块")
    assert reported["flags"] == []
    invented = check_claims("用户称退款少999元", records, ["O1"], source_text="我收到的钱少了23.5块")
    assert "unsupported_amount" in invented["flags"]
    different_role = check_claims("用户称少了23.5元但后台实付999元", records, ["O1"], source_text="少了23.5元")
    assert "unsupported_amount" in different_role["flags"]
    wrong_role = check_claims(
        "用户称退款少300元", records, ["O1"],
        source_text="订单实付300元，但退款少了23.5元")
    assert "unsupported_amount" in wrong_role["flags"]


@pytest.mark.parametrize("text", ["请放心我们已受理", "请放心我们已核实", "建议稍后回复，我们已联系物流"])
def test_reassurance_does_not_turn_completed_actions_into_plans(text):
    assert "unsupported_execution_claim" in check_claims(text, [], [])["flags"]


def test_attribution_cannot_hide_a_new_diagnosis_or_treatment_instruction():
    assert "unsupported_medical_conclusion" in check_claims(
        "买家称接触性皮炎", [], [], source_text="脸痒，请查订单")["flags"]
    assert "unsupported_medical_conclusion" in check_claims(
        "客户称保证治愈", [], [], source_text="保证治愈")["flags"]
    reported = check_claims(
        "买家自述已经就医，医生说是接触性皮炎", [], [],
        source_text="已就医，医生说是接触性皮炎")
    assert not reported["flags"]


def test_supported_shipment_requires_event_before_analysis_time():
    result = check_claims("已发货", context()["evidence"], ["ORDER-X"], analysis_at="2026-06-06 11:00:00")
    assert "unsupported_shipped" in result["flags"]


class Model:
    model = "fixture"
    provider = "ollama"

    def __init__(self, output):
        self.calls = 0
        self.output = output

    def generate_with_usage(self, prompt, max_tokens=360):
        self.calls += 1
        return SimpleNamespace(text=json.dumps(self.output, ensure_ascii=False),
                               input_tokens=100, output_tokens=40, model=self.model)


class NoKnowledge:
    def search(self, message, intent):
        return {"reason": "no_evidence", "confidence": 0,
                "can_auto_reply": False, "retrieved_docs": []}


def test_combined_unsafe_claims_are_rechecked_after_rewrite():
    model = Model(draft(suggested_reply="我们注意到物流显示已签收，您的订单实付999元。"))
    result = AssistAgent(model, NoKnowledge()).assist(context(), "物流已签收但没收到", "NEW-SESSION")
    assert "999" not in result["suggested_reply"]
    assert "unsupported_amount" in result["validation_flags"]
    assert result["final_validation_flags"] == []
    assert result["draft_before_validation"]["suggested_reply"] == model.output["suggested_reply"]
    assert result["quality_adjustments"]


def test_new_prompt_version_changes_cache_key_without_erasing_history():
    model = Model(draft())
    agent = AssistAgent(model, NoKnowledge())
    first = agent.assist(context(), "请查退款流水", "NEW-SESSION")
    assert not first["cache_hit"]
    assert agent.assist(context(), "请查退款流水", "NEW-SESSION")["cache_hit"]
    agent.prompt_version += "-new"
    assert not agent.assist(context(), "请查退款流水", "NEW-SESSION")["cache_hit"]
    assert model.calls == 2


def test_health_exposes_actual_assistance_version(monkeypatch):
    from src.api.app_upgraded import create_app

    agent = AssistAgent(Model(draft()), NoKnowledge())
    app = create_app(assist_agent=agent)
    try:
        assert app.test_client().get("/health").json["assistance_revision"] == agent.prompt_version
    finally:
        app.extensions["analysis_jobs"].close()
        app.extensions["case_store"].close()
        app.extensions["evaluation_store"].close()
