# 中文美妆人工客服：开源情感与共情研究

研究日期：2026-10-13（Asia/Shanghai）。交付范围仅为本报告和 `evaluation/reference/empathy_open_source_20261013.json`。本次没有引入第三方对话数据、下载模型、安装依赖或修改业务代码，也没有完成新的人工复核。

## 结论与证据边界

优先继续使用已有的规则和 `communication_brief`，把“消费者表达了什么”“业务问题是什么”“客服如何回应”分别记录。已有来源引用、重复信息复用和情绪与策略分离，具备零新增模型调用的实用基础。中文弱线索、反讽和混合情绪仍需分歧留证；目前证据不能证明某个外部模型能提高本项目的独立准确率。

轻量中文分类器可以作为候选补充信号，但不能把二分类情感直接转换为 angry / sad / fearful，也不能从消极程度推断不适风险。`IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment` 仅列为待核候选：具体模型卡、config、标签和权重授权尚未成功读取，当前不建议直接接入。

EmpatheticDialogues 和 Emotional-Support-Conversation 可提供研究方向；后者此前读取的 README 明示 academic research only。美妆客服的潜在商业使用不属于已确认许可范围，不导入、翻译、改写其对话用作训练或示例，也不复制受限数据。仅讨论抽象的澄清、回应负担、确认诉求等客服行为，不引入心理治疗、心理诊断或治疗建议。

初步核查因网络访问失败未完成外部文件读取。随后在获准联网后补读了4个具体外部文件，正文与日期见下表；Hugging Face模型配置仍因域名不可达未成功读取。以下补充核查优先于后文初步待核表，不把框架许可推广到未核实的独立权重。

## 补充外部源码与许可核查

2026-10-13通过官方GitHub Contents API读取，没有复制其代码或训练语料到应用。

| 仓库与实际文件 | Git blob SHA | 发现与本项目决定 |
| --- | --- | --- |
| `facebookresearch/EmpatheticDialogues/LICENSE` | `6b28d560c9cbbb829dec5bf3eb23f8ddae46d697` | CC BY-NC 4.0，包含非商业限制。不作为可直接用于商业客服的训练材料 |
| `IDEA-CCNL/Fengshenbang-LM/LICENSE` | `8a541f4249238c29483d26aa249e23c753e29fbe` | 框架Apache-2.0；未独立验证具体情绪权重或训练语料许可 |
| `fengshen/examples/classification/finetune_classification.py` | `2e643f2fcf560b6c817d22946ad4a6610b647e13` | `TaskDataModel.load_schema`从训练数据生成label2id，`TaskCollator`按长度编码，`LitModel`用序列分类模型及交叉熵。可借鉴显式标签映射、分开训练/验证/测试；当前不导入重训练框架 |
| `fengshen/API/text_classification.json` | `f510becb1306bd66faf2573dbd09044867c08efe` | 示例使用Similarity模型、CPU device=-1、最大长度512；这是分类接口配置，不是已验证的五类情绪权重。不能原样冒充中文情绪分类器 |

