"""Retrieval contracts and conservative answerability checks."""

import pytest

from src.agents.knowledge_agent import KnowledgeAgent
from src.knowledge.answerable_gate import AnswerableGate
from src.knowledge.rag_engine import RAGEngine, tokenize
from src.knowledge.vector_store import VectorStore
from src.models.embedding_model import EmbeddingModel


def test_embedding_cache_is_stable_and_isolated():
    model = EmbeddingModel("local")
    vectors = model.embed_batch(["敏感肌", "烟酰胺", "敏感肌"])
    assert len(vectors) == 3 and len(vectors[0]) == 512
    assert vectors[0] == vectors[2] and len(model._cache) == 2
    vectors[0][0] = 999
    assert model.embed("敏感肌")[0] != 999


def test_vector_store_upsert_and_rank():
    store = VectorStore(EmbeddingModel("local"))
    docs = [{"title": "烟酰胺成分", "content": "含烟酰胺", "source": "内部"},
            {"title": "发货说明", "content": "物流配送", "source": "内部"}]
    assert store.add_documents(docs, batch_size=1) == 2
    assert store.add_documents(docs) == 2
    assert len(store.documents) == 2
    assert "烟酰胺" in store.search("烟酰胺")[0]["title"]
    assert store.search("任何问题", top_k=0) == []
    with pytest.raises(ValueError):
        store.add_documents(docs, batch_size=0)


def test_bm25_rrf_and_tokenizer():
    docs = [{"id": "a", "title": "敏感肌保湿", "content": "温和保湿", "source": "已审核"},
            {"id": "b", "title": "物流配送", "content": "快递送货", "source": "已审核"}]
    engine = RAGEngine(documents=docs)
    assert tokenize("敏感肌") and engine.hybrid_search("敏感肌")[0]["id"] == "a"
    assert len(engine.reciprocal_rank_fusion([docs[0]], [docs[0]])) == 1
    assert engine.hybrid_search("") == []


def test_unverified_and_sensitive_evidence_rejected():
    gate = AnswerableGate()
    query = "敏感肌怎么保湿"
    doc = {"title": "敏感肌保湿", "content": "敏感肌怎么保湿", "source": "模拟样本",
           "verified": True}
    assert not gate.can_answer(query, [doc])
    assert not gate.can_answer(query, [], "skin_type_match")
    doc["source"] = "审核资料"
    assert gate.can_answer(query, [doc], "skin_type_match")
    assert not gate.can_answer("我过敏了", [doc], "allergy_reaction")


def test_knowledge_agent_handoff_without_verified_data():
    agent = KnowledgeAgent()
    result = agent.search("敏感肌可以用吗", "skin_type_match")
    assert result["retrieved_docs"] and not result["can_auto_reply"]
    assert result["reason"] == "unverified_evidence"


def test_qdrant_client_local_contract():
    """Exercise actual Qdrant client APIs without claiming remote Docker success."""
    from qdrant_client import QdrantClient

    model = EmbeddingModel("local")
    store = VectorStore(
        embedding_model=model, backend="qdrant", client=QdrantClient(":memory:"),
        collection_name="contract_test",
    )
    store.add_documents([
        {"title": "烟酰胺成分", "content": "烟酰胺成分介绍", "verified": True},
        {"title": "订单物流", "content": "快递配送进度", "verified": True},
    ])
    results = store.search("烟酰胺")
    assert results and results[0]["title"] == "烟酰胺成分"
