# 第三方组件说明

## 随项目提供的前端组件

| 组件 | 文件 | 许可 |
| --- | --- | --- |
| Socket.IO客户端 | `frontend/static/vendor/socket.io.min.js` | MIT，同目录保留许可文本 |
| Apache ECharts | `frontend/static/vendor/echarts.min.js` | Apache-2.0，同目录保留LICENSE、NOTICE及d3附属许可 |

## 运行与可选依赖

Python依赖由 `requirements_runtime.txt`指定。Flask提供应用，LangGraph编排工作流，Ollama运行本地Qwen模型。可选语义检索依赖见 `requirements_ml.txt`，CPU实验依赖见 `requirements_research.txt`。

依赖、运行器和模型权重按各自发布许可获取，不随源码打包。场景知识和业务数据的来源与用途见 [数据说明](docs/DATA_POLICY.md)。

本作品未附加开源许可证，提交源码不改变第三方组件和赛题材料的权利归属。
