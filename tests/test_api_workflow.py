"""Integration: safe handoff, socket notification and input validation."""

from src.agents.intent_agent import IntentAgent
from src.agents.emotion_agent import EmotionAgent
from src.api.app_upgraded import create_app
from src.api.websocket_handler import socketio
from src.risk.beauty_risk_rules import detect_risks
from src.agents.risk_agent import RiskAgent
from src.agents.knowledge_agent import KnowledgeAgent
from src.agents.response_agent import ResponseAgent
from src.knowledge.rag_engine import RAGEngine
from src.agents.intent_agent import IntentAgent
from src.agents.emotion_agent import EmotionAgent
from src.orchestration.langgraph_workflow import CustomerServiceWorkflow


def test_chat_handoff_and_realtime_alert():
    app = create_app()
    http = app.test_client()
    socket = socketio.test_client(app)
    response = http.post("/chat", json={"message": "用了精华脸上红肿刺痛", "session_id": "s1"})
    assert response.status_code == 200
    assert response.json["action"] == "escalate_urgent"
    assert response.json["metadata"]["valence"] < 0
    assert "就医" in response.json["response"]
    received = socket.get_received()
    assert any(item["name"] == "new_alert" for item in received)
    assert http.get("/api/dashboard").json["high_risk"] >= 1
    assert http.get("/api/dashboard").json["emotion_trend"][-1]["valence"] < 0
    assert http.get("/api/cost").json["cost"]["sessions"] >= 1
    assert http.get("/dashboard").status_code == 200
    assert "pricing_configured" in http.get("/api/cost").json["cost"]
    socket.disconnect()


def test_api_validation_and_policy_gate():
    client = create_app().test_client()
    assert client.post("/chat", data="{}", content_type="text/plain").status_code == 400
    assert client.post("/chat", json={"message": ""}).status_code == 400
    assert client.post("/chat", json={"message": "x" * 2001}).status_code == 400
    assert client.post("/chat", json={"message": "您好", "user_profile": []}).status_code == 400
    assert client.post("/chat", json={"message": "您好", "user_profile": {"history": []}}).status_code == 400
    assert client.post("/chat", json={"message": "您好", "user_profile": {"emotion_history": {}}}).status_code == 400
    assert client.post("/chat", json={"message": "您好", "user_profile": {"history": {"refund_count_30d": "2"}}}).status_code == 400
    assert client.post("/chat", json={"message": "您好", "user_profile": {"emotion_history": ["sad"]}}).status_code == 400
    answer = client.post("/chat", json={"message": "敏感肌能用这款吗"}).json
    assert answer["action"] == "human_review"
    assert answer["metadata"]["knowledge_confidence"] == 0


def test_regression_classification_and_alert_rules():
    assert IntentAgent().classify("用了后过敏了要退款")["intent_name"] == "allergy_reaction"
    assert EmotionAgent().analyze("这价格真不值")["special_emotion"] == "price_dissatisfaction"
    assert detect_risks("退货申请", {"refund_count_30d": 2})[0]["level"] == "high"
    assert detect_risks("会不会过敏？") == []
    direct = RiskAgent().assess_risk("用了后红肿刺痛", {"intent_name": "general_consultation"},
                                   {"emotion_risk_score": 0}, {})
    assert direct["risk_level"] == "critical" and direct["need_escalation"]


def test_verified_test_fixture_reaches_auto_reply_and_cache():
    """A synthetic approved fixture checks the path, not production evidence."""
    faq = {"id": "test-approved", "title": "面霜怎么用 使用方法 步骤",
           "content": "这个面霜怎么用 使用方法 步骤：依商品已审核说明使用。",
           "source": "test_fixture", "verified": True}
    agent = ResponseAgent()
    workflow = CustomerServiceWorkflow(
        IntentAgent(), EmotionAgent(),
        KnowledgeAgent(RAGEngine(documents=[faq])), agent, RiskAgent())
    query = "这个面霜怎么用 使用方法 步骤"
    result = workflow.run(query, {}, "fixture-1")
    assert result["action"] == "auto_reply"
    assert result["metadata"]["response_strategy"] == "rule"
    assert result["cost_info"]["input_tokens"] == 0
    workflow.run(query, {}, "fixture-2")
    assert agent.cache.stats()["hits"] == 1
    assert agent.tracker.get_stats()["sessions"] == 2


def test_competitor_alert_requests_review_not_escalation():
    client = create_app().test_client()
    result = client.post("/chat", json={"message": "和SK-II相比哪个好"}).json
    assert result["action"] == "human_review"
    assert result["metadata"]["alerts"][0]["level"] == "medium"
