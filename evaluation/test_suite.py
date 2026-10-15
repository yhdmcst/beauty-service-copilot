"""Evaluate repeatable offline metrics; distinguish synthetic from real-world results."""

from __future__ import annotations

import json
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.emotion_agent import EmotionAgent
from src.agents.intent_agent import IntentAgent
from src.api.app_upgraded import create_app
from src.risk.beauty_risk_rules import detect_risks


def read_cases(name: str) -> list[dict]:
    """Read versioned evaluation fixtures."""
    return json.loads((ROOT / "evaluation" / "test_data" / f"{name}.json").read_text(encoding="utf-8"))


def evaluate() -> dict:
    """Run classification, high-risk detection and rule-only latency tests."""
    intent = IntentAgent()
    emotion = EmotionAgent()
    intent_cases = read_cases("intent_test")
    emotion_cases = read_cases("emotion_test")
    risk_cases = read_cases("risk_test")
    negative_cases = read_cases("risk_negative_test")
    intent_accuracy = sum(intent.classify(item["query"])["intent_name"] == item["ground_truth"]
                          for item in intent_cases) / len(intent_cases)
    emotion_accuracy = sum(emotion.analyze(item["query"])["special_emotion"] == item["ground_truth"]
                            for item in emotion_cases) / len(emotion_cases)
    risk_recall = sum(bool(detect_risks(item["query"], item["history"])) for item in risk_cases) / len(risk_cases)
    false_positives = sum(bool(detect_risks(item["query"], item["history"]))
                          for item in negative_cases)
    app = create_app()
    client = app.test_client()
    samples = ["敏感肌能用吗", "用了精华脸上红肿刺痛", "怎么申请退款",
               "订单什么时候发货", "这个面霜怎么用", "和SK-II哪个好",
               "我想开发票", "谢谢", "要投诉你们", "有什么优惠券"]
    latencies = []
    actions = {}
    for query in samples:
        response = client.post("/chat", json={"message": query})
        if response.status_code != 200:
            raise RuntimeError(f"Chat failed: {query}: {response.status_code}")
        data = response.get_json()
        latencies.append(data["latency_ms"])
        actions[data["action"]] = actions.get(data["action"], 0) + 1
    tracker = app.extensions["workflow"].response_agent.tracker.get_stats()
    cache = app.extensions["workflow"].response_agent.cache.stats()
    return {
        "provenance": "synthetic_templates; repeated phrases; not independent validation",
        "intent": {"n": len(intent_cases), "accuracy": round(intent_accuracy, 4)},
        "emotion": {"n": len(emotion_cases), "accuracy": round(emotion_accuracy, 4)},
        "risk": {"positive_n": len(risk_cases), "positive_recall": round(risk_recall, 4),
                 "negative_n": len(negative_cases),
                 "false_positive_rate": round(false_positives / len(negative_cases), 4),
                 "precision": round(
                     risk_recall * len(risk_cases) /
                     (risk_recall * len(risk_cases) + false_positives), 4)},
        "latency": {"n": len(samples), "median_ms": round(statistics.median(latencies), 2),
                    "max_ms": max(latencies), "under_2s": all(x < 2000 for x in latencies),
                    "mode": "offline rule-only / no remote LLM or Qdrant"},
        "actions": actions, "cost": tracker, "cache": cache,
        "unmeasured": ["Qwen response quality", "Qdrant Top-5 recall", "answerability accuracy",
                       "real traffic cache hit rate", "actual API cost", "network WebSocket latency"],
    }


def main() -> None:
    """Save auditable machine metrics and a human-readable assessment."""
    result = evaluate()
    output = ROOT / "evaluation" / "results"
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    report = f"""# 离线评估报告

执行日期：{date.today().isoformat()}；模式：本地词法向量 + 模拟知识 + 规则回复。

| 指标 | 结果 | 数据范围 |
| --- | ---: | --- |
| 意图识别准确率 | {result['intent']['accuracy']:.1%} | {result['intent']['n']} 条合成模板样本（存在重复） |
| 特殊情绪准确率 | {result['emotion']['accuracy']:.1%} | {result['emotion']['n']} 条合成模板样本 |
| 风险正例召回率 | {result['risk']['positive_recall']:.1%} | {result['risk']['positive_n']} 条合成高风险正例 |
| 风险负例误报率 | {result['risk']['false_positive_rate']:.1%} | {result['risk']['negative_n']} 条合成低风险负例 |
| 离线端到端中位耗时 | {result['latency']['median_ms']:.2f} ms | {result['latency']['n']} 条，不调用远程模型 |
| 离线端到端最大耗时 | {result['latency']['max_ms']:.2f} ms | 不代表线上 P95 |

负例来自少量合成模板，不能推断线上误报率。合成测试集由关键词模板循环产生，以上指标仅是功能回归检查，**不能**证明真实数据上的目标阈值。回复质量 4/5、Top-5 召回率 90%、可回答性 85%、线上推送 <500ms 均未验证。对比实验（规则与 Qwen 7B/72B）尚需有效密钥、核实知识和独立标注集。

## 成本与缓存

此轮自动回复次数：{result['actions'].get('auto_reply', 0)}；人工复核/升级次数：{sum(v for k, v in result['actions'].items() if k != 'auto_reply')}。
实测 Token：{result['cost']['total_tokens']}；缓存命中率：{result['cache']['hit_rate']:.1%}。
Qwen 单价尚未配置，`0` 元**不代表真实单会话成本**；缓存节省 40% 的目标同样未验证。规则优先和未核实知识转人工会降低误答风险，但当前无法给出模型对比质量或真实账单结论。

## 数据来源与后续验收

知识库实际为 56 条模拟/草案记录 + 4 条话术，非 5000 条真实已核实数据。须导入商家审核过的产品资料与政策，并准备独立人工标注的问答、意图、情绪、风险正负样本；再启用 BGE/Qdrant、配置 Qwen 密钥和实际计价，测量线上 P50/P95、混合检索召回、人工评分与端到端推送耗时。
"""
    (output / "evaluation_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
