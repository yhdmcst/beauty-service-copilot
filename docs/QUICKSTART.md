# 运行与演示指南

## 环境准备

使用Python 3.11，按 [首页安装步骤](../README.md)创建虚拟环境，安装 `requirements_runtime.txt`，将 `.env.example`复制为 `.env`。

本地文本生成使用Ollama与 `qwen3:8b`：

```bash
ollama pull qwen3:8b
```

默认模型地址为 `http://127.0.0.1:11434/v1`。应用以本地JSON、SQLite、词法检索和进程缓存运行，无需Node、Docker或外部数据库。模型权重与Python环境由展示设备单独安装。

## 启动与停止

Windows：

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py --port 5000
```

macOS / Linux：

```bash
.venv/bin/python scripts/run_demo.py --port 5000
```

访问 `http://127.0.0.1:5000/`。Windows完成安装后也可双击 `start_demo.cmd`，启动器会寻找可用端口。命令行启动的服务按Ctrl+C停止。

`/health`显示服务版本与模型配置。实际模型连通性使用 `scripts/check_local_model.py` 或一次建议生成检查。模型不可用时页面显示降级状态。

## 演示操作

| 场景 | 会话 | 分析点 |
| --- | --- | --- |
| 退货后退款受阻 | S00381 | 13694977354478.PNM，2026-05-19 15:44:33 |
| 批次疑虑与举报表达 | S00076 | 92900836378476.PNM，2026-05-08 15:53:44 |
| 商品少件 | S00006 | 选择少件问题消息 |

1. 选择会话，查看聊天、关联订单和工单。
2. 在S00381切换附件快照与历史回放，观察更晚工单的排除。
3. 生成辅助建议，展开事项状态、已有资料和下一步。
4. 编辑草稿，填写审核人及备注，保存采纳或拒绝决定。
5. 创建或认领跟进任务，设置期限和等待对象，在风险看板查看状态。

多轮演示可在同一分析点输入“照片已经提供，瓶身漏液，泵头坏了”，生成后再输入“漏液已经解决了，但泵头还是坏的”，查看事项与资料的延续。补充输入用于本地演示，不修改原始聊天。

视频路线与旁白见 [演示脚本](../presentation/demo_script.md)。

## 记录与隔离模式

首次运行创建 `data/runtime/`，保存本机分析、审核、任务与评估记录。正式提交不包含该目录和 `.env`。

界面验证或彩排可使用内存数据库启动：

```bash
python scripts/run_demo.py --port 5011 --isolated
```

此模式停止后不保留操作记录。软件测试使用独立测试数据库，运行方法见 [评估说明](EVALUATION.md)。

## 可选实验

`requirements_ml.txt`和 `requirements_research.txt`用于语义检索、CPU分类等扩展实验，默认工作台不启用。知识示例演示资料用途与适用范围，品牌后台与真实售后写操作不属于运行条件。
