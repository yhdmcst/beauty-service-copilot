# 开源评测与后续优化

核查日期：2026-10-13。按官方仓库README、许可证、具体实现和文档选择。没有导入受限训练语料，未新增大型运行依赖。

## 已核查项目

| 项目 | 实际读取的文件 | 许可与结论 |
| --- | --- | --- |
| [Promptfoo](https://github.com/promptfoo/promptfoo) | `LICENSE`、`src/providers/echo.ts`、`src/providers/ollama.ts`、`site/docs/providers/ollama.md`、`site/docs/configuration/expected-outputs/model-graded/llm-rubric.md`、`package.json` | MIT。echo复用既有结果，Ollama作显式本地评审，llm-rubric按具体标准评分。当前版本0.124.1需要Node>=22.22.0，本机Node20尚不满足，未安装CLI |
| [Ragas](https://github.com/vibrantlabsai/ragas) | `LICENSE`、README、`src/ragas/metrics/_faithfulness.py` | Apache-2.0。代码先把回答拆为事实，再判断是否被上下文支持；适合补忠实性评估。它不是真人验证，不等于全面业务正确；完整指标有多次模型调用，当前不把重依赖装进接待主流程 |
| [Label Studio](https://github.com/HumanSignal/label-studio) | `LICENSE`、README、`docs/source/guide/predictions.md` | Apache-2.0。模型结果用predictions导入，人工annotations独立；能预标和加快检查，不能让模型成为第二名真人。若展示预判并复制成标注，就不称盲标 |

Ragas历史仓库README指向当前`vibrantlabsai/ragas`，后续源码以该仓库为准。仓库许可不能自动覆盖其所有模型或外部训练数据。

本轮借鉴评分维度、明确评审提供方、事实/证据对照和预测/人工结果分离，新增本项目的保存回复预审及导出器。没有复制第三方源码，生成的Promptfoo配置可用本地Ollama；实际CLI验收仍待符合Node版本的环境。

已完成两轮离线对照：自适应分流保留规则门禁，高/紧急案例用完整评审，其余用紧凑评审。12条同一回复交替检查时，完整格式约15326 Token，自适应约11788 Token，减少约23.08%，标记一致。它只降低离线预审成本，不改变客服接待生成。

本地自动预审先做6条工程校准：首轮把三条合理候选均误报，原输出保留。第二轮限制“只审候选，缺业务事实不是回复错误”，并校验issue引用属于候选后，模型区分了3条明显错误和3条无明显错误。这是已见工程回归，不是独立准确率；其中1条合理候选仍被现有有限规则检出下一步表达漏项，模型与规则分歧保留。

## 最值得继续优化

| 优先级 | 优化 | 原因和验收方式 |
| --- | --- | --- |
| 1 | 用不同模型离线评审，再筛出分歧给本人 | 当前同模型自评容易共享偏差；3090库存已核实，但远程旧版Ollama生成请求超时。不能把多个模型一致直接叫人类金标准 |
| 1 | 校准意图的业务口径与风险等级 | 当前最终意图21/30；实际不适安全等级与3条原标签冲突。先明确标签层级，不通过重写金标签制造分数 |
| 1 | 对新增提示开销做同设备交替实验 | V8-3完整12例8342Token比同日V7多8.20%；压缩重复要求须同时测情绪、回复、时点和风险，别只降Token |
| 2 | 情绪与回复都附原话依据，记录混合表达 | 生气/担忧可能同时存在；重要的是客服回应具体担忧，而不是逼单标签完全一致。先保留对象、分句和不确定信息 |
| 2 | 选经许可核实的中文多类分类器旁路试验 | 正负面二分类不能替代担忧、失望或反讽。当前轻量候选的权重配置仍未核实，不直接装入 |
| 2 | 补经过审核的商品/售后资料 | 肤质自述复用已完成，个性化推荐仍缺真实商品来源；先核资料、商品身份、适用范围，再评估检索和回答 |
| 3 | 3090并行批量评测、较大Qwen模型比较 | 比较实际质量/耗时/显存，不从参数量推定准确性。不影响客服线上主流程 |

短接待提示隔离试验输入Token略降、输出Token上升，交替中位耗时也变慢，因此不替换当前主提示。远程服务可读取模型列表，但Ollama 0.1.29的生成请求超时，诊断发现原服务占用11434，独立端口未启动，未作远程性能结论，也未重启原服务。

## 人工验证能否被替代

预检查、技术回归、部分质量代理指标可以自动完成。独立金标准、真人共情体验和人工任务耗时不能被上述工具替代。赛题未要求一定多人标注，可以只提交真实完成的工程评测，不把未完成的人效数字当作收尾硬门槛。

本轮输出保留12条待本人确认；可以用风险与分歧排序减少阅读负担，不能把未读条目记成已通过。具体操作见 [自动预检查指南](AUTOMATED_VALIDATION_GUIDE.md)。

## 可追踪文件版本

| 官方文件 | Git blob SHA |
| --- | --- |
| Promptfoo LICENSE | `af3fa111d9303b3041d225fb851534e50a4bbec2` |
| Promptfoo echo provider | `d33d4915015efa2e784d08c74964dd3adfd58e8a` |
| Promptfoo Ollama provider | `8c88cb11518226222fc5d0aeb4801b1ef01987d5` |
| Promptfoo llm-rubric docs | `5984282691366d201486eebfa520f09fd68db9ff` |
| Promptfoo Ollama docs | `33b23f76a892305069862e13958c0bdc2e81cb4a` |
| Ragas LICENSE | `8bcca742ae3458aa4e74d0133d51a248df16f23b` |
| Ragas faithfulness | `32d474c815869f050a315966adc145dfa23adef2` |
| Label Studio LICENSE | `3f1aa21f494250562d5e94d96446b3e5cb6e3acb` |
| Label Studio predictions docs | `88b8a7b09c9320ef0c3fa0160b50b18c11c0984f` |
