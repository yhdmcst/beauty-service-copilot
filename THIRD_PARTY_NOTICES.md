# 第三方组件与许可

本次整理没有为本项目源码或赛题数据选择开源许可证。项目权利人需要分别决定源码许可，并确认数据、截图和比赛附件的再发布权限。

## 随仓库分发的前端文件

| 文件 | 来源 | 许可文件 |
| --- | --- | --- |
| `frontend/static/vendor/socket.io.min.js` | Socket.IO客户端 | 同目录 `LICENSE-socket.io-client.txt`，MIT |
| `frontend/static/vendor/echarts.min.js` | Apache ECharts | 同目录 `LICENSE-echarts.txt`，Apache-2.0及文件内附属组件声明 |

保留了前端库原文件及许可文字。若上游版本包含额外NOTICE，应随具体版本一起保留。

ECharts 6.1.0的官方NOTICE和d3附属许可已经按对应版本补齐，分别在同目录 `NOTICE-echarts.txt`及 `LICENSE-echarts-d3.txt`。来源为Apache ECharts官方6.1.0标签。

## 安装后使用的组件

Python依赖由 `requirements_runtime.txt`及锁定文件指定，Node的PPT工具依赖由 `package.json`及锁文件指定。未把这些库源码、浏览器、模型权重或本机环境打包为项目自产代码。

LangGraph编排、本地Ollama和Qwen为技术底座；项目自己实现了多源服务时点、有限业务声明检查、客服审核与任务跟踪。模型权重应按其提供方及模型发布方的许可获取。

## 查阅过但未新增依赖

LiteLLM缓存键参数隔离、Outlines结构化输出及Ragas分项评测提供设计参考。没有复制这些仓库的实现，也没有宣称实现完整的外部忠实性指标或网关能力。

仓库README和文档中应保持源码、依赖和数据来源分开。项目中出现真实品牌名称只是赛题或模拟知识的一部分，不是商标授权或商业合作声明。

## 可选研究依赖

`requirements_research.txt`使用scikit-learn 1.7.2（BSD-3-Clause）建立CPU字符特征分类和词法重排实验，工作台默认不加载。库源码、环境和权重不随项目打包；安装分发时保留该版本自带许可和依赖声明。

SetFit（Apache-2.0）、Sentence Transformers（Apache-2.0）、FlagEmbedding（MIT）的查阅文件和采纳边界见 [开源补充报告](docs/OPEN_SOURCE_SUPPLEMENTS_20261014.md)。未安装SetFit或BGE模型，未把词法基线冒充语义模型；库许可不自动授予所有权重或训练语料的使用权限。

LangMem（MIT）、Mem0（Apache-2.0）与Chatwoot非enterprise部分（MIT Expat）的实际源码/许可核查见 [服务记忆研究](docs/SERVICE_MEMORY_RESEARCH_20261014.md)。仅参考记忆结构、身份范围及会话属性，没有复制源码或部署整套产品；Chatwoot enterprise及第三方部分不按MIT一概处理。
