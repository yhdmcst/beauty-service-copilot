# 场景标注模板

`annotation_pack.json`包含20条开发样本与30条待标注样本，按场景家族划分，初始标签为空。

评估中心将人工标签、模型预测与规则候选分别记录。实际标注和效率计时保存在本机 `data/runtime/evaluation.sqlite`，不随参赛源码分发。

`evaluation/prepare_holdout.py`在模板已存在时拒绝覆盖，新实验使用独立文件。评估方法见 [评估说明](../../docs/EVALUATION.md)。
