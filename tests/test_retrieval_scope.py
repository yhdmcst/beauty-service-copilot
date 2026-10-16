from src.knowledge.retrieval_scope import retrieval_scope


def test_structured_order_scope_requires_unambiguous_complete_values():
    ctx = {"evidence": [{"type": "order", "fields": {"商品货号": "SKU1", "品牌": "A", "渠道": "店铺"}}]}
    result = retrieval_scope(ctx, "shipment_query")
    assert result["product_id"] == "SKU1" and result["brand"] == "A" and result["channel"] == "店铺"
    ctx["evidence"].append({"type": "order", "fields": {"商品货号": "SKU2"}})
    assert "product_id" not in retrieval_scope(ctx, "shipment_query")
    assert "brand" not in retrieval_scope(ctx, "shipment_query")


def test_model_intent_change_refreshes_knowledge_and_audits_repair():
    import json
    from types import SimpleNamespace
    from src.agents.assist_agent import AssistAgent
    from tests.test_service_guidance import context, draft, NoKnowledge
    class Model:
        model = "fixture"
        provider = "ollama"
        calls = 0
        def generate_with_usage(self, prompt, max_tokens):
            self.calls += 1
            return SimpleNamespace(text=json.dumps({**draft(), "t": "logistics_query"}),
                                   input_tokens=10, output_tokens=10, model=self.model)
    model = Model()
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    queries = []
    def retrieve(message, intent, context=None):
        queries.append((intent, context))
        return {"reason": "requires_human", "confidence": 0, "can_auto_reply": False,
                "retrieved_docs": [], "verified_context": "", "procedure_context": "旧范围流程"}
    agent.retrieve_knowledge = retrieve
    ctx = context(); ctx["product_id"] = "SKU1"
    result = agent.assist(ctx, "先别退款，查物流", "S1")
    assert result["intent"] == "logistics_query" and model.calls == 1
    assert queries[-1][1]["product_id"] == "SKU1"
    # Force a distinct correction to exercise invalidation rather than a
    # same-intent model confirmation.
    signals = agent.inspect(ctx, "你好", "S1", "A2")
    result = agent.assist(ctx, "你好", "S1", signals=signals)
    assert queries[-2][0] == "general_consultation"
    assert queries[-1][0] == "logistics_query"
    assert "knowledge_scope_changed_after_generation" in result["validation_flags"]
    assert result["quality_adjustments"]
