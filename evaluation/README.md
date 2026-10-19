# 评测目录

这里保留模型调用、工程协议、标注导出和成本对照工具，运行Demo本身无需执行这些脚本。

| 内容 | 入口 |
| --- | --- |
| 首遍回复与调整记录 | `capture_precheck_cases.py` |
| 固定请求与协议对照 | `benchmark_assistance.py`、`benchmark_paired_protocols.py` |
| 已有人工标签回归 | `evaluate_frozen_assistance.py` |
| 情绪及商品问题规则 | `evaluate_emotion_protocol.py`、`evaluate_service_issue_protocol.py` |
| CPU分类与重排实验 | `evaluate_lightweight_classifier.py`、`evaluate_knowledge_reranking.py` |
| 保存回复的自动检查 | `review_saved_replies.py` |

`holdout_v2/`为待标注模板。原个人数据库、历史测量明细及完整模型输出未随包提供；有些入口需要另行准备输入。

评测输出请使用新目录，保留失败结果。自动检查与人工复核分开保存。测量范围和当前数字见 [评估说明](../docs/EVALUATION.md)。
