"""
美妆场景意图识别Agent
"""

from typing import Dict, Tuple
from enum import Enum
import re
from src.risk.beauty_risk_rules import detect_risks, is_active_keyword
from src.utils.service_requests import current_request_text, primary_request_text, request_plan, MISSING_OUTCOME_CUES
from src.utils.service_issue_cues import reported_item_issues


class BeautyIntent(Enum):
    """美妆场景意图枚举"""
    
    # 商品咨询类
    INGREDIENT_QUERY = "ingredient_query"  # 成分查询
    SKIN_TYPE_MATCH = "skin_type_match"    # 肤质适配
    USAGE_METHOD = "usage_method"          # 使用方法
    AUTHENTICITY_CHECK = "authenticity_check"  # 真假鉴别
    
    # 效果咨询类
    EFFECT_INQUIRY = "effect_inquiry"      # 效果咨询
    ALLERGY_CONCERN = "allergy_concern"    # 过敏担忧
    PRODUCT_COMPARISON = "product_comparison"  # 产品对比
    
    # 订单问题类
    ORDER_QUERY = "order_query"            # 订单查询
    LOGISTICS_QUERY = "logistics_query"    # 物流查询
    
    # 售后服务类
    REFUND_REQUEST = "refund_request"      # 退款申请
    QUALITY_ISSUE = "quality_issue"        # 质量问题
    ALLERGY_REACTION = "allergy_reaction"  # 过敏反应（高风险）
    
    # 促销活动类
    COUPON_QUERY = "coupon_query"          # 优惠券查询
    ACTIVITY_INQUIRY = "activity_inquiry"  # 活动咨询
    
    # 其他
    INVOICE_REQUEST = "invoice_request"    # 发票开具
    GENERAL_CONSULTATION = "general_consultation"  # 一般咨询
    UNKNOWN = "unknown"                    # 未知意图


