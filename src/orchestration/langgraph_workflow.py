"""
Agent编排 - 使用LangGraph构建5-Agent工作流
"""

from typing import TypedDict, Dict, List
from langgraph.graph import StateGraph, END
import logging
import time

from src.risk.beauty_risk_rules import detect_risks

logger = logging.getLogger(__name__)


# 定义Agent状态
class AgentState(TypedDict):
    """Agent工作流状态"""
    
    # 输入
    user_input: str
    user_id: str
    session_id: str
    
    # 用户画像
    user_profile: Dict
    
    # Intent Agent输出
    intent: str
    intent_confidence: float
    is_high_risk_intent: bool
    
    # Emotion Agent输出
    emotion: str
    special_emotion: str
    valence: float
    arousal: float
    emotion_risk_score: int
    emotion_history: List[Dict]
    
    # Knowledge Agent输出
    retrieved_docs: List[Dict]
    approved_docs: List[Dict]
    can_auto_reply: bool
    knowledge_confidence: float
    
    # Response Agent输出
    draft_response: str
    response_strategy: str  # "rule" | "small_model" | "large_model"
    
    # Risk Agent输出
    risk_score: int
    risk_level: str
    risk_triggers: List[str]
    need_escalation: bool
    rule_alerts: List[Dict]
    
    # 最终决策
    final_response: str
    action: str  # "auto_reply" | "human_review" | "escalate"
    cost_info: Dict


class CustomerServiceWorkflow:
    """客服Agent工作流编排"""
    
    def __init__(
        self,
        intent_agent,
        emotion_agent,
        knowledge_agent,
        response_agent,
        risk_agent
    ):
        """
        初始化工作流
        
        Args:
            intent_agent: IntentAgent实例
            emotion_agent: EmotionAgent实例
            knowledge_agent: KnowledgeAgent实例
            response_agent: ResponseAgent实例
            risk_agent: RiskAgent实例
        """
        self.intent_agent = intent_agent
        self.emotion_agent = emotion_agent
        self.knowledge_agent = knowledge_agent
        self.response_agent = response_agent
        self.risk_agent = risk_agent
        
        # 构建工作流图
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile()
    
    def _build_workflow(self) -> StateGraph:
        """构建LangGraph工作流"""
        
        workflow = StateGraph(AgentState)
        
        # 添加节点
        workflow.add_node("intent", self.intent_node)
        workflow.add_node("emotion", self.emotion_node)
        workflow.add_node("knowledge", self.knowledge_node)
        workflow.add_node("response", self.response_node)
        workflow.add_node("risk", self.risk_node)
        
        # 设置入口点
        workflow.set_entry_point("intent")
        
        # 风险判定先于知识检索和回复，避免高风险问题调用模型
        workflow.add_edge("intent", "emotion")
        workflow.add_edge("emotion", "risk")
        workflow.add_edge("risk", "knowledge")
        workflow.add_edge("knowledge", "response")
        
        # 根据最终风险和证据决策
        workflow.add_conditional_edges(
            "response",
            self.should_escalate,
            {
                "auto_reply": END,
                "human_review": END,
                "escalate": END
            }
        )
        
        return workflow
    
    def intent_node(self, state: AgentState) -> Dict:
        """Intent Agent节点"""
        result = self.intent_agent.classify(state["user_input"])
        
        return {
            "intent": result["intent_name"],
            "intent_confidence": result["confidence"],
            "is_high_risk_intent": result["is_high_risk"]
        }
    
    def emotion_node(self, state: AgentState) -> Dict:
        """Emotion Agent节点"""
        result = self.emotion_agent.analyze(
            state["user_input"],
            history_emotions=state.get("emotion_history", [])
        )
        
        return {
            "emotion": result["basic_emotion"],
            "special_emotion": result["special_emotion"],
            "valence": result["valence"],
            "arousal": result["arousal"],
            "emotion_risk_score": result["emotion_risk_score"]
        }
    
    def knowledge_node(self, state: AgentState) -> Dict:
        """Knowledge Agent节点"""
        try:
            result = self.knowledge_agent.search(
                query=state["user_input"], intent=state["intent"],
                user_profile=state["user_profile"],
            )
        except Exception as error:
            logger.warning("Knowledge retrieval unavailable: %s", type(error).__name__)
            result = {
                "retrieved_docs": [], "can_auto_reply": False,
                "confidence": 0.0, "reason": "knowledge_unavailable",
            }
        return {
            "retrieved_docs": result["retrieved_docs"],
            "approved_docs": result.get("approved_docs", []),
            "can_auto_reply": bool(result["can_auto_reply"] and result.get("approved_docs")),
            "knowledge_confidence": result["confidence"]
        }
    
    def response_node(self, state: AgentState) -> Dict:
        """Response Agent节点"""
        if state["need_escalation"]:
            return {"draft_response": None, "response_strategy": "escalate", "cost_info": {}}
        if state.get("rule_alerts"):
            return {"draft_response": None, "response_strategy": "handoff", "cost_info": {}}
        # 如果知识库无法回答，直接转人工
        if not state["can_auto_reply"]:
            return {
                "draft_response": None,
                "response_strategy": "escalate"
            }
        
        result = self.response_agent.generate(
            user_input=state["user_input"], intent=state["intent"],
            emotion={"emotion": state["emotion"], "valence": state["valence"]},
            knowledge_docs=state["approved_docs"], user_profile=state["user_profile"],
            session_id=state["session_id"], can_auto_reply=state["can_auto_reply"],
        )
        return {
            "draft_response": result["response"],
            "response_strategy": result["strategy"],
            "cost_info": result.get("cost_info", {}),
        }
    
    def risk_node(self, state: AgentState) -> Dict:
        """Risk Agent节点"""
        result = self.risk_agent.assess_risk(
            text=state["user_input"],
            intent_data={
                "intent_name": state["intent"],
                "confidence": state["intent_confidence"]
            },
            emotion_data={
                "emotion_risk_score": state["emotion_risk_score"],
                "valence": state["valence"]
            },
            user_history=state["user_profile"].get("history", {})
        )
        alerts = detect_risks(state["user_input"], state["user_profile"].get("history", {}))
        level = "critical" if any(item["level"] == "critical" for item in alerts) else result["risk_level"]
        
        return {
            "risk_score": result["total_risk_score"],
            "risk_level": level,
            "risk_triggers": list(dict.fromkeys(result["triggers"] + [item["name"] for item in alerts])),
            "rule_alerts": alerts,
            "need_escalation": result["need_escalation"] or any(
                item["level"] in ("critical", "high") for item in alerts),
        }
    
    def should_escalate(self, state: AgentState) -> str:
        """决策函数：是否需要升级"""
        
        # 1. 高风险直接升级
        if state["need_escalation"]:
            return "escalate"
        
        # 2. 意图置信度低，需要人工复核
        if state["intent_confidence"] < 0.7:
            return "human_review"
        
        # 3. 知识库无法回答
        if not state["can_auto_reply"] or state.get("response_strategy") == "handoff":
            return "human_review"
        
        # 4. 正常情况，AI自动回复
        return "auto_reply"
    
    def run(self, user_input: str, user_profile: Dict, session_id: str) -> Dict:
        """
        执行完整工作流
        
        Args:
            user_input: 用户输入
            user_profile: 用户画像
            session_id: 会话ID
            
        Returns:
            完整的处理结果
        """
        # 初始化状态
        if not isinstance(user_input, str) or not user_input.strip() or len(user_input) > 2000:
            raise ValueError("user_input must be 1-2000 characters")
        started = time.perf_counter()
        initial_state = {
            "user_input": user_input,
            "user_id": user_profile.get("user_id", "unknown"),
            "session_id": session_id,
            "user_profile": user_profile,
            "emotion_history": user_profile.get("emotion_history", [])
        }
        
        # 运行工作流
        final_state = self.app.invoke(initial_state)
        self.response_agent.tracker.record_session(session_id)
        
        # 格式化输出
        action = self._determine_action(final_state)
        logger.info("Session %s intent=%s action=%s", session_id, final_state["intent"], action)
        return {
            "response": final_state.get("draft_response") if action == "auto_reply"
                        else "建议客服优先处理。若有明显不适，请立即停用产品并及时就医。"
                        if final_state["risk_level"] == "critical"
                        else "建议由人工客服进一步核实当前问题与业务记录。",
            "action": action,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "cost_info": final_state.get("cost_info", {}),
            "metadata": {
                "intent": final_state["intent"],
                "intent_confidence": final_state["intent_confidence"],
                "emotion": final_state["emotion"],
                "special_emotion": final_state.get("special_emotion"),
                "valence": final_state["valence"],
                "risk_score": final_state["risk_score"],
                "risk_level": final_state["risk_level"],
                "risk_triggers": final_state["risk_triggers"],
                "need_escalation": final_state["need_escalation"],
                "alerts": final_state["rule_alerts"],
                "response_strategy": final_state["response_strategy"],
                "knowledge_confidence": final_state["knowledge_confidence"],
            }
        }
    
    def _determine_action(self, state: AgentState) -> str:
        """确定最终动作"""
        if state["need_escalation"]:
            if state["risk_level"] == "critical":
                return "escalate_urgent"  # 紧急升级
            else:
                return "escalate"  # 普通升级
        elif state["intent_confidence"] < 0.7 or not state["can_auto_reply"] or state["response_strategy"] == "handoff":
            return "human_review"  # 人工复核
        else:
            return "auto_reply"  # 自动回复


