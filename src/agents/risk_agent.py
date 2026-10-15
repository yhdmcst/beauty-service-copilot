"""
风险评估Agent
"""

from typing import Dict, List
from enum import Enum
from src.risk.beauty_risk_rules import detect_risks, is_active_keyword


class RiskLevel(Enum):
    """风险等级"""
    CRITICAL = "critical"  # 红色预警（≥90分）
    HIGH = "high"          # 黄色预警（≥70分）
    MEDIUM = "medium"      # 蓝色预警（≥50分）
    LOW = "low"            # 正常（<50分）


class RiskAgent:
    """风险评估Agent - 美妆场景专属"""
    
    def __init__(self):
        """初始化风险评估Agent"""
        
        # 敏感词库（投诉、法律、舆情相关）
        self.sensitive_keywords = {
            "complaint": ["投诉", "12315", "315", "消协", "举报", "曝光"],
            "legal": ["起诉", "律师", "法律", "法院", "报警", "诉讼"],
            "social_media": ["微博", "抖音", "小红书", "曝光", "差评", "黑名单"],
            "competitor": ["SK-II", "雅诗兰黛", "兰蔻", "资生堂", "欧莱雅", "比你们", "其他家"]
        }
        
        # 质量问题关键词
        self.quality_keywords = ["假货", "假的", "不是正品", "质量问题", "三无", "过期"]
    
    def calculate_emotion_risk(self, emotion_data: Dict) -> int:
        """
        情绪风险（0-40分）
        
        Args:
            emotion_data: 来自EmotionAgent的情绪分析结果
        """
        score = emotion_data.get("emotion_risk_score", 0)
        return min(score, 40)
    
    def calculate_behavior_risk(self, user_history: Dict) -> int:
        """
        行为风险（0-30分）
        
        Args:
            user_history: 用户历史行为数据
            {
                "refund_count_30d": 30天内退款次数,
                "repeat_contact_7d": 7天内重复咨询次数,
                "complaint_count": 历史投诉次数,
                "avg_satisfaction": 平均满意度(1-5)
            }
        """
        score = 0
        
        # 重复退款（最高20分）
        refund_count = user_history.get("refund_count_30d", 0)
        if refund_count >= 3:
            score += 20
        elif refund_count >= 2:
            score += 15
        elif refund_count >= 1:
            score += 5
        
        # 重复进线（最高15分）
        repeat_contact = user_history.get("repeat_contact_7d", 0)
        if repeat_contact >= 5:
            score += 15
        elif repeat_contact >= 3:
            score += 10
        elif repeat_contact >= 2:
            score += 5
        
        # 历史投诉（最高20分）
        complaint_count = user_history.get("complaint_count", 0)
        if complaint_count >= 2:
            score += 20
        elif complaint_count >= 1:
            score += 10
        
        # 满意度低（最高10分）
        avg_satisfaction = user_history.get("avg_satisfaction", 5.0)
        if avg_satisfaction < 3.0:
            score += 10
        elif avg_satisfaction < 4.0:
            score += 5
        
        return min(score, 30)
    
    def calculate_content_risk(self, text: str, intent: str) -> int:
        """
        内容风险（0-20分）
        
        Args:
            text: 用户输入文本
            intent: 识别的意图
        """
        score = 0
        text_lower = text.lower()
        
        # 投诉威胁（最高15分）
        if any(is_active_keyword(text_lower, kw) for kw in self.sensitive_keywords["complaint"]):
            score += 15
        
        # 法律维权（最高20分）
        if any(is_active_keyword(text_lower, kw) for kw in self.sensitive_keywords["legal"]):
            score += 20
        
        # 舆情威胁（最高12分）
        if any(is_active_keyword(text_lower, kw) for kw in self.sensitive_keywords["social_media"]):
            score += 12
        
        # 竞品提及（最高8分）
        if any(is_active_keyword(text_lower, kw) for kw in self.sensitive_keywords["competitor"]):
            score += 8
        
        # 质疑真假（最高10分）
        if any(is_active_keyword(text_lower, kw) for kw in self.quality_keywords):
            score += 10
        
        return min(score, 20)
    
    def calculate_intent_risk(self, intent: str) -> int:
        """
        意图风险（0-10分）
        
        高风险意图本身就代表风险
        """
        high_risk_intents = {
            "allergy_reaction": 10,      # 过敏反应
            "quality_issue": 8,          # 质量问题
            "refund_request": 6,         # 退款申请
            "authenticity_check": 5      # 真假鉴别
        }
        
        return high_risk_intents.get(intent, 0)
    
    def assess_risk(
        self, 
        text: str, 
        intent_data: Dict, 
        emotion_data: Dict, 
        user_history: Dict
    ) -> Dict:
        """
        综合风险评估
        
        Args:
            text: 用户输入
            intent_data: 意图识别结果
            emotion_data: 情绪分析结果
            user_history: 用户历史数据
            
        Returns:
            {
                "total_risk_score": 总风险分数(0-100),
                "risk_level": 风险等级,
                "risk_breakdown": 各维度风险分数,
                "triggers": 触发的风险规则,
                "recommended_action": 推荐处理方式,
                "need_escalation": 是否需要升级
            }
        """
        # 1. 计算各维度风险
        emotion_risk = self.calculate_emotion_risk(emotion_data)
        behavior_risk = self.calculate_behavior_risk(user_history)
        content_risk = self.calculate_content_risk(text, intent_data["intent_name"])
        intent_risk = self.calculate_intent_risk(intent_data["intent_name"])
        
        # 2. 总风险分数（加权）
        total_score = (
            emotion_risk +      # 0-40分
            behavior_risk +     # 0-30分
            content_risk +      # 0-20分
            intent_risk         # 0-10分
        )
        
        # 3. 确定风险等级
        if total_score >= 90:
            risk_level = RiskLevel.CRITICAL
        elif total_score >= 70:
            risk_level = RiskLevel.HIGH
        elif total_score >= 50:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW
        
        # 4. 识别触发的风险规则
        triggers = self._identify_triggers(
            text, 
            intent_data, 
            emotion_data, 
            user_history
        )
        alerts = detect_risks(text, user_history)
        if any(alert["level"] == "critical" for alert in alerts):
            total_score = max(total_score, 90)
            risk_level = RiskLevel.CRITICAL
        elif any(alert["level"] == "high" for alert in alerts):
            total_score = max(total_score, 70)
            risk_level = RiskLevel.HIGH
        triggers = list(dict.fromkeys(triggers + [alert["name"] for alert in alerts]))
        
        # 5. 推荐处理方式
        recommended_action = self._recommend_action(risk_level, triggers)
        
        # 6. 是否需要人工介入
        need_escalation = risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]
        
        return {
            "total_risk_score": total_score,
            "risk_level": risk_level.value,
            "risk_level_display": self._get_risk_level_display(risk_level),
            "risk_breakdown": {
                "emotion_risk": emotion_risk,
                "behavior_risk": behavior_risk,
                "content_risk": content_risk,
                "intent_risk": intent_risk
            },
            "triggers": triggers,
            "recommended_action": recommended_action,
            "need_escalation": need_escalation,
            "escalation_reason": self._get_escalation_reason(risk_level, triggers)
        }
    
    def _identify_triggers(
        self, 
        text: str, 
        intent_data: Dict, 
        emotion_data: Dict, 
        user_history: Dict
    ) -> List[str]:
        """识别触发的风险规则"""
        triggers = []
        
        # 过敏反应
        if intent_data["intent_name"] == "allergy_reaction":
            triggers.append("过敏反应（紧急处理）")
        
        # 情绪升级
        if emotion_data.get("emotion_change"):
            change = emotion_data["emotion_change"]
            if change.get("alert"):
                triggers.append(f"情绪急剧恶化（Δ={change['delta_valence']:.2f}）")
        
        # 投诉威胁
        if any(is_active_keyword(text.lower(), kw) for kw in self.sensitive_keywords["complaint"]):
            triggers.append("投诉威胁")
        
        # 法律维权
        if any(is_active_keyword(text.lower(), kw) for kw in self.sensitive_keywords["legal"]):
            triggers.append("法律维权威胁")
        
        # 舆情风险
        if any(is_active_keyword(text.lower(), kw) for kw in self.sensitive_keywords["social_media"]):
            triggers.append("舆情传播风险")
        
        # 重复退款
        if (user_history.get("refund_count_30d") or 0) >= 2:
            triggers.append(f"重复退款（{user_history['refund_count_30d']}次/30天）")
        
        # 质疑真假
        if any(is_active_keyword(text.lower(), kw) for kw in self.quality_keywords):
            triggers.append("质疑商品真伪")
        
        return triggers
    
    def _recommend_action(self, risk_level: RiskLevel, triggers: List[str]) -> str:
        """推荐处理方式"""
        if risk_level == RiskLevel.CRITICAL:
            return "立即转资深客服 + 主管关注 + 48小时跟进"
        elif risk_level == RiskLevel.HIGH:
            return "转资深客服处理 + 重点关注"
        elif risk_level == RiskLevel.MEDIUM:
            return "AI辅助 + 人工复核"
        else:
            return "AI自动回复"
    
    def _get_escalation_reason(self, risk_level: RiskLevel, triggers: List[str]) -> str:
        """获取升级原因"""
        if risk_level == RiskLevel.CRITICAL:
            return f"极高风险，触发规则：{', '.join(triggers[:3])}"
        elif risk_level == RiskLevel.HIGH:
            return f"高风险，触发规则：{', '.join(triggers[:2])}"
        else:
            return ""
    
    def _get_risk_level_display(self, risk_level: RiskLevel) -> str:
        """获取风险等级显示文本"""
        displays = {
            RiskLevel.CRITICAL: "🚨 极高风险",
            RiskLevel.HIGH: "⚠️ 高风险",
            RiskLevel.MEDIUM: "💡 中风险",
            RiskLevel.LOW: "✅ 正常"
        }
        return displays.get(risk_level, "未知")


