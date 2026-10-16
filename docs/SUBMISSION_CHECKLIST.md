# 参赛提交清单

## 材料对应

| 材料 | 文件或入口 | 状态 |
| --- | --- | --- |
| 展示PPT | `presentation/contest_presentation.pptx` | 18页可编辑展示稿 |
| 演示视频 | `presentation/demo_script.md` | 操作与旁白脚本已提供，视频需实际录制 |
| 作品报告 | `docs/FINAL_PROJECT_REPORT.md` | 场景、设计、创新与价值 |
| Agent设计 | `docs/AGENT_DESIGN.md` | 节点、工具、状态、人工决策与异常处理 |
| 交互Demo | `scripts/run_demo.py`、`start_demo.cmd` | 首页、工作台、风险看板与评估中心 |
| 源码与运行指南 | `src/`、`frontend/`、`README.md`、`docs/QUICKSTART.md` | 安装与演示步骤齐全 |
| 评测依据 | `evaluation/`、`tests/`、`docs/EVALUATION.md` | 固定协议、逐条记录与软件测试 |

初赛材料为展示PPT和实际演示视频。决赛增加Agent设计、现场Demo及源码和运行指南ZIP，具体以赛事安排为准。

## 展示前检查

1. 在展示设备启动Ollama与Qwen3:8b，运行模型检查并实际生成一次建议。
2. 走通S00381退款受阻与S00076举报风险场景，确认审核回执、任务认领及看板更新。
3. 录制实际操作，保留生成状态；剪辑等待时注明。模型不可用或缓存命中时按实际画面说明。
4. 核对PPT、证据页与评估说明的版本和数据口径，区分自动检查与人工评价。
5. 打包源码时排除 `.git/`、`.env`、`.venv/`、日志、缓存和本机运行数据库，保留 `.env.example`。

## 演示范围

作品使用虚构业务数据与知识示例，重点展示服务轨迹、多轮事项、资料复用、人工审核及风险跟进。真实品牌知识、平台接口和生产部署属于可选扩展，不是本作品演示的前置条件。
