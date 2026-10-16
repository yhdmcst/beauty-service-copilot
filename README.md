# 美妆客服共情副驾

面向美妆电商人工客服的参赛作品，围绕“看不清服务经过、跟不上未解决事项、判不准当前诉求”设计。工作台整合聊天、订单与售后工单，生成带依据的回复建议，并将待核事项交给人工持续跟进。

对应赛题一“数据共情者 - 消费者的AI管家”。作品使用赛题虚构业务数据、本地开源模型Qwen3:8b与LangGraph工作流，展示从服务理解到人工处置的完整交互。

## 设计亮点

- **有时点的服务轨迹**：同屏核对聊天、订单和工单，历史回放排除后来产生的记录；跨会话关联由人工确认。
- **按事项延续服务**：区分当前、暂缓、条件备选、撤销及已解决诉求，漏液解决后仍能继续跟进泵头问题。
- **把共情落实到下一步**：沿用消费者已给的材料和肤质自述，回应具体等待与重复说明的负担，列出客服应查什么、必要时还需问什么。
- **风险先登记**：风险识别先于模型生成，任务支持认领、期限、等待对象与重开，关联历次分析依据。
- **可审核的生成**：结构校验、资料适用范围和业务声明检查共同约束草稿，原稿、修正与人工审核分别保存。

## 快速运行

需要Python 3.11及Ollama。安装Ollama后下载模型：

```bash
ollama pull qwen3:8b
```

macOS / Linux：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements_runtime.txt
cp .env.example .env
.venv/bin/python scripts/run_demo.py --port 5000
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements_runtime.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts\run_demo.py --port 5000
```

访问 `http://127.0.0.1:5000/`。Windows也可在完成安装后双击 `start_demo.cmd`。已有本机配置时保留原 `.env`。详细安装、模型检查与演示场景见 [运行指南](docs/QUICKSTART.md)。模型不可用时，页面显示降级建议。

## 作品入口

| 页面 | 用途 |
| --- | --- |
| `/` | 项目首页与工作空间导航 |
| `/workbench` | 服务记录、辅助建议、人工审核和跟进任务 |
| `/dashboard` | 风险预警与处置状态 |
| `/evaluation` | 场景标注与效率对照记录 |

## 文件结构

| 目录 | 内容 |
| --- | --- |
| `src/`、`frontend/` | Agent、数据处理、API及交互界面 |
| `data/` | 虚构业务数据与场景知识示例 |
| `evaluation/`、`tests/` | 评测工具、固定协议、结果证据和软件测试 |
| `docs/` | 作品报告、技术设计、运行及评估说明 |
| `presentation/` | 18页展示PPT、演示脚本与展示素材 |
| `scripts/` | 启动、数据导入、模型检查和界面验证工具 |

## 验证结果

当前版本 `compact-v13-service-continuity-1`：软件回归441项通过、3项可选依赖检查跳过。20条固定工程协议的意图与处理焦点均匹配。本地Qwen3:8b完整回归19条成功生成、1条超时降级，全请求中位约10.13秒；工作流匹配结果包含降级案例。样本用于开发回归，评估方法与逐条结果见 [评估说明](docs/EVALUATION.md)。

## 参赛材料

- [作品报告](docs/FINAL_PROJECT_REPORT.md)：场景洞察、创新设计与作品价值。
- [18页展示材料](presentation/README.md)：可编辑PPT与演示视频脚本。
- [Agent设计](docs/AGENT_DESIGN.md)、[技术架构](docs/ARCHITECTURE.md)。
- [提交清单](docs/SUBMISSION_CHECKLIST.md)、[资料索引](docs/README.md)。

作品以人工客服辅助流程为演示范围，知识示例用于展示检索和生成机制，无需接入真实品牌后台。应用保存建议与人工任务，由客服决定是否使用回复。数据来源见 [数据说明](docs/DATA_POLICY.md)，组件声明见 [第三方说明](THIRD_PARTY_NOTICES.md)。
