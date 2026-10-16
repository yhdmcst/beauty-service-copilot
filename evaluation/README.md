# 评测工具与证据

| 内容 | 位置 |
| --- | --- |
| 当前固定工程协议 | `five_stage_protocol.json` |
| 当前逐条规则与模型结果 | `reference/five_stage_rules.json`、`reference/five_stage_model.json` |
| 超时案例单独复测 | `reference/timeout_case_retry.json` |
| 软件回归摘要 | `reference/software_tests.json` |
| 历史成本对照 | `reference/cost_protocol_baseline.json` |
| 待人工标注的场景模板 | `holdout_v2/` |
| 专项协议 | 意图、情绪、商品问题、检索与服务焦点JSON |

完整运行与指标定义见 [评估说明](../docs/EVALUATION.md)。`evaluation_center.py`为应用的本地标注与效率记录模块，其余脚本用于固定协议、草稿检查、成本测量和数据导出。新测量写入 `results/`，该目录在运行时创建，默认不随提交文件分发。
