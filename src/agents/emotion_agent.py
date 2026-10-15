"""
美妆场景情绪识别Agent
"""

from typing import Dict, Optional
from enum import Enum
import re
from src.risk.beauty_risk_rules import is_active_keyword
from src.risk.beauty_risk_rules import detect_risks


class BeautyEmotion(Enum):
    """美妆场景特殊情绪"""
    ALLERGY_ANXIETY = "allergy_anxiety"          # 过敏焦虑（高风险）
    EFFECT_DISAPPOINTMENT = "effect_disappointment"  # 效果失望
    PRICE_DISSATISFACTION = "price_dissatisfaction"  # 价格不满
    PURCHASE_HESITATION = "purchase_hesitation"      # 购买犹豫
    SATISFACTION = "satisfaction"                    # 满意
    NEUTRAL = "neutral"                             # 中性


class EmotionAgent:
    """情绪识别Agent"""
    
    def __init__(self, bert_model=None, llm_client=None):
        """
        初始化情绪识别Agent
        
        Args:
            bert_model: MacBERT情感分析模型（SmartCS原有）
            llm_client: LLM客户端（用于复杂情绪分析）
        """
        self.bert_model = bert_model
        self.llm_client = llm_client
        
        # 美妆场景特殊情绪关键词
        self.beauty_emotion_patterns = {
            BeautyEmotion.ALLERGY_ANXIETY: {
                "keywords": ["过敏", "红肿", "红疹", "小疹", "刺痛", "烂脸", "起疹", "发红", "痒", "长痘"],
                "valence": -0.8,  # 情感倾向（-1到1，负面到正面）
                "arousal": 0.9,   # 激动程度（0到1，平静到激动）
                "risk_weight": 1.5
            },
            BeautyEmotion.EFFECT_DISAPPOINTMENT: {
                "keywords": ["没效果", "无效", "白买了", "浪费钱", "效果不好", "失望"],
                "valence": -0.6,
                "arousal": 0.5,
                "risk_weight": 1.2
            },
            BeautyEmotion.PRICE_DISSATISFACTION: {
                "keywords": ["太贵", "被坑", "为什么比", "价格差", "贵这么多",
                             "不划算", "价格比", "这价格", "这么贵", "真不值"],
                "valence": -0.5,
                "arousal": 0.6,
                "risk_weight": 1.3
            },
            BeautyEmotion.PURCHASE_HESITATION: {
                "keywords": ["纠结", "不知道", "怕踩雷", "选哪个", "犹豫",
                             "拿不定", "怕不合适", "考虑一下"],
                "valence": 0.0,
                "arousal": 0.4,
                "risk_weight": 0.5
            },
            BeautyEmotion.SATISFACTION: {
                "keywords": ["好用", "满意", "推荐", "喜欢", "效果好", "赞", "棒"],
                "valence": 0.7,
                "arousal": 0.5,
                "risk_weight": 0.1
            }
        }
    
    def detect_beauty_emotion(self, text: str) -> Optional[Dict]:
        """
        检测美妆场景特殊情绪
        
        Returns:
            {
                "special_emotion": BeautyEmotion枚举,
                "valence": -1到1,
                "arousal": 0到1,
                "risk_weight": 风险权重,
                "matched_keywords": 匹配到的关键词
            } 或 None
        """
        text_lower = text.lower()
        
        fear = self._rule_based_emotion(text)["emotion"] == "fearful"
        price_complaint = (
            any(self._active(text_lower, cue) for cue in (
                "价差", "降价", "打折", "保价", "价保", "价格", "贵很多", "贵这么多", "便宜了"))
            and (any(self._active(text_lower, cue) for cue in (
                "不合理", "不公平", "不满意", "太贵", "真不值", "被坑", "贵很多", "贵这么多"))
                 or bool(re.search(r"(?:刚|才)[^。；]{0,18}(?:降价|打折|便宜)", text_lower)))
        )
        for emotion, config in self.beauty_emotion_patterns.items():
            matched_keywords = [kw for kw in config["keywords"] if is_active_keyword(text_lower, kw)]
            if emotion == BeautyEmotion.ALLERGY_ANXIETY:
                matched_keywords = [kw for kw in config["keywords"] if self._active(text_lower, kw)]
                if fear:
                    matched_keywords.extend(cue for cue in ("敏感", "刺激") if self._active(text_lower, cue))
                reported_reaction = any(alert["code"] == "allergy" for alert in detect_risks(text_lower))
                if not fear and not reported_reaction:
                    matched_keywords = []
            elif emotion == BeautyEmotion.EFFECT_DISAPPOINTMENT:
                if not any(self._active(text_lower, cue) for cue in (
                    "效果", "没效果", "没有效果", "无效", "改善", "白买了", "白花钱", "浪费钱")):
                    matched_keywords = []
                elif self._active(text_lower, "白花钱"):
                    matched_keywords.append("白花钱")
            elif emotion == BeautyEmotion.PRICE_DISSATISFACTION and price_complaint:
                matched_keywords.extend(cue for cue in ("降价", "打折", "不合理", "不公平", "不满意", "贵很多") if self._active(text_lower, cue))
            elif emotion == BeautyEmotion.SATISFACTION:
                positive = self._positive_cues(text_lower)
                matched_keywords = positive if positive and not self._unresolved_service(text_lower) else []
            if matched_keywords:
                return {
                    "special_emotion": emotion,
                    "emotion_name": emotion.value,
                    "valence": config["valence"],
                    "arousal": config["arousal"],
                    "risk_weight": config["risk_weight"],
                    "matched_keywords": list(dict.fromkeys(matched_keywords)),
                    "description": self._get_emotion_description(emotion)
                }
        
        return None

    @staticmethod
    def _active(text: str, cue: str) -> bool:
        for match in re.finditer(re.escape(cue), text):
            prefix = re.split(r"[，,。！？?!；;]|但是|不过|但|却", text[:match.start()])[-1][-12:]
            negated = re.search(r"(?:没有|没|不(?:是|想|要|需要|认为|觉得|会)?|并非|无需)(?:感到|觉得|认为|有|在){0,2}$", prefix)
            other_person = re.search(
                r"(?:他|她|朋友|客服|医生|别人)(?:自己)?(?:很|非常|有点|感到|觉得|表示){0,2}$"
                r"|(?:他|她|朋友|别人|人家)(?:在)?(?:说|表示|认为|觉得|提到)[^，。；！？\n]{0,5}$",
                prefix,
            )
            clause = re.split(r"[，,。！？?!；;]", text[:match.start()])[-1] + text[match.start():]
            clause = re.split(r"[，,。；;]", clause, maxsplit=1)[0]
            allegation_question = cue in {"骗人", "敷衍", "被坑"} and bool(
                re.search(r"是不是(?:在)?$|是否(?:在)?$", prefix)
                or (re.search(r"不是在$", prefix) and re.search(r"难道|吗|[？?]", clause))
            )
            if cue == "投诉":
                start = max((text.rfind(mark, 0, match.start()) for mark in "，,。！？?!；;"), default=-1) + 1
                ends = [position for mark in "，,。！？?!；;"
                        if (position := text.find(mark, match.end())) >= 0]
                clause = text[start:min(ends) if ends else len(text)]
                information_only = re.search(r"入口|流程|渠道|如何投诉|怎么投诉|咨询投诉", clause)
                direct_complaint = re.search(r"我要|我就|准备|去投诉|要投诉|投诉你们|投诉客服", clause)
                if information_only and not direct_complaint:
                    continue
            if not other_person and (allegation_question or (
                not negated and is_active_keyword(text[max(0, match.start() - 12):match.end()], cue)
            )):
                return True
        return False

    @classmethod
    def _positive_cues(cls, text: str) -> list[str]:
        cues = []
        for cue in ("开心", "高兴", "满意", "喜欢", "好用", "好多了", "棒", "赞", "解决了", "处理好了"):
            if not cls._active(text, cue):
                continue
            clauses = [clause for clause in re.split(r"[，,。！？?!；;]", text) if cue in clause]
            if any(not re.search(r"吗|是否|有没有|推荐一下|推荐一款|请问|多久", clause) for clause in clauses):
                cues.append(cue)
        return cues

    @staticmethod
    def _unresolved_service(text: str) -> bool:
        return bool(re.search(r"未到账|没收到|收不到|还没|仍然|一直没|依然|无法", text)) and not re.search(
            r"问题(?:已经)?(?:解决|查清)|已经处理好", text)
    
    def detect_basic_emotion(self, text: str) -> Dict:
        """
        检测基础情绪（使用BERT模型或规则）
        
        Returns:
            {
                "emotion": 情绪类别,
                "valence": -1到1,
                "arousal": 0到1,
                "confidence": 置信度
            }
        """
        if self.bert_model:
            # 使用MacBERT模型（SmartCS原有）
            return self._bert_emotion_detection(text)
        else:
            # 降级到规则匹配
            return self._rule_based_emotion(text)
    
    def _bert_emotion_detection(self, text: str) -> Dict:
        """使用BERT模型进行情感分析"""
        # TODO: 集成SmartCS的MacBERT模型
        # 这里提供接口，实际实现需要加载模型
        
        # 模拟BERT输出
        emotion_labels = ["angry", "sad", "neutral", "happy", "fearful"]
        
        # 实际调用：
        # result = self.bert_model.predict(text)
        # emotion = result['label']
        # confidence = result['confidence']
        
        # 临时使用规则匹配
        return self._rule_based_emotion(text)
    
    def _rule_based_emotion(self, text: str) -> Dict:
        """基于规则的情绪识别"""
        text_lower = text.lower()
        
        # 负面情绪关键词
        negative_keywords = {
            "angry": ["生气", "气死", "投诉", "骗人", "太差", "垃圾", "气愤",
                      "离谱", "敷衍", "不公平", "不合理", "不满意", "糟糕", "差劲", "气人", "被坑", "太坑"],
            "sad": ["难过", "失望", "伤心", "无奈", "白花钱"],
            "fearful": ["担心", "害怕", "焦虑", "不安", "着急", "焦急", "急死", "很急", "怕"]
        }
        
        # 检测负面情绪
        for emotion, keywords in negative_keywords.items():
            matched = [kw for kw in keywords if self._active(text_lower, kw)]
            if matched:
                return {
                    "emotion": emotion,
                    "valence": -0.7,
                    "arousal": 0.7,
                    "confidence": 0.90,
                    "matched_keywords": matched,
                }
        repeated_work = re.search(r"别再问|别让我重复|不要让我重复|别让我再说|说了(?:三|四|五|[3-9])遍", text_lower)
        sarcasm = re.search(r"你们可真(?:行|厉害|会)", text_lower) and re.search(
            r"又让我等|又拖|还让我等|又等了|再次让我等", text_lower)
        if repeated_work or sarcasm:
            return {
                "emotion": "angry", "valence": -0.6, "arousal": 0.6,
                "confidence": 0.80,
                "matched_keywords": [repeated_work[0] if repeated_work else "反讽与等待描述"],
            }
        if re.search(r"(?:是不是|会不会|会是)[^。；]{0,10}(?:假的|假货)", text_lower):
            return {"emotion": "fearful", "valence": -0.6, "arousal": 0.6,
                    "confidence": 0.80, "matched_keywords": ["真伪疑问"]}
        
        # 检测正面情绪
        positive_keywords = self._positive_cues(text_lower)
        if positive_keywords and not self._unresolved_service(text_lower):
            return {
                "emotion": "happy",
                "valence": 0.7,
                "arousal": 0.5,
                "confidence": 0.85,
                "matched_keywords": positive_keywords,
            }
        
        # 中性
        return {
            "emotion": "neutral",
            "valence": 0.0,
            "arousal": 0.3,
            "confidence": 0.5,
            "matched_keywords": [],
        }
    
    def calculate_emotion_change(self, current_emotion: Dict, history_emotions: list) -> Dict:
        """
        计算情绪变化趋势
        
        Args:
            current_emotion: 当前情绪
            history_emotions: 历史情绪列表
            
        Returns:
            {
                "trend": "升级" | "平稳" | "好转",
                "delta_valence": 情绪变化值,
                "is_escalating": 是否正在升级
            }
        """
        if not history_emotions:
            return {
                "trend": "平稳",
                "delta_valence": 0.0,
                "is_escalating": False
            }
        
        # 计算平均历史情绪
        avg_history_valence = sum(e.get("valence", 0) for e in history_emotions[-3:]) / min(len(history_emotions), 3)
        
        current_valence = current_emotion.get("valence", 0)
        delta = current_valence - avg_history_valence
        
        # 判断趋势
        if delta < -0.3:
            trend = "升级"
            is_escalating = True
        elif delta > 0.3:
            trend = "好转"
            is_escalating = False
        else:
            trend = "平稳"
            is_escalating = False
        
        return {
            "trend": trend,
            "delta_valence": delta,
            "is_escalating": is_escalating,
            "alert": is_escalating and current_valence < -0.5  # 负面且在升级
        }
    
    def analyze(self, text: str, history_emotions: list = None) -> Dict:
        """
        综合情绪分析
        
        Args:
            text: 用户输入
            history_emotions: 历史情绪列表
            
        Returns:
            完整的情绪分析结果
        """
        # 1. 检测美妆特殊情绪
        special_emotion = self.detect_beauty_emotion(text)
        
        # 2. 检测基础情绪
        basic_emotion = self.detect_basic_emotion(text)
        
        # 3. 合并情绪（特殊情绪优先）
        if special_emotion:
            final_valence = min(special_emotion["valence"], basic_emotion["valence"])
            final_arousal = special_emotion["arousal"]
            risk_weight = special_emotion["risk_weight"]
        else:
            final_valence = basic_emotion["valence"]
            final_arousal = basic_emotion["arousal"]
            risk_weight = 1.0
        
        # 4. 计算情绪变化趋势
        emotion_change = None
        if history_emotions:
            emotion_change = self.calculate_emotion_change(
                {"valence": final_valence},
                history_emotions
            )
        
        # 5. 计算情绪风险分数
        emotion_risk_score = self._calculate_emotion_risk(
            final_valence, 
            final_arousal, 
            emotion_change
        )
        
        return {
            "basic_emotion": basic_emotion["emotion"],
            "special_emotion": special_emotion["emotion_name"] if special_emotion else None,
            "valence": final_valence,
            "arousal": final_arousal,
            "risk_weight": risk_weight,
            "emotion_change": emotion_change,
            "emotion_risk_score": emotion_risk_score,
            "description": self._format_description(special_emotion, basic_emotion),
            "matched_keywords": special_emotion["matched_keywords"] if special_emotion else [],
            "basic_matched_keywords": basic_emotion.get("matched_keywords", []),
            "confidence": basic_emotion["confidence"],
            "confidence_scope": "heuristic cue strength, not calibrated probability",
            "label_contract": "basic emotion and scenario emotion are separate",
        }
    
    def _calculate_emotion_risk(self, valence: float, arousal: float, change: Optional[Dict]) -> int:
        """
        计算情绪风险分数（0-40分）
        
        情绪风险是总风险评分的一部分
        """
        risk_score = 0
        
        # 基于valence（情感倾向）
        if valence < -0.7:
            risk_score += 30
        elif valence < -0.5:
            risk_score += 20
        elif valence < -0.3:
            risk_score += 10
        
        # 基于arousal（激动程度）
        if arousal > 0.8:
            risk_score += 10
        
        # 基于情绪变化趋势
        if change and change.get("is_escalating"):
            risk_score += 15
            if change.get("alert"):
                risk_score += 10
        
        return min(risk_score, 40)  # 最高40分
    
    def _get_emotion_description(self, emotion: BeautyEmotion) -> str:
        """获取情绪的中文描述"""
        descriptions = {
            BeautyEmotion.ALLERGY_ANXIETY: "不适相关担忧",
            BeautyEmotion.EFFECT_DISAPPOINTMENT: "效果失望",
            BeautyEmotion.PRICE_DISSATISFACTION: "价格不满",
            BeautyEmotion.PURCHASE_HESITATION: "购买犹豫",
            BeautyEmotion.SATISFACTION: "满意",
            BeautyEmotion.NEUTRAL: "中性"
        }
        return descriptions.get(emotion, "未知")
    
    def _format_description(self, special: Optional[Dict], basic: Dict) -> str:
        """格式化情绪描述"""
        if special:
            return f"{special['description']} (基础情绪: {basic['emotion']})"
        else:
            emotion_map = {
                "angry": "愤怒",
                "sad": "悲伤",
                "neutral": "中性",
                "happy": "愉快",
                "fearful": "担忧"
            }
            return emotion_map.get(basic['emotion'], basic['emotion'])


# 测试代码
if __name__ == "__main__":
    agent = EmotionAgent()
    
    test_cases = [
        "这个精华含烟酰胺吗？",  # 中性
        "用了三天脸上过敏了，红肿得厉害！",  # 过敏焦虑
        "用了一个月完全没效果，白花钱了",  # 效果失望
        "为什么你们比其他平台贵这么多？",  # 价格不满
        "纠结要不要买，怕不适合我的皮肤",  # 购买犹豫
        "非常好用，已经推荐给朋友了！"  # 满意
    ]
    
    print("=" * 60)
    print("情绪识别测试")
    print("=" * 60)
    
    for text in test_cases:
        result = agent.analyze(text)
        print(f"\n输入: {text}")
        print(f"情绪: {result['description']}")
        print(f"Valence: {result['valence']:.2f} | Arousal: {result['arousal']:.2f}")
        print(f"风险分数: {result['emotion_risk_score']}/40")
        if result['matched_keywords']:
            print(f"关键词: {', '.join(result['matched_keywords'])}")
