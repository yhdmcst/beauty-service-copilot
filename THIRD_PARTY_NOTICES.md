# 第三方组件说明

本项目源码尚未指定开源许可证，赛题数据按主办方允许的范围使用。依赖库、模型权重及数据的权限分别处理。

## 随包前端库

| 文件 | 来源 | 许可文件 |
| --- | --- | --- |
| `frontend/static/vendor/socket.io.min.js` | Socket.IO客户端 | `LICENSE-socket.io-client.txt`，MIT |
| `frontend/static/vendor/echarts.min.js` | Apache ECharts 6.1.0 | `LICENSE-echarts.txt`、`NOTICE-echarts.txt`、`LICENSE-echarts-d3.txt` |

上述许可和NOTICE均保存在同目录，分发时一并保留。

## 运行依赖

Python依赖见 `requirements_runtime.txt`；`.lock`文件记录Windows测试环境。依赖源码、浏览器及模型权重未随包提供。

LangGraph、Ollama和Qwen为工作流及模型底座。具体模型权重需按发布方许可获取，运行器许可不覆盖所有可加载权重。

`requirements_research.txt`中的scikit-learn 1.7.2采用BSD-3-Clause，仅用于可选CPU分类及词法重排实验，默认工作台不加载。

赛题和演示知识中的品牌名称用于说明场景，不代表品牌合作或授权。
