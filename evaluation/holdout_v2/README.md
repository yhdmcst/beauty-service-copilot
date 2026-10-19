# 空白标注模板

20条开发样本和30条待标注样本由随包业务数据生成，按场景家族划分，标签为空。

当前机器的标注及效率记录保存到 `data/runtime/evaluation.sqlite`。模型候选与人工确认分别记录，原个人标签未随包提供。

`evaluation/prepare_holdout.py`不会覆盖已有模板。新实验请另存输入和结果。
