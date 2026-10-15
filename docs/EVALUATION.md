# 评估与复现

更新：2026-10-15。当前版本 `compact-v9-item-issues-2`。以下软件检查、原环境模型测量与人工记录分开报告。

## 软件测试

`tests/`使用模型替身和隔离SQLite，检查时点、身份、结构、声明、情绪规则、风险、缓存、队列和人工操作，不需要云端模型。

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements_dev.txt
uv pip install --python .venv\Scripts\python.exe -r requirements_research.txt
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q -p no:cacheprovider tests
```

当前全套348项通过，包含可选CPU实库检查。不装研究依赖时3项会明确跳过。测试数量不是模型正确率；上传副本与主项目的执行记录分别保存，不凭源码同步就假定验收通过。

## 当前原环境模型测量

聚合摘要：[mainline_accuracy_update_20261015.json](../evaluation/reference/mainline_accuracy_update_20261015.json)。

| 检查 | 当前结果 | 范围 |
| --- | --- | --- |
| 固定12例回复 | 11次模型、1次证据路径，零不可用降级 | 各取首遍，原稿10条16处修正保留 |
| 最终声明/服务检查 | 均0例剩余检出 | 不等于独立人工正确率 |
| 输入 / 输出 / 总Token | 6783 / 1573 / 8356 | 原开发环境顺序运行 |
| 系统中位 / 最大耗时 | 2834.98 / 3685.6毫秒 | 不作为生产并发SLA |
| 原30条最终意图 | 27/30，Macro-F1约0.6176 | 已见样本事后回归 |
| 最终基础情绪 | 同映射21/30，Macro-F1约0.6511 | 本轮未提高 |
| 最终风险 | 27/30 | 三条不适安全下限高于旧中级标签 |

原规则意图26/30、Macro-F1约0.6038，混合情绪11/30，与最终工作流分别报告。原人工高/紧急正例为0，召回不可计算。最终基础情绪读取 `emotion_basic_display`，原场景标签采用明确映射：`allergy_anxiety→fearful`、`price_dissatisfaction→angry`、`effect_disappointment→sad`、`satisfaction→happy`。不能拿混合标签匹配率直接与基础情绪比较。

样本已参与开发，原标签未改。新20条商品表达和8条缺商品表达是工程定义预期，不是新人工金标准。详见 [当前判断优化](MAINLINE_ACCURACY_20261014.md)。

## 历史结果

| 记录 | 当时结果 | 位置 |
| --- | --- | --- |
| V6/V7协议交替 | 两版各22次，Token16368→15364，减少6.13% | `evaluation/reference/local_measurement_summary.json` |
| V7完整12例 | Token8980→7682，减少14.45%，包含1条证据路径 | `docs/ACCURACY_COST_UPGRADE.md`；不能与纯模型路径混算 |
| V8-3 | 12例8342 Token、中位2.94秒；当时269项软件测试 | `evaluation/reference/communication_update_20261013_v3.json` |
| 固定提示CPU/5060 | 各6次，中位17.18→3.82秒 | 同上所含设备对照 |
| V8-4 | 303项测试、12例8357 Token | `evaluation/reference/open_source_update_20261014.json` |
| V8-5 | 320项测试、12例8357 Token | `evaluation/reference/service_memory_update_20261014.json` |
| 离线预审分流 | Token15326→11788，减少23.08% | `evaluation/reference/automated_precheck_20261013.json` |

V9与V8-5仅差1 Token，不当显著降本。V8-3的28条工程情绪协议中，规则基础/场景均28/28，实际模型基础情绪25/28（开发10/12、验证15/16），不是人工准确率。旧32条工程表达基础31/32、场景30/32，礼貌致谢改中性后各少1条，旧预期保留。

历史研究、失败和中间结果不改写。离线预审节约不计入接待成本；设备和提示同时改变的完整复测不作单因素归因。

## 人工记录与上传副本

原项目的30条人工标注、42条历史和效率记录仅在本机保存。用户确认30条均由人工判断，误点候选按钮不作为采用证据。本上传副本不提供原个人数据库，20条开发/30条待标注模板是空的，不能充当原金标准。

本人12条回复复核已完成：8条原V9可见草稿可用、4条改后认可、0待确认，见 [复核汇总](REPLY_REVIEW_SUMMARY_20261015.md)。本人已看自动检查意见，不是独立盲测；4条认可稿不是原模型输出或已部署生成补丁。旧测量快照不改写。H的效率声明保留，但缺完整20条任务级计时，不能报告真人提效比例。自动预审只能筛查和排序，不填写人工通过。

清理副本改变了昵称和无关字段，不与原输入逐字相同；需要在新机器另存第一遍输出、代码版本、失败及用量，不能直接宣称复现原环境结果。

## 可用工具

| 用途 | 入口 |
| --- | --- |
| 保留首遍回复与修正 | `evaluation/capture_precheck_cases.py` |
| 固定请求与协议对照 | `evaluation/benchmark_assistance.py`、`benchmark_paired_protocols.py` |
| 实际人工标签事后比较 | `evaluation/evaluate_frozen_assistance.py` |
| 规则/工程表达检查 | `evaluation/evaluate_emotion_protocol.py`、`evaluate_service_issue_protocol.py` |
| CPU分类与检索实验 | `evaluation/evaluate_lightweight_classifier.py`、`evaluate_knowledge_reranking.py` |
| 只读预审与开源工具导出 | `evaluation/review_saved_replies.py` |

有些入口需要自己的已保存回复或实际标注数据库。先准备依赖与输入，不因脚本存在就当作实验完成；不要用空白模板补造原人工标签。
