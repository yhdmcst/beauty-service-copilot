"""Accuracy guards, bounded inference and independent evaluation contracts."""

import json
import threading
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from src.agents.assist_agent import AssistAgent, FALLBACK_REPLY
from src.agents.intent_agent import IntentAgent
from src.api.app_upgraded import create_app
from src.knowledge.business_claims import check_claims
from src.models.qwen_wrapper import QwenWrapper
from src.ops.case_store import CaseStore
from src.orchestration.workbench_workflow import WorkbenchWorkflow
from evaluation.evaluation_center import FrozenAnnotationAgent, _normalize_context
from tests.test_workbench_v2 import Model, data_store


@pytest.mark.parametrize("text", [
    "没有红肿，只查物流", "已经不过敏了，也没有刺痛",
    "没有呼吸困难",
])
def test_negated_intent_is_not_active_adverse_reaction(text):
    assert IntentAgent().classify(text)["intent_name"] != "allergy_reaction"


@pytest.mark.parametrize("text,flag", [
    ("已为您提交退款申请", "unsupported_commitment"),
    ("已安排全额退款", "unsupported_commitment"),
    ("一定到账", "unsupported_commitment"),
    ("预计晚1-2天送达", "unsupported_time_promise"),
    ("1-3个工作日内到账", "unsupported_time_promise"),
    ("快递公司反馈拦截成功", "unsupported_intercept_complete"),
    ("地址修改成功", "unsupported_intercept_complete"),
    ("产品引发过敏", "unsupported_medical_conclusion"),
])
def test_unproved_promises_are_blocked(text, flag):
    assert flag in check_claims(text, [], [])["flags"]


def test_risk_is_persisted_before_slow_retrieval():
    began, release = threading.Event(), threading.Event()

    class SlowKnowledge:
        def search(self, query, intent):
            began.set()
            assert release.wait(2)
            return {"retrieved_docs": [], "confidence": 0, "can_auto_reply": False,
                    "reason": "no_evidence"}

    cases = CaseStore()
    agent = AssistAgent(Model(), SlowKnowledge())
    flow = WorkbenchWorkflow(data_store(), agent, cases, lambda e: None)
    prepared = flow.prepare("S00381", "要投诉12315", None, "snapshot")
    assert prepared["task_ids"] and not began.is_set()
    thread = threading.Thread(target=lambda: flow.run_prepared(prepared))
    thread.start()
    try:
        assert began.wait(1)
        assert cases.list_tasks()[0]["priority"] == "high"
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()


def test_blocked_knowledge_body_never_enters_prompt():
    class Knowledge:
        def search(self, query, intent):
            return {"retrieved_docs": [{"id": "K", "verified": True,
                    "title": "测试", "content": "秘密测试政策全文"}],
                    "confidence": 0, "reason": "unverified_evidence", "can_auto_reply": False}
    model = Model()
    AssistAgent(model, Knowledge()).assist(data_store().get_session("S00381"), "查物流", "S00381")
    assert "秘密测试政策全文" not in model.prompts[0]


def test_unknown_citation_cannot_leave_fact_reply():
    class UnknownModel(Model):
        def generate_with_usage(self, prompt, max_tokens=360):
            result = super().generate_with_usage(prompt, max_tokens)
            draft = json.loads(result.text)
            draft["evidence_ids"] = ["NOT-PROVIDED"]
            result.text = json.dumps(draft, ensure_ascii=False)
            return result
    result = AssistAgent(UnknownModel()).assist(data_store().get_session("S00381"), "查物流", "S00381")
    assert result["suggested_reply"] == FALLBACK_REPLY
    assert "unknown_evidence_removed" in result["validation_flags"]


def test_compact_prompt_keeps_all_structured_values():
    agent = AssistAgent(Model())
    context = data_store().get_session("S00381")
    signals = agent.inspect(context, "查物流", "S00381", "A")
    prompt = agent.build_prompt(context, "查物流", "S00381", signals)
    bundle = json.loads(prompt.split("\n", 2)[2].split("\n\n请严格", 1)[0])
    assert len(bundle["context"]["evidence"]) == len(context["evidence"])
    for original, compact in zip(context["evidence"], bundle["context"]["evidence"]):
        assert original["id"] == compact["id"]
        for key, value in original["fields"].items():
            if value not in ("", None) and key not in {"订单号", "工单号"}:
                assert compact["fields"][key] == value


