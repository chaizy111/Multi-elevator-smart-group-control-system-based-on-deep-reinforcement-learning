# 第二轮保留策略的历史对比

仅统计原页面预设401模型与其同先验规则，使用原实验的配对运行子集，没有重新训练或采样，也不是原三模型平均数。等待时间为各运行平均等待的等权均值。变化为PPO相对规则，负数表示等待减少。

| 范围 | 同流配对数 | 规则等待（秒） | 加PPO等待（秒） | 变化 |
|---|---:|---:|---:|---:|
| optimization-generalization | 400 | 13.1902 | 13.4342 | +1.849% |
| optimization-pressure | 10 | 213.4829 | 213.8063 | +0.151% |
| optimization-standard | 900 | 10.9677 | 11.0727 | +0.958% |
| optimization-long | 60 | 9.5386 | 9.4665 | -0.756% |

合计2740次运行、1370组输入，两策略均完整服务。PPO仅在本表长时范围等待均值更低；不能据此声称稳定优于规则。该单模型历史结果不能替代独立的新实验或多训练seed验证。

原始数据入口：
- [optimization-generalization](../artifacts/experiments/optimization-generalization/runs.csv)
- [optimization-pressure](../artifacts/experiments/optimization-pressure/runs.csv)
- [optimization-standard](../artifacts/experiments/optimization-standard/runs.csv)
- [optimization-long](../artifacts/experiments/optimization-long/runs.csv)

每个范围的manifest记录了从原实验筛出的策略和数量，并标为ARCHIVED_SUBSET；原单次运行文件未改写。所有保留乘客行已[独立重算审计](../../../reports/baseline-restore/reference-raw-audit.json)。返回[归档说明](../README.md)。
