"""Customer information memory must retain sources, time and identity boundaries."""

import copy

import pytest

from src.agents.assist_agent import AssistAgent
from src.knowledge.provided_information import supplied_information
from tests.test_service_guidance import Model, NoKnowledge, context, draft


def buyer(identifier, text, at="2026-06-08 10:00:00", **extra):
    return {"角色": "买家", "message_id": identifier, "message_text": text, "发送时间": at, **extra}


def test_material_report_is_not_recorded_as_received_attachment():
    ctx = context()
    ctx["messages"] = [buyer("PAST", "照片已经提供，别再问")]
    original = copy.deepcopy(ctx)
    items = supplied_information(ctx, "退款还没处理", "CURRENT")
    material = next(item for item in items if item["kind"] == "reported_material")
    assert material["status"] == "buyer_reported_upload_unverified"
    assert material["basis"]["message_id"] == "PAST"
    assert material["basis"]["quote"] in ctx["messages"][0]["message_text"]
    assert ctx == original


@pytest.mark.parametrize("text", [
    "照片还没发，请问发哪里", "请问照片已经提供了吗", "没有提供照片", "照片未发送",
])
def test_material_question_or_denial_never_becomes_supplied_information(text):
    items = supplied_information(context(), text, "CURRENT")
    assert not any(item["kind"] == "reported_material" for item in items)


def test_staff_future_and_unconfirmed_cross_session_memory_are_excluded():
    ctx = context()
    ctx["messages"] = [
        {**buyer("STAFF", "照片已经提供"), "角色": "客服"},
        buyer("FUTURE", "照片已经提供", at="2026-06-08 12:00:00"),
    ]
    ctx["service_history"] = {
        "identity_basis": "unconfirmed",
        "messages": [buyer("UNCONFIRMED", "我是油皮，照片已经提供", session_id="OTHER")],
    }
    items = supplied_information(ctx, "想查退款", "CURRENT")
    assert not any(item["kind"] in {"reported_material", "skin_type"} for item in items)


def test_confirmed_history_keeps_source_session_and_current_denial_does_not_erase_history():
    ctx = context()
    ctx["service_history"] = {
        "identity_basis": "human_confirmed",
        "messages": [buyer("OLD", "照片已经提供", session_id="LINKED")],
    }
    items = supplied_information(ctx, "照片还没发，之前说错了", "CURRENT")
    material = next(item for item in items if item["kind"] == "reported_material")
    assert material["basis"]["session_id"] == "LINKED"
    assert material["status"] == "current_report_conflicts_with_prior_upload"


def test_picture_message_record_does_not_imply_real_file_is_available():
    ctx = context()
    ctx["messages"] = [buyer("IMG", "[图片]", 内容类型="图片", image_available=False)]
    record = next(item for item in supplied_information(ctx, "查售后", "CURRENT")
                  if item["kind"] == "attachment_record")
    assert record["status"] == "asset_not_provided"


def test_structured_order_information_has_order_source_not_staff_guarantee():
    ctx = context()
    items = supplied_information(ctx, "单号多少", "CURRENT")
    order = next(item for item in items if item["kind"] == "order_reference")
    waybill = next(item for item in items if item["label"] == "已有运单字段")
    assert order["status"] == waybill["status"] == "structured_record"
    assert waybill["value"] == "WAYBILL-X" and waybill["basis"]["message_id"] == "ORDER-X"


def test_memory_adds_no_extra_generation_and_risk_priority_remains():
    model = Model(draft())
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    result = agent.assist(context(), "照片已经提供，用后红肿，很担心", "CURRENT")
    assert model.calls == 1
    assert result["risk_level"] == "紧急"
    assert result["communication_brief"]["additional_model_calls"] == 0
    assert result["communication_brief"]["provided_information"]


def test_unknown_skin_statement_cannot_be_built_from_a_question_or_third_person():
    assert not any(item["kind"] == "skin_type" for item in supplied_information(
        context(), "朋友说我是油皮吗？", "CURRENT"))


def test_sources_are_deduplicated_and_memory_output_is_bounded():
    ctx = context()
    ctx["messages"] = [buyer(str(i), "照片已经提供") for i in range(15)]
    items = supplied_information(ctx, "照片已经提供", "CURRENT")
    assert sum(item["kind"] == "reported_material" for item in items) == 1
    assert len(items) <= 8


@pytest.mark.parametrize("text", ["客服已经提供照片", "朋友照片已经发了", "他已经提供截图"])
def test_third_party_upload_report_is_not_customers_own_supplied_material(text):
    items = supplied_information(context(), text, "CURRENT")
    assert not any(item["kind"] == "reported_material" for item in items)


def test_current_image_record_is_retained_only_when_input_matches_saved_message():
    ctx = context()
    ctx["analysis_point"] = "CURRENT-IMG"
    ctx["messages"] = [buyer("CURRENT-IMG", "[图片]", 内容类型="图片", image_available=False)]
    items = supplied_information(ctx, "[图片]", "CURRENT")
    assert any(item["kind"] == "attachment_record" for item in items)
    edited = supplied_information(ctx, "改成只查物流", "CURRENT")
    assert not any(item["kind"] == "attachment_record" for item in edited)


def test_unconfirmed_foreign_session_row_cannot_enter_same_session_memory():
    ctx = context()
    ctx["messages"] = [buyer("FOREIGN", "照片已经提供", session_id="OTHER")]
    assert not any(item["kind"] == "reported_material"
                   for item in supplied_information(ctx, "只查退款", "CURRENT"))