# 测试代码
if __name__ == "__main__":
    agent = RiskAgent()
    
    # 模拟测试数据
    test_cases = [
        {
            "text": "我要投诉你们，打12315举报，还要在微博上曝光！",
            "intent": {"intent_name": "refund_request"},
            "emotion": {"emotion_risk_score": 35, "valence": -0.8},
            "history": {"refund_count_30d": 3, "complaint_count": 1}
        },
        {
            "text": "用了三天脸上过敏了，红肿得厉害",
            "intent": {"intent_name": "allergy_reaction"},
            "emotion": {"emotion_risk_score": 35, "valence": -0.8},
            "history": {"refund_count_30d": 0, "complaint_count": 0}
        },
        {
            "text": "这个面霜怎么样？适合干皮吗？",
            "intent": {"intent_name": "skin_type_match"},
            "emotion": {"emotion_risk_score": 0, "valence": 0.0},
            "history": {"refund_count_30d": 0, "complaint_count": 0}
        }
    ]
    
    print("=" * 60)
    print("风险评估测试")
    print("=" * 60)
    
    for i, case in enumerate(test_cases, 1):
        result = agent.assess_risk(
            case["text"],
            case["intent"],
            case["emotion"],
            case["history"]
        )
        
        print(f"\n案例 {i}: {case['text']}")
        print(f"风险等级: {result['risk_level_display']}")
        print(f"风险分数: {result['total_risk_score']}/100")
        print(f"分数分解: 情绪{result['risk_breakdown']['emotion_risk']} + "
              f"行为{result['risk_breakdown']['behavior_risk']} + "
              f"内容{result['risk_breakdown']['content_risk']} + "
              f"意图{result['risk_breakdown']['intent_risk']}")
        print(f"触发规则: {', '.join(result['triggers']) if result['triggers'] else '无'}")
        print(f"推荐处理: {result['recommended_action']}")
        print(f"需要升级: {'是' if result['need_escalation'] else '否'}")