# 测试代码
if __name__ == "__main__":
    from src.agents.intent_agent import IntentAgent
    from src.agents.emotion_agent import EmotionAgent
    from src.agents.risk_agent import RiskAgent
    from src.agents.knowledge_agent import KnowledgeAgent
    from src.agents.response_agent import ResponseAgent
    
    # 初始化Agents
    intent_agent = IntentAgent()
    emotion_agent = EmotionAgent()
    risk_agent = RiskAgent()
    
    # 创建完整工作流
    workflow = CustomerServiceWorkflow(
        intent_agent=intent_agent,
        emotion_agent=emotion_agent,
        knowledge_agent=KnowledgeAgent(),
        response_agent=ResponseAgent(),
        risk_agent=risk_agent
    )
    
    # 测试用户画像
    test_user_profile = {
        "user_id": "test_001",
        "name": "张小姐",
        "age": 25,
        "skin_type": "混合偏油",
        "vip_level": 3,
        "history": {
            "refund_count_30d": 0,
            "repeat_contact_7d": 1,
            "complaint_count": 0,
            "avg_satisfaction": 4.5
        },
        "emotion_history": []
    }
    
    # 测试案例
    test_queries = [
        "这个精华含烟酰胺吗？",
        "用了三天脸上过敏了，红肿得厉害！要投诉你们！",
        "和SK-II相比哪个更好？"
    ]
    
    print("=" * 60)
    print("Agent工作流测试")
    print("=" * 60)
    
    for query in test_queries:
        print(f"\n{'=' * 60}")
        print(f"用户输入: {query}")
        print(f"{'=' * 60}")
        
        result = workflow.run(
            user_input=query,
            user_profile=test_user_profile,
            session_id="test_session_001"
        )
        
        print(f"\n最终动作: {result['action']}")
        print(f"\n元数据:")
        for key, value in result['metadata'].items():
            print(f"  {key}: {value}")
