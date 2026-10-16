# 评估方法与结果

版本：`compact-v13-service-continuity-1`。测量日期：2026-10-15。

## 软件回归

`tests/`覆盖数据时点、身份确认、诉求与多轮状态、资料复用、知识范围、回复校验、风险任务、缓存及人工操作。测试使用隔离数据库和模型替身，无需实际模型生成。

结果：**441项通过，3项跳过**。跳过项为未安装可选研究依赖的检查。记录见 [软件测试摘要](../evaluation/reference/software_tests.json)。

安装运行依赖后执行：

```bash
python -B -m pytest -q -p no:cacheprovider tests
```

Windows使用 `.venv\Scripts\python.exe`，macOS / Linux使用 `.venv/bin/python`。开发工具在 `requirements_dev.txt`，可选CPU研究依赖在 `requirements_research.txt`。

## 固定工程协议

[evaluation/five_stage_protocol.json](../evaluation/five_stage_protocol.json)包含20条条件、暂缓、反悔、多订单与风险表达。分别比较意图和处理焦点，记录逐条结果。

| 模式 | 意图匹配 | 处理焦点匹配 |
| --- | --- | --- |
| 规则模式 | 20/20 | 20/20 |
| 完整模型工作流 | 20/20 | 20/20 |

协议预期由工程定义，样本参与了开发，结果用于功能回归。完整模型工作流包含超时后的规则降级，不能把上述匹配数量等同于模型生成成功数。

## 本地模型运行

环境：Ollama、Qwen3:8b，单次25秒超时、最多1次尝试。完整20条顺序运行，结果见 [逐条模型记录](../evaluation/reference/five_stage_model.json) 与 [规则记录](../evaluation/reference/five_stage_rules.json)。

| 指标 | 结果 |
| --- | --- |
| 成功生成 | 19/20 |
| 超时降级 | 1/20，案例gift-1 |
| 全请求中位耗时 | 10.132秒 |
| 成功生成中位耗时 | 10.011秒 |
| 最大耗时 | 25.012秒 |
| 已报告Token | 19,378；超时请求用量未知 |
| 最终草稿自动检查 | 19条完成，0条被标记 |

超时案例“不查赠品，只问发货了没”单独复测成功，耗时15.919秒、1,140 Token，意图与焦点各1/1。记录见 [单条复测](../evaluation/reference/timeout_case_retry.json)。原完整回归仍保留1条超时，单条复测单独报告。

自动检查覆盖既定结构、声明与服务规则，无法替代人工语义评价。上述时延为本机固定案例结果，未测生产并发或实际客服任务用时。

## 复现与断点续跑

在已激活的Python环境中执行：

```bash
python evaluation/evaluate_five_stage.py --output evaluation/results/rules.json
python evaluation/evaluate_five_stage.py --model --output evaluation/results/model.json
python evaluation/evaluate_five_stage.py --model --output evaluation/results/model.json --resume
```

模型测量时在本机 `.env` 配置 `QWEN_TIMEOUT_SECONDS=25`、`QWEN_MAX_ATTEMPTS=1`。每条结果完成后原子保存检查点，续跑校验协议、源码、版本、模型及配置摘要，已完成案例不重复请求。

源码摘要覆盖 `src/` Python文件及场景知识JSON，不含前端和说明文档。评测修改输出文件另存，保留失败及中间结果。结果目录在运行时创建，默认不打包。

## 成本设计与对照

作品采用紧凑输出、精确缓存和有限证据路径，记录实际返回的Token用量。没有计价提供方时不推算费用；超时用量未知时分别报告。

历史固定协议对照记录见 [成本基线](../evaluation/reference/cost_protocol_baseline.json)：2026-10-09，11个共同案例，两版各22次交替生成，合计Token由16,368降至15,364，减少6.13%。该记录来自较早版本与原始输入，用于说明协议优化方法，不能与当前20条结果直接比较。

## 人工评估入口

评估中心支持记录意图、情绪、风险标签及任务效率。随附20条开发样本和30条待标注样本模板，初始标签为空。新增标注和计时保存到本机数据库。

工程预期、模型预测和人工标注分别保留来源。当前结果支持作品机制与回归表现，不报告独立人工准确率、真实提效或满意度比例。
