# 第二轮的两项离线对照

按2026-10-24最新要求，仅保留下面两项对照。当前服务、训练与默认模型仍使用首版 `ppo-curriculum`，不会自动加载本目录。

| 对照策略 | 保存内容 |
|---|---|
| 候选代价 + 预设规则 | [固定规则定义](policies/candidate-prior.json)，没有神经网络权重 |
| 候选代价 + 预设规则 + PPO调整 | `ppo-opt-s401-n200000-e1`，见[模型元数据](artifacts/models/ppo-opt-s401-n200000-e1/metadata.json) |

两者使用相同六系数 `[1.0, 0.2, 0.0, 1.0, 0.2, 0.0]`。保留401是因为它是第二轮原页面预设模型，并非按测试结果重新挑选。其训练预算为200000决策，获选检查点为40960决策；权重SHA256为 `d38817cd60caa86651bff5c9b06fe1e3be9daaf450a7d3fca6f873907cd78aa3`。

这里保留的是两种策略：一份规则定义、一份PPO神经权重。第三轮全部模型、训练与实验结果已删除；第二轮402/403副本、无关报告及冗余检查点也已删除。保留401训练日志及配置，策略索引见 [policies.json](policies.json)。

保留两策略的2740次原始运行，共1370组相同输入。它们是旧实验的子集，没有重新训练或采样；不能继续把原三模型平均数作为这里的结果。见[对比数据](reports/comparison.md)、[建模与推理说明](docs/reference-pair.md)、[原始数据审计](../../reports/baseline-restore/reference-raw-audit.json)、[权重与输出一致性](../../reports/baseline-restore/reference-compatibility.json)。

`artifacts` 是指向项目内 `../../artifacts/references/round2` 的相对链接。`src` 仅为旧模型的离线推理兼容源码，不是当前网页或训练入口；当前训练流程见[首版建模说明](../../docs/rl/前端PPO建模与流程.md)。
