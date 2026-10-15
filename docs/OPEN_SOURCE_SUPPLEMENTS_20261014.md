# 开源补充与采纳结果

日期：2026-10-14。当前接待引擎为 `compact-v8-knowledge-4`。本轮核查实际源码、许可证，再运行隔离实验；没有改写原30条人工标注、待复核回复或效率记录。

## 筛选与采用

| 项目 | 已核查部分 | 本轮决定 |
| --- | --- | --- |
| [scikit-learn](https://github.com/scikit-learn/scikit-learn) | BSD-3-Clause；`COPYING`、`sklearn/feature_extraction/text.py`，实际安装1.7.2 | 使用字符TF-IDF与LogisticRegression建立可选CPU分类基线和词法重排器；不覆盖当前分类 |
| [SetFit](https://github.com/huggingface/setfit) | Apache-2.0；README、`src/setfit/modeling.py`、LICENSE，实际分类头支持LogisticRegression | 适合作为后续有合规训练样本的语义分类候选；本轮没有安装或训练SetFit，不能把词法基线叫SetFit模型 |
| [Sentence Transformers](https://github.com/huggingface/sentence-transformers) | Apache-2.0许可证；SetFit源码使用其语义编码器 | 保留为语义编码/重排候选。本轮未下载编码器权重，未做语义模型性能验证 |
| [FlagEmbedding / BGE](https://github.com/FlagOpen/FlagEmbedding) | MIT；README、LICENSE、`FlagEmbedding/inference/reranker/encoder_only/base.py` | 核实查询-资料配对重排、设备和batch接口；新增可插拔重排位置，但当前只跑词法基线，未部署BGE权重 |

先前尝试的 `BAAI/FlagEmbedding` 路径返回404，不采用该失败结果，后续成功核查的是 `FlagOpen/FlagEmbedding`。库许可与模型权重、训练数据许可分开；不导入非商业或仅限学术的共情语料。没有复制第三方库代码，使用库API或参考抽象流程。

## 真正进入主流程的修复

知识检索此前的“有一条支持就通过”是整组决策：后续可能把别的已审核但不支持当前问题、明确禁止产品结论或尚无依据的资料一起送入模型。

现在逐条返回 `supported_document_ids`，模型上下文最多只使用3条本次支持的资料。商品匹配与支持度必须来自同一份资料，不能由一份资料的高匹配度借用另一份资料的商品授权。历史接口的回复路径也只接收本次批准资料。

可插拔重排器只能调整已检索资料的顺序，不得增加/丢失ID或改写正文、来源、审核状态等字段；高相似分不等于业务授权。未核实资料仍不准进入生成依据，真实品牌、肤质适配和疗效不因为排名高就被允许。

这是证据过滤保护，不声称语义蕴含判断已经完善。对中文商品身份、品牌政策和真实场景仍需业务审核。

## 已运行的实验

| 实验 | 方法 | 结果 |
| --- | --- | --- |
| 轻量意图分类 | 仅工程开发28条训练，旧工程验证32条，固定参数，不用冻结人工集训练 | 新分类器11/32，现规则26/32；32条均需复核，**不替换** |
| 轻量基础情绪分类 | 同样训练/验证分离，五类基础标签 | 新分类器21/32，现规则31/32；不替换 |
| 可选词法重排 | 8份未审核工程资料、8个预先定义查询 | 原检索8/8、重排8/8，自动放行均0；未测得额外质量收益，**默认不开启** |
| 新主流程12例复测 | 各案例第一遍，11条模型、1条证据路由，内存业务库 | 最终声明/服务规则0检出，零模型不可用降级；原稿10条16处调整保留 |
| 新版本用量 | 同原业务输入，不是单因素性能实验 | 输入6784、输出1573、总8357Token，中位约2.80秒；总Token较V8-3增加0.18%，不声称新降本 |
| 软件与人工完整性 | 全套测试及受保护表前后哈希 | 303项测试通过（含可选CPU依赖）；原30条标注、42条历史和计时任务未改变 |

CPU基线每条预测中位约0.25毫秒，但样本和类别太少，速度不能补偿匹配率不足，也不是生产吞吐。工程验证已见过，不当作新的独立人工准确率。原冻结规则意图21/30、混合情绪10/30、风险27/30保留。

## 实用运行方式

工作台不需要安装研究依赖，新增分类器和重排器不会默认启用。做实验时安装：

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements_research.txt
.venv\Scripts\python.exe -B -X utf8 evaluation/evaluate_lightweight_classifier.py `
  --output evaluation/results/my_classifier_experiment.json
.venv\Scripts\python.exe -B -X utf8 evaluation/evaluate_knowledge_reranking.py `
  --output evaluation/results/my_rerank_experiment.json
```

输出必须用新文件名。不要训练原冻结30条后，再把这30条称作测试准确率。没有审核过的新标注和模型权重时，保持当前规则/模型共用一次生成更稳妥。

## 后续优先级

先收集覆盖各类业务和基础情绪的合规中文标注，另外保留未接触的验证表达；再试SetFit或经许可核实的中文语义编码器。需要更多标注时可以预标和筛分歧，但模型预测不是第二位真人，也不代填本人12条回复确认。

BGE重排应先有真实、已审核的商品/政策资料，比较相关性、证据过滤、耗时和显存，再决定接入。没有知识资料时继续堆检索模型不能提高品牌回答的可靠性。

## 证据

- `evaluation/results/open_source_classification_20261014.json`：训练边界、每类样本、全部分歧及耗时。
- `evaluation/results/open_source_reranking_20261014.json`：8个查询、排名及未审核资料门禁。
- `evaluation/results/open_source_release_20261014/`：当前源码哈希、12条首遍输出、303项回归与原记录完整性。
- `evaluation/results/open_source_ui_20261014/`：隔离数据库软件彩排，不是本人效果验证。

| 查阅文件 | Git blob SHA |
| --- | --- |
| SetFit README | `f30a37f879358ff3e1b24e606e72342098b9ecf9` |
| SetFit modeling.py | `b41a708e65c5fb58941c9e5b6301df4b9584a67c` |
| SetFit LICENSE | `261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64` |
| scikit-learn text.py | `6cea2777b3608b2578fe29c1ce07bbe93f9c0334` |
| scikit-learn COPYING | `3d7ee432c15b685eaa654b6abe8f8e3ea8126a8d` |
| Sentence Transformers LICENSE | `8e5d3560eeeb3e6bb8f233d0ff7cee7372cca397` |
| FlagEmbedding README | `50ef1616329d45cec15b9ff06c0890ea14e60497` |
| FlagEmbedding LICENSE | `360931513aa6c02f933a403202afa99ac2c5bc88` |
| FlagEmbedding base.py | `69b9c35056484763f675c357a5ab0401af5f5a86` |