def test_prompt_includes_service_focus_and_action_boundaries():
    agent = AssistAgent(Model())
    context = data_store().get_session("S00001")
    signals = agent.inspect(context, "收到的粉底液泵头坏了，按不出来", "S00001", "A")
    prompt = agent.build_prompt(context, "收到的粉底液泵头坏了，按不出来", "S00001", signals)
    assert '"category":"product_usability_or_damage"' in prompt
    assert "不预判物流责任" in prompt
    assert "不得写我们正在核实" in prompt


def test_focus_prioritizes_address_and_adverse_reaction():
    agent = AssistAgent(Model())
    address = agent.inspect(
        data_store().get_session("S00107"),
        "订单地址填错了，还没到货，能改吗",
        "S00107",
        "A-address",
    )
    assert address["service_focus"]["category"] == "address_change"
    adverse = agent.inspect(
        data_store().get_session("S00154"),
        "用了面霜整张脸肿了，医生说是接触性皮炎",
        "S00154",
        "A-adverse",
    )
    assert adverse["service_focus"]["category"] == "adverse_reaction_report"
    pre_sale = agent.inspect(
        data_store().get_session("S00012"),
        "预售尾款什么时候付",
        "S00012",
        "A-presale",
    )
    assert pre_sale["service_focus"]["category"] == "pre_sale_payment"


def test_unsafe_generated_wording_is_rewritten_to_buyer_attribution():
    class UnsafeModel(Model):
        def generate_with_usage(self, prompt, max_tokens=360):
            result = super().generate_with_usage(prompt, max_tokens)
            draft = json.loads(result.text)
            draft.update({
                "summary": "用户使用后出现过敏反应，需紧急处理。",
                "suggested_reply": "您好，我们注意到物流显示已签收，我们正在核实。",
                "next_action": "我们已记录问题，正在核实物流。",
            })
            result.text = json.dumps(draft, ensure_ascii=False)
            return result

    context = data_store().get_session("S00009")
    result = AssistAgent(UnsafeModel()).assist(
        context, "搞啥啊！物流显示昨天已签收，我根本没收到货", "S00009"
    )
    assert "过敏反应" not in result["summary"]
    assert "正在核实" not in result["suggested_reply"]
    assert "我们已记录" not in result["next_action"]
    assert "unsupported_external_delivery_observation" in result["validation_flags"]


def test_provider_schema_request():
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2))
    QwenWrapper("test", client=client, provider="ollama").generate_structured(
        "test", {"type": "object"})
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["max_tokens"] == 360


def test_immediate_safety_skips_model_and_knowledge():
    model, knowledge = Model(), Mock()
    result = AssistAgent(model, knowledge).assist(
        data_store().get_session("S00381"), "用了后呼吸困难", "S00381")
    assert result["model_status"] == "rule_safety"
    assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert model.calls == 0
    knowledge.search.assert_not_called()


def test_normalized_frozen_point_is_not_its_own_history():
    store = FrozenAnnotationAgent(":memory:")
    sample = store.get_sample(store.list_samples("heldout")[0]["sample_id"])
    context = _normalize_context(sample)
    signals = AssistAgent(Model()).inspect(context, sample["buyer_message"], sample["sample_id"], "A")
    assert signals["emotion_trend"]["history"] == []
    assert signals["knowledge"]["reason"] == "not_requested"


def test_efficiency_cannot_pair_different_people():
    store = FrozenAnnotationAgent(":memory:")
    task = store.list_efficiency_tasks()[0]["task_id"]
    for method, person in (("manual", "A"), ("copilot", "B")):
        trial = store.start_trial(task, method, person)
        store.stop_trial(trial["trial_id"], {"missed_facts": 0, "edit_count": 0, "success": True})
    assert store.efficiency_report()["paired_tasks"] == 0
    with pytest.raises(ValueError):
        store.start_trial(task, "manual", "A")


def test_study_manual_cannot_invoke_model_and_bundle_excludes_labels():
    app = create_app(assist_agent=AssistAgent(Model()), case_store=CaseStore(),
                     evaluation_store=FrozenAnnotationAgent(":memory:"))
    client = app.test_client()
    task = client.get("/api/evaluation/efficiency/tasks").json["tasks"][0]["task_id"]
    trial = client.post("/api/evaluation/efficiency/trials",
                        json={"task_id": task, "method": "manual", "operator": "A"}).json["trial"]
    detail = client.get(f"/api/evaluation/efficiency/trials/{trial['trial_id']}").json
    assert "human_annotation" not in detail["sample"]
    assert detail["sample"]["context"]["analysis_mode"] == "replay"
    assert client.post(f"/api/evaluation/efficiency/trials/{trial['trial_id']}/assist").status_code == 400
    app.extensions["analysis_jobs"].close()
