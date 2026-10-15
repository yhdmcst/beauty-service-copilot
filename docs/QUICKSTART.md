# 运行指南

## 初次安装

Windows运行README中的Python 3.11安装命令，复制 `.env.example`为本机 `.env`。模板默认本地Ollama，不会使用原开发者的密钥。

应用运行只需要 `requirements_runtime.txt`，不需要Docker、Redis、Qdrant、Node或图片模型。模型生成建议另需安装Ollama并拉取 `qwen3:8b`。Windows和Edge为本机验收环境，其他系统的页面与模型性能需要重新验证。

## 启动和停止

双击 `start_demo.cmd`在后台启动，浏览器关闭不停止服务。需要在终端控制启动/停止时使用：

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py --port 5000
```

终端内按Ctrl+C停止此进程，勿为清理端口关闭不属于本项目的服务。健康检查地址为 `/health`，它说明服务配置状态，不代表实时模型探测已经通过。

模型连通性和预热：

```powershell
.\.venv\Scripts\python.exe scripts\check_local_model.py
```

检查输出的 `gpu_allocation_observed` 和 `gpu_bytes`。新机器默认使用11434；需要独立GPU服务时先安装完整的官方Ollama，再设置 `OLLAMA_GPU_RUNTIME` 指向其目录，用 `scripts/start_local_gpu.ps1` 启动11435并把本机 `.env` 的 `QWEN_API_BASE` 改为 `http://127.0.0.1:11435/v1`。此配置下启动器会检查GPU服务；仓库不包含便携运行时或模型权重。

## 录制场景

工作台选 `S00381`，分析时点为 `13694977354478.PNM`。先看附件快照，再切历史回放，生成退款受阻建议。另一个场景 `S00076`选 `92900836378476.PNM`，展示举报风险和人工认领。

上传版昵称采用演示编号，订单/工单关联和上述分析点保留。首次运行任务和审核记录为空，不能把新的演示操作说成原人工效率实验。

## 空白标注模板

`evaluation/holdout_v2/annotation_pack.json`包含20条开发样本和30条待人工标注样本。上传副本依据字段清理后的数据生成，样本标签为空，不是原人工金标准。

运行时创建的 `data/runtime/evaluation.sqlite`只属于当前机器。不要将它上传GitHub。导出个人标注和计时时，检查脱敏及授权，默认输出目录已忽略。

## 可选页面验收

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements_dev.txt
.\.venv\Scripts\python.exe scripts\run_demo.py --port 5011 --isolated
```

在第二个终端执行：

```powershell
.\.venv\Scripts\python.exe scripts\verify_mainline_ui.py --base http://127.0.0.1:5011 --output evaluation/results/my_ui_check
```

此检查使用Windows的本机Edge和隔离内存数据库，不往正式库写假人工记录。需要另用浏览器时调整脚本的 `EDGE`路径；不要随意改用有原始标注的正式服务。

## 可选知识检索

默认知识为模拟草案，缺已审核证据会被门禁拒绝。生产品牌结论需要经业务确认的来源、商品身份及审核标记。

BGE、Qdrant或Redis都不是比赛原型的运行前提。如自行接入，安装 `requirements_ml.txt`并配置对应服务，重新验证权限、维度、持久化及性能。不要把本机Flask服务直接暴露公网。
