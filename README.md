# 美妆客服共情副驾

面向美妆电商人工客服的本地工作台。把聊天、订单和售后工单放在一起，辅助判断当前问题、审核回复草稿，并把待核事项交给负责人跟进。不自动发送客户消息，不执行退款、补发或改址。

对应赛题一“数据共情者 - 消费者的AI管家”。当前版本 `compact-v9-item-issues-2`；参赛要求、实现和文件状态见 [提交检查](docs/SUBMISSION_AUDIT_20261015.md)。

## 运行

需要Python 3.11、完整Ollama环境和文本模型 `qwen3:8b`。在项目文件夹内执行：

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements_runtime.txt
Copy-Item .env.example .env
ollama pull qwen3:8b
```

已有 `.env` 时保留自己的配置。模板使用本地Ollama默认11434端口，无云密钥；模型或运行时需在新机器安装，本仓库不提供权重。然后双击 `start_demo.cmd`，打开启动器显示的地址，默认从 `127.0.0.1:5000` 寻找可用端口。

| 页面 | 用途 |
| --- | --- |
| `/workbench` | 会话、订单/工单、辅助建议、人工审核及跟进 |
| `/dashboard` | 风险事项、负责人和处理状态 |
| `/evaluation` | 当前机器的标注与可选效率对照 |

启动、停止、模型探测和可选依赖见 [运行指南](docs/QUICKSTART.md)。应用不需要Node、Docker、Redis或Qdrant；Node只在重新生成PPT等可选工具中使用。当前是回环地址原型，不要直接暴露公网。

## 处理流程

LangGraph执行 `evidence → safety → draft → verify → audit`。先查证据并登记风险，再用本地Qwen生成建议，核对结构和业务声明，保存分析及操作记录。客服决定是否修改、采纳或拒绝。

历史回放排除分析时点之后的记录，未知历史状态不补写。脱敏昵称只给出关联候选，人工确认身份后才合并轨迹。已有资料保留消息来源；买家说发过照片，不等于附件已经收到或可用。详见 [技术方案](docs/ARCHITECTURE.md) 和 [Agent设计](docs/AGENT_DESIGN.md)。

## 验证与成本

当前源码的软件回归为348项。原开发环境12个固定案例为11次生成加1次证据路径，合计8356 Token、系统中位约2.83秒。原30条人工标注的最终意图27/30、基础情绪同映射21/30、风险27/30都是已见样本事后回归，不是独立准确率。

紧凑输出、精确缓存和限用证据路径用于减少重复生成。历史协议交替对照总Token减少6.13%；本轮与V8-5仅差1 Token，不称新增显著降本。本人12条回复复核已完成：8条原V9可见草稿可用、4条改后认可，不称首轮12条全部正确，见 [复核汇总](docs/REPLY_REVIEW_SUMMARY_20261015.md)。改稿未替换自动生成逻辑，实际视频仍待录制，人工效率缺完整任务级计时。

这些模型数字来自原输入，清理副本的昵称和字段不同，没有新机器的质量或性能保证。方法见 [评估说明](docs/EVALUATION.md)，软件及文件检查范围见 [上传验收](docs/UPLOAD_VALIDATION.md)。

## 数据和文件

随附138个虚构会话、998条消息、113笔订单、80张工单的清理副本。标注包是20条开发和30条待标注的空白模板，**不含原30条人工标签或个人数据库**。运行时记录在本机 `data/runtime/` 生成，默认不上传。

数据、截图和PPT仍有赛题来源内容。公开再发布授权、源码许可证尚未确认，建议先用Private仓库；字段清理不替代授权。见 [数据说明](docs/DATA_POLICY.md) 和 [第三方声明](THIRD_PARTY_NOTICES.md)。

- [项目报告](docs/FINAL_PROJECT_REPORT.md)、[赛题原文](docs/CONTEST_BRIEF.md)。
- [15页PPT及视频脚本](presentation/README.md)。
- [文档索引](docs/README.md)、[GitHub上传步骤](docs/GITHUB_UPLOAD.md)。

软件测试：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q -p no:cacheprovider tests
```

测试另需开发依赖，见评估说明。没有安装可选研究依赖时，3项实库检查会明确跳过。