class IntentAgent:
    """意图识别Agent"""
    
    def __init__(self, llm_client=None):
        """
        初始化意图识别Agent
        
        Args:
            llm_client: LLM客户端（Qwen），如果为None则使用规则匹配
        """
        self.llm_client = llm_client
        self.use_llm = llm_client is not None
        
        # 规则匹配关键词
        self.intent_keywords = {
            BeautyIntent.INGREDIENT_QUERY: [
                "成分", "原料", "烟酰胺", "玻尿酸", "视黄醇", "水杨酸",
                "果酸", "维c", "含酒精"
            ],
            BeautyIntent.SKIN_TYPE_MATCH: [
                "肤质", "皮肤", "敏感肌", "油性", "干性", "混合", 
                "能用吗", "适合吗", "我是", "适不适合"
            ],
            BeautyIntent.USAGE_METHOD: [
                "怎么用", "使用方法", "用法", "步骤", "顺序", 
                "先用", "后用", "早上", "晚上", "怎么使用"
            ],
            BeautyIntent.AUTHENTICITY_CHECK: [
                "真假", "正品", "假货", "鉴别", "辨别", "是不是真的",
                "怎么看真假", "验货"
            ],
            BeautyIntent.EFFECT_INQUIRY: [
                "效果", "有效", "多久见效", "能美白", "能祛痘", 
                "能淡斑", "能抗老", "有用吗"
            ],
            BeautyIntent.ALLERGY_CONCERN: [
                "会不会过敏", "过敏吗", "敏感", "刺激", "温和", 
                "孕妇能用", "哺乳期"
            ],
            BeautyIntent.PRODUCT_COMPARISON: [
                "哪个好", "对比", "区别", "相比", "vs",
                "选哪个", "比较"
            ],
            BeautyIntent.ORDER_QUERY: [
                "订单", "我的订单", "订单号", "买的", "下单"
            ],
            BeautyIntent.LOGISTICS_QUERY: [
                "物流", "快递", "发货", "什么时候到", "几天到", 
                "发出", "配送"
            ],
            BeautyIntent.REFUND_REQUEST: [
                "退货", "退款", "退钱", "退回款", "退的款", "退的钱", "申请退"
            ],
            BeautyIntent.QUALITY_ISSUE: [
                "质量", "破了", "漏了", "坏了", "货不对版",
                "破损", "渗漏", "泵头", "封口", "空包裹", "少件", "少了一",
                "错发", "发错", "换货", "补发"
            ],
            BeautyIntent.ALLERGY_REACTION: [
                "过敏了", "红肿", "刺痛", "烂脸", "长痘", "起疹", 
                "发红", "痒", "用了过敏"
            ],
            BeautyIntent.COUPON_QUERY: [
                "优惠券", "券", "折扣", "优惠", "有没有活动"
            ],
            BeautyIntent.ACTIVITY_INQUIRY: [
                "活动", "促销", "满减", "双十一", "618", "赠品",
                "赠送", "附赠", "试用装", "尾款", "支付窗口"
            ],
            BeautyIntent.INVOICE_REQUEST: [
                "发票", "开票", "发票抬头", "需要发票", "开发票"
            ]
        }

    @staticmethod
    def _active(query: str, cue: str) -> bool:
        """Intent negation means rejecting a request, not a denied refund outcome."""
        query = current_request_text(query)
        for match in re.finditer(re.escape(cue), query):
            prefix = re.split(r"[，,。！？?!；;]|但是|不过|但|却", query[:match.start()])[-1][-16:]
            rejected = re.search(
                r"(?:不(?:是|想|要|需要|打算|认为|怀疑)|没(?:有)?|无需|不用|并非)"
                r"(?:要|再|来|咨询|问|申请|办理|发生|认为|怀疑|提|是){0,3}$", prefix)
            missing_outcome = cue in MISSING_OUTCOME_CUES and re.search(r"(?:没有|没|未)$", prefix)
            if missing_outcome or (not rejected and is_active_keyword(
                query[max(0, match.start() - 16):match.end()], cue)):
                return True
        return False

    def _explicit_intent(self, query: str) -> BeautyIntent | None:
        active = lambda *cues: any(self._active(query, cue) for cue in cues)
        price = active("价保", "保价", "补差", "价差", "降价", "便宜了", "贵很多", "贵这么多", "价格")
        conditional_return = re.search(
            r"(?:如果|若|不通过|不能|不给)[^。；]{0,24}(?:再|就|考虑)[^。；]{0,8}退货"
            r"|退货[^。；]{0,8}(?:备选|再说)", query)
        if price and conditional_return:
            return BeautyIntent.GENERAL_CONSULTATION
        if active("开票", "开发票", "开个发票", "电子发票", "发票", "开个票"):
            return BeautyIntent.INVOICE_REQUEST
        if active("退款", "退钱", "退的款", "退的钱", "退回款", "申请退", "仅退款") or re.search(
            r"钱.{0,4}(?:没回来|没到账)|(?:给我|帮我|还是)退了(?:吧)?", query
        ):
            return BeautyIntent.REFUND_REQUEST
        if active("退货") and not price:
            return BeautyIntent.REFUND_REQUEST
        if price:
            return BeautyIntent.GENERAL_CONSULTATION
        item_issues = reported_item_issues(query)
        gift_context = active("赠品", "赠送", "附赠", "试用装", "活动", "买一送一")
        if item_issues and (not gift_context or any(
            issue["category"] == "product_usability_or_damage" for issue in item_issues
        )):
            return BeautyIntent.QUALITY_ISSUE
        if active("优惠券", "折扣券", "折扣", "领取券"):
            return BeautyIntent.COUPON_QUERY
        if active("赠品", "赠送", "附赠", "试用装", "尾款", "支付窗口", "活动规则", "满减"):
            return BeautyIntent.ACTIVITY_INQUIRY
        if re.search(r"(?:下单|页面|活动)[^。；]{0,10}写?赠", query):
            return BeautyIntent.ACTIVITY_INQUIRY
        if active("质量", "破损", "渗漏", "泵头", "封口", "空包裹", "少件", "少了一", "盖子裂", "错发", "发错", "换货", "补发", "破了", "坏了"):
            return BeautyIntent.QUALITY_ISSUE
        if len(re.findall(r"#\s*[a-z]?\d+", query)) >= 2 and re.search(
            r"发来|收到|色差|不能用|不符", query):
            return BeautyIntent.QUALITY_ISSUE
        if active("真假", "假货", "假的", "防伪", "鉴别", "真伪"):
            return BeautyIntent.AUTHENTICITY_CHECK
        if active("担心过敏", "会不会过敏", "过敏吗", "怕刺激") or (
            active("敏感", "刺激", "过敏") and active("担心", "怕", "害怕")
        ):
            return BeautyIntent.ALLERGY_CONCERN
        if active("取消订单", "地址", "改址", "订单状态"):
            return BeautyIntent.ORDER_QUERY
        if active("物流", "快递", "承运", "配送", "运单", "发货", "发出", "签收", "什么时候到", "几天到", "包裹到"):
            return BeautyIntent.LOGISTICS_QUERY
        if active("对比", "区别", "相比", "选哪个", "比较", "vs"):
            return BeautyIntent.PRODUCT_COMPARISON
        if active("成分", "原料", "烟酰胺", "玻尿酸", "水杨酸", "含酒精"):
            return BeautyIntent.INGREDIENT_QUERY
        if active("怎么用", "怎么使用", "用法", "使用方法", "使用顺序", "先后", "步骤", "先用", "后用"):
            return BeautyIntent.USAGE_METHOD
        if active("效果", "见效", "改善", "白花钱", "无效", "没效果", "效果不好", "没有效果"):
            return BeautyIntent.EFFECT_INQUIRY
        if active("肤质", "油皮", "油性", "干性", "皮肤", "肌肤", "适配", "适合", "敏感肌"):
            return BeautyIntent.SKIN_TYPE_MATCH
        return None
    
    def classify_by_rules(self, query: str) -> Tuple[BeautyIntent, float]:
        """
        基于规则的意图分类（快速，无Token消耗）
        
        Args:
            query: 用户输入
            
        Returns:
            (意图, 置信度)
        """
        original = query.lower()
        query_lower = primary_request_text(original)

        # Safety-sensitive expressions take precedence over generic skin, ingredient,
        # comparison and refund terms that commonly occur in the same sentence.
        if any(item["code"] == "allergy" for item in detect_risks(original)):
            return BeautyIntent.ALLERGY_REACTION, 0.95
        explicit = self._explicit_intent(query_lower)
        if explicit is not None:
            return explicit, 0.75 if request_plan(original)["requires_review"] else 0.90
        
        # 统计每个意图匹配到的关键词数量
        intent_scores = {}
        
        for intent, keywords in self.intent_keywords.items():
            score = 0
            for keyword in keywords:
                if self._active(query_lower, keyword):
                    score += 1
            if score > 0:
                intent_scores[intent] = score
        
        # 如果没有匹配到任何关键词
        if not intent_scores:
            return BeautyIntent.GENERAL_CONSULTATION, 0.3
        
        # 找到得分最高的意图
        best_intent = max(intent_scores, key=intent_scores.get)
        max_score = intent_scores[best_intent]
        
        # 计算置信度（简单的归一化）
        confidence = min(0.45 + max_score * 0.15, 0.95)
        
        return best_intent, confidence
    
    def classify_by_llm(self, query: str) -> Tuple[BeautyIntent, float]:
        """
        基于LLM的意图分类（准确，消耗Token）
        
        Args:
            query: 用户输入
            
        Returns:
            (意图, 置信度)
        """
        if not self.llm_client:
            raise ValueError("LLM client not initialized")
        
        # Few-shot Prompt
        prompt = f"""
你是一个美妆电商客服意图分类专家。请识别用户的咨询意图。

意图分类：
1. ingredient_query - 成分查询
2. skin_type_match - 肤质适配
3. usage_method - 使用方法
4. authenticity_check - 真假鉴别
5. effect_inquiry - 效果咨询
6. allergy_concern - 过敏担忧
7. product_comparison - 产品对比
8. order_query - 订单查询
9. logistics_query - 物流查询
10. refund_request - 退款申请
11. quality_issue - 质量问题
12. allergy_reaction - 过敏反应（高风险）
13. coupon_query - 优惠券查询
14. activity_inquiry - 活动咨询
15. invoice_request - 发票开具
16. general_consultation - 一般咨询

示例：
用户："这个精华含烟酰胺吗？浓度是多少？"
意图：ingredient_query
置信度：0.95

用户："我是混合偏油的皮肤，能用这个面霜吗？"
意图：skin_type_match
置信度：0.92

用户："用了三天脸上起红疹了，怎么办？"
意图：allergy_reaction
置信度：0.98

用户："和SK-II小灯泡比，哪个美白效果更好？"
意图：product_comparison
置信度：0.90

现在请分类：
用户："{query}"

请严格按照以下JSON格式返回：
{{"intent": "意图类别", "confidence": 置信度(0-1的小数)}}
"""
        
        try:
            response = self.llm_client.generate(prompt, max_tokens=100)
            result = self._parse_llm_response(response)
            
            intent_str = result.get("intent", "unknown")
            confidence = float(result.get("confidence", 0.5))
            
            # 转换为枚举
            try:
                intent = BeautyIntent(intent_str)
            except ValueError:
                intent = BeautyIntent.UNKNOWN
            
            return intent, confidence
        
        except Exception as e:
            print(f"LLM分类失败: {e}")
            # 降级到规则匹配
            return self.classify_by_rules(query)
    
    def _parse_llm_response(self, response: str) -> Dict:
        """解析LLM返回的JSON"""
        import json
        
        # 尝试提取JSON
        json_match = re.search(r'\{.*?\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        # 解析失败，返回默认值
        return {"intent": "unknown", "confidence": 0.3}
    
    def classify(self, query: str, use_llm: bool = None) -> Dict:
        """
        意图分类主方法
        
        Args:
            query: 用户输入
            use_llm: 是否使用LLM（None则根据初始化配置）
            
        Returns:
            {
                "intent": 意图枚举值,
                "intent_name": 意图名称,
                "confidence": 置信度,
                "is_high_risk": 是否高风险
            }
        """
        # 决定使用哪种方法
        if use_llm is None:
            use_llm = self.use_llm
        
        if use_llm and self.llm_client:
            intent, confidence = self.classify_by_llm(query)
        else:
            intent, confidence = self.classify_by_rules(query)
        
        # 判断是否高风险意图
        high_risk_intents = {
            BeautyIntent.ALLERGY_REACTION,
            BeautyIntent.QUALITY_ISSUE,
            BeautyIntent.REFUND_REQUEST
        }
        
        return {
            "intent": intent,
            "intent_name": intent.value,
            "confidence": confidence,
            "is_high_risk": intent in high_risk_intents,
            "description": self._get_intent_description(intent),
            "classification_basis": "model" if use_llm and self.llm_client else
            "explicit_service_request" if confidence >= 0.90 else "keyword_heuristic",
            "confidence_scope": "heuristic score, not calibrated probability",
            "matched_keywords": [
                cue for cue in self.intent_keywords.get(intent, [])
                if self._active(query.lower(), cue)
            ],
        }
    
    def _get_intent_description(self, intent: BeautyIntent) -> str:
        """获取意图的中文描述"""
        descriptions = {
            BeautyIntent.INGREDIENT_QUERY: "成分查询",
            BeautyIntent.SKIN_TYPE_MATCH: "肤质适配咨询",
            BeautyIntent.USAGE_METHOD: "使用方法咨询",
            BeautyIntent.AUTHENTICITY_CHECK: "真假鉴别",
            BeautyIntent.EFFECT_INQUIRY: "效果咨询",
            BeautyIntent.ALLERGY_CONCERN: "过敏担忧",
            BeautyIntent.PRODUCT_COMPARISON: "产品对比",
            BeautyIntent.ORDER_QUERY: "订单查询",
            BeautyIntent.LOGISTICS_QUERY: "物流查询",
            BeautyIntent.REFUND_REQUEST: "退款申请",
            BeautyIntent.QUALITY_ISSUE: "质量问题",
            BeautyIntent.ALLERGY_REACTION: "使用后不适，待人工核实",
            BeautyIntent.COUPON_QUERY: "优惠券查询",
            BeautyIntent.ACTIVITY_INQUIRY: "活动咨询",
            BeautyIntent.INVOICE_REQUEST: "发票开具",
            BeautyIntent.GENERAL_CONSULTATION: "一般咨询",
            BeautyIntent.UNKNOWN: "未知意图"
        }
        return descriptions.get(intent, "未知")


# 测试代码
if __name__ == "__main__":
    agent = IntentAgent()  # 使用规则匹配模式
    
    test_queries = [
        "这个精华含烟酰胺吗？",
        "我是敏感肌，能用吗？",
        "用了三天过敏了，脸上起红疹",
        "和SK-II相比哪个好？",
        "订单什么时候发货？",
        "我要退货"
    ]
    
    print("=" * 60)
    print("意图识别测试")
    print("=" * 60)
    
    for query in test_queries:
        result = agent.classify(query)
        print(f"\n查询: {query}")
        print(f"意图: {result['description']}")
        print(f"置信度: {result['confidence']:.2f}")
        print(f"高风险: {'是' if result['is_high_risk'] else '否'}")