官方证据路径：[EmpatheticDialogues许可证](https://api.github.com/repos/facebookresearch/EmpatheticDialogues/contents/LICENSE)、[Fengshen许可证](https://api.github.com/repos/IDEA-CCNL/Fengshenbang-LM/contents/LICENSE)、[分类训练源码](https://api.github.com/repos/IDEA-CCNL/Fengshenbang-LM/contents/fengshen/examples/classification/finetune_classification.py)、[接口配置](https://api.github.com/repos/IDEA-CCNL/Fengshenbang-LM/contents/fengshen/API/text_classification.json)。

## 实际读取记录

以下本地文件在 2026-10-13 成功读取。路径均相对于项目根目录；未读取客户身份凭证。

| 实际路径 | 阅读范围与发现 |
| --- | --- |
| `src/agents/emotion_agent.py` | 全文。`_active` 排除部分否定和他人归属；`_positive_cues` 不把单纯“谢谢”当满意；反讽仅覆盖特定表达与等待线索；`analyze` 分开输出基础/场景情绪。BERT 接口仍回退规则，没有已集成分类器的证据 |
| `src/knowledge/communication_brief.py` | 全文。`basis` 含 message_id、session_id、time、scope、quote；复用既有信息；记录等待事项、自述肤质和待复核原因；`additional_model_calls: 0` |
| `src/models/qwen_wrapper.py` | 全文。复用现有 OpenAI 兼容接口、JSON Schema 和显式 Ollama 配置；可在已有草稿调用中增加结构字段，但不保证 Token 不增加 |
| `requirements_runtime.txt`、`requirements_ml.txt` | 全文。轻量运行清单没有显式列出情绪分类训练栈；ML 清单列出 sentence-transformers。没有核查环境中传递依赖是否齐备 |
| `evaluation/emotion_protocol_20261013.json`、`evaluation/evaluate_emotion_protocol.py` | 全文。开发 12 条、验证 16 条；工程预期、非人工金标准；脚本分别比较 basic 和 scene |
| `evaluation/results/emotion_20261013_before.json` | 分组汇总及案例。新协议基础情绪原规则 7/12 + 8/16 = 15/28 |
| `evaluation/results/emotion_20261013_final.json` | 全文。基础与场景规则均 12/12 + 16/16；未调用模型 |
| `evaluation/results/emotion_20261013_safety_final.json` | 顶层状态、分组和哈希。再次记录规则基础/场景 28/28 |
| `evaluation/results/model_emotion_20261013_v3.json` | 顶层状态、分组和案例数量。capture_state=complete，prompt_version=compact-v8-communication-3，基础 10/12 + 15/16，human_gold=false |
| `evaluation/results/recognition_communication_20261013_first.json`、`evaluation/results/recognition_communication_20261013_final.json` | 分组汇总。旧 60 条协议 dev 基础 27/28、val 基础 31/32；不将工程预期当独立准确率 |
| `evaluation/results/gpu_pair_20261013.json` | 汇总。3 个固定案例、CPU/GPU 各 6 次，属于本地小样本后端对照 |
| `docs/OPEN_SOURCE_REVIEW.md`、`docs/COMMUNICATION_GPU_FIRST_20261013.md` | 历史研究及运行说明。属于项目内记录，不能替代当前官方许可证或远程部署证据 |

可追踪哈希（本次读取时）：

- 情绪实现 SHA256：`30baa23220dea1cb53d7a6a0000d4b8555369554aacfe7b4c48d9d10affe8e4d`。
- communication_brief SHA256：`80c0de36ffb80524b93b02cafe9c0e4c8af88c6038b8c5ba0f77e8d11f475d79`。
- Qwen 适配器 SHA256：`463cb3d2fcfb5793bda4cdb50d0e9076890fac58ba5f866d2154f83454d7098a`。
- 新 28 条协议 SHA256：`fd4cdc00e2354db082073f222ce7d710921c1533433da853bbc8877e281ea211`。
- V3 新协议结果文件 SHA256：`44a8864b620956a562df297acacb3fbcca73d7727c27ae475aed83e7662cc57c`。

## 外部来源、许可证与采用决定

“此前已读”由用户交接记录提供；本轮没有重读这些 README。此前阅读的准确时间、commit 和文件哈希未提供，本轮不补造。以下官方链接用于追踪来源；“待核”链接不是已读证据。

| 项目与路径 | 来源链接 | 已有证据与许可边界 | 本项目决定 |
| --- | --- | --- | --- |
| facebookresearch/EmpatheticDialogues：README.md；LICENSE 待核 | [仓库](https://github.com/facebookresearch/EmpatheticDialogues)、[LICENSE 待核](https://github.com/facebookresearch/EmpatheticDialogues/blob/main/LICENSE) | 此前 README 已读。未成功读取 LICENSE，也未分别确认代码、数据及模型使用条款；分支和许可证路径待核 | 仅作共情对话研究线索；不宣称支持中文，不导入语料 |
| thu-coai/Emotional-Support-Conversation：README.md；独立许可证待核 | [README](https://github.com/thu-coai/Emotional-Support-Conversation/blob/main/README.md) | 此前 README 已读并记录 academic research only。具体许可证、代码与数据条款没有逐项核实 | 商业客服不采用其数据或训练产物；抽象策略仅作为研究讨论，不迁移心理支持干预 |
| IDEA-CCNL/Fengshenbang-LM：README.md；LICENSE 待核 | [仓库](https://github.com/IDEA-CCNL/Fengshenbang-LM)、[LICENSE 待核](https://github.com/IDEA-CCNL/Fengshenbang-LM/blob/main/LICENSE) | 此前 README 记录 Apache-2.0；许可证正文未核实。仓库许可不能自动覆盖独立模型权重、训练语料或衍生模型 | 候选训练/推理框架，暂不增加依赖 |
| IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment：README.md、config.json | [模型卡待核](https://huggingface.co/IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment/blob/main/README.md)、[配置待核](https://huggingface.co/IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment/blob/main/config.json) | config 浏览未取得正文。模型是否可用、参数量、id2label、语言、license 元数据和权重授权均未验证；名称不是配置证据 | 只列为轻量候选，不作已选型或可商用结论 |
| QwenLM/Qwen3：README.md；LICENSE 与具体模型卡待核 | [仓库](https://github.com/QwenLM/Qwen3)、[LICENSE 待核](https://github.com/QwenLM/Qwen3/blob/main/LICENSE)、[Qwen3-8B 模型卡待核](https://huggingface.co/Qwen/Qwen3-8B/blob/main/README.md) | 此前仓库已读；本轮未完成官方 license、权重卡及具体量化制品溯源。项目中有 Qwen 适配器不等于权重授权已核实 | 优先利用已有一次生成，不增设情绪专用 LLM 调用；是否采用更大模型须质量实测 |
| ollama/ollama：README.md；LICENSE 待核 | [仓库](https://github.com/ollama/ollama)、[LICENSE 待核](https://github.com/ollama/ollama/blob/main/LICENSE) | 此前仓库已读。项目 2026-10-10 报告记为 MIT，但当前正文未核实；运行器许可不覆盖加载的模型权重 | 沿用已有接口；不把本地运行解释为任意模型均可商用 |

Apache-2.0 候选若以后核实适用，需保留许可证、适用的 NOTICE 和修改说明；MIT 候选需保留版权与许可文本。此处为集成前待核清单，不是已完成授权审查或法律结论。没有为任何未核实权重宣称商业许可。

## 中文问题与具体融合方案

| 问题 | 已有能力与局限 | 建议融合方式 |
| --- | --- | --- |
| 弱线索：“单号给过了” | 已有重复信息需求抽取；基础规则仍依赖有限表达，单标签不能涵盖全部负担 | 先输出可追踪的服务负担与未解决事项，再决定是否存在情绪证据。弱证据可保留 neutral 和待复核原因 |
| 反讽：“你们可真厉害，又让我等” | 已有特定组合规则与反讽提醒；不代表泛化到所有反讽 | 要求字面正向词与负面事件同时留证；作为“可能反讽”，不自动认定 angry。不得用单个正向词覆盖争议 |
| 混合情绪：“喜欢商品，但退款未到账” | 当前主要输出一个基础标签；未解决事项已有独立记录 | 为每个分句保留表达对象、正负线索和业务事项；愉快不能清除退款等待，也不推断所有“但”后句都是情绪 |
| 场景情绪与风险 | 购买犹豫可能 basic=neutral；allergy_anxiety 包含担忧语境，不能作为医学事实 | 独立记录 basic、scene、communication need、risk。以明确用后不适及业务规则处理风险；分类器不得降级已识别风险 |

建议优先顺序：

1. **无新依赖、无新增调用**：继续由已有信息生成沟通策略，策略依据保持 `basis`；低证据情绪仅给待复核提示。客服草稿回应具体等待、材料重复与当前诉求，不确认未知退款完成状态。
2. **复用已有草稿生成**：如果需要补判，放入现有一次结构化生成，限定基本标签、归属、原话依据和分歧原因；保留规则与模型两份结果及最终采用来源。增加字段可能增加 Token，不宣称零成本。
3. **轻量分类器仅作后续实验**：确认模型卡、配置、权重与数据授权后，用合规自有中文客服标注训练/校准。二分类只输出 polarity 辅助信号，五类情绪和场景使用分别监督；先旁路对照，不能无条件覆盖规则或安全信号。

新增分类器需报告每类 precision/recall/F1、Macro-F1、neutral 与礼貌用语误报、反讽/混合/他人引用切片、拒判率和延迟。没有独立、未接触的人工标注测试集前，只能报告工程协议匹配，不能报告客户准确率。

## 测量口径及 V3 退步

V3 冻结 30 条最终数据采用用户于 2026-10-13 的最新实测交接；本轮未定位并重算该完整工作流结果文件。新 28 条 V3 模型协议已读取实际结果文件。两种来源在 JSON 中分别标记，未新做人工标注或复核。

| 测量对象 | 结果 | 可解释范围 |
| --- | --- | --- |
| 新 28 条协议，基础规则前后 | 15/28 → 28/28；最终 dev 12/12、val 16/16 | 开发期间修复的工程回归，非独立准确率 |
| 新 28 条协议，最终场景规则 | dev 12/12、val 16/16 | 仅场景标签工程匹配，不是模型结果 |
| 新 28 条协议，V3 模型完整草稿 | **25/28**；dev **10/12**、val **15/16** | `model_emotion_20261013_v3.json`；3 条不匹配，非金标准，不能用规则 28/28替代 |
| 旧 60 条表达协议，当前基础规则 | dev 27/28、val **31/32** | 礼貌“谢谢”按 neutral 处理后的当前记录；与新 28 条不同，保留不匹配 |
| 已接触冻结 30 条，V3 最终基础情绪 | **21/30，Macro-F1=0.6511** | 按明确映射比较，事后复测；V2 为 10/30 且含 1 条字段缺失 |
| 已接触冻结 30 条，V3 最终意图 | **21/30；V2 为 23/30，下降 2 条** | 不隐藏退步；单项情绪改善不能证明总体质量改善 |
| 已接触冻结 30 条，V3 最终风险 | **27/30** | 不是风险召回；旧标签高/紧急正例不足，不能宣称识别完整 |

基础情绪映射固定披露：过敏担忧→fearful、价格不满→angry、效果失望→sad、满意→happy。购买犹豫不能强行映射五类基础情绪；此前说明本批没有该标签，未在本輪重查全部原标签。其余标签、映射表及 Macro-F1 的类集合须随实际评测文件保存；不能从 21/30自行反推 Macro-F1。

冻结集已被开发接触，V2 与 V3 基础字段完整性也存在差异，不能把 10/30→21/30写成独立盲测提升。风险旧 29/30 与当前 27/30的分歧在项目记录中涉及不适安全升级，保留旧标签，不能调低风险来追求匹配。当前数值不证明人工共情质量、用户满意度或人工效率。

## 硬件条件建议

| 条件 | 建议 | 限制 |
| --- | --- | --- |
| 本地 RTX 5060 8GB（用户提供的设备条件） | 优先现有规则/沟通摘要；轻量分类器以后可先 CPU 旁路对照。复用已有 Qwen 量化实例时限制上下文、输出和并发，先记录峰值显存和延迟 | 本轮未检查设备或跑显存测试。8B 若为 4-bit，纯权重理论约 4GB（十进制）只是估算，实际还含量化元数据、KV cache、运行器和其他进程；不能保证 8GB 全部 GPU 驻留 |
| 4×RTX 3090（用户给出的远程目标） | 仅在成功登录并确认每卡容量、空闲、驱动与运行器后，比较独立副本、批量分类实验或更大模型；优先测同输入质量与队列吞吐 | `amax-server` SSH 被 publickey,password 拒绝，配置和可用性未验证；未部署、未启动任务。不能把四卡显存当一个连续显存池或保证线性加速 |

已有 `gpu_pair_20261013.json` 的 CPU/GPU 中位数分别约 17.18 秒和 3.82 秒，仅为 3 个固定案例、每后端 6 次的本地记录，不能外推远程 3090、生产并发或确定提速。当前不下载大模型。

## 可提出但本次不实现的进一步能力

1. **分句表达与对象留证**：在现有正则与标准库范围内，为转折前后记录原文 span、customer/third_party 归属和 positive/negative cue，增加 `mixed_expression`、`possible_sarcasm` 提示。保留主标签，提升客服可见证据，不承诺识别准确率增加；涵盖“喜欢商品但退款未到账”“他说生气但我没有”。
2. **未解决事项及重复材料连续记录**：基于现有截断时点与 source id，把已给材料、重复请求和等待事项联系到具体服务问题，提供“沿用哪些信息、客服需查哪一步”的摘要。订单/事项不明确时保留未知，不把身份相似或礼貌话当解决证据，不跨未确认身份合并。

这两项均为设计建议，尚未实现，也不新增模型调用。引入前用新措辞检查否定、他人引用、事项切换和多订单误合并；另以未接触的合规真实样本进行以后的人工作业评估。

## 交付状态

报告记录了研究线索、4个补充外部文件核查、模型权重许可待核和具体融合建议。独立人工评估、中文候选权重配置核查及远程部署未完成，没有宣称人工复核完成。
