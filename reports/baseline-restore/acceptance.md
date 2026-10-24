# 首版 ppo-curriculum 恢复验收

2026-10-24。按用户最新修正：仅保留第二轮固定规则与规则加PPO两项离线对照，第三轮及后续产物删除；当前训练/建模/推理恢复为首次生成 `ppo-curriculum` 的首版提交 `18fd731`。

| 要求 | 结果与证据 |
|---|---|
| 冻结恢复前改动 | Git原暂存树固定至 `refs/archive/pre-curriculum-restore-20261024`，见[冻结清单](freeze-manifest.json)；未创建新提交或移动当前分支 |
| 恢复首版训练与网络 | 活动源码、原配置、训练/评价脚本与原测试共93文件和首版逐位一致；Attention双任务、四目标奖励、时间GAE及T0→T3流程恢复 |
| 原模型保持不变 | 原 `ppo-curriculum` SHA为 `1a8600fdbecbd2933afed8f4d9fd8c8651f8b88858d9ceffb5f6feccb3cf68c1`；8首版模型的权重和24状态输出不变，见[核验](active-model-compatibility.json) |
| 仅保留第二轮两项对照 | 一份固定规则定义、一份原页面预设401的PPO权重，移至 `references/round2` 与项目内 `artifacts/references/round2`，不进入当前默认运行；24状态输出逐位一致，独立规则与关闭PPO调整的策略一致，见[核验](reference-compatibility.json) |
| 删除第三轮及多余副本 | 第三轮9模型及训练/实验/报告删除，第二轮402/403副本和冗余检查点删除；只保留两策略2740次原始运行，见[最新清理记录](reference-pruning.json) |
| 删除第四轮及后续 | 23模型及训练/报告/配置/脚本/专用测试/关联页面实验与仿真已删除；未发现第五轮产物，见[此前清理记录](cleanup-manifest.json) |
| 页面与索引恢复 | 模型8项，首项及PPO默认 `ppo-curriculum`；活动模型、训练、实验、Trace API无优化引用；保留图表间距等维护 |
| 完整质量验证 | 恢复时10/10通过，pytest79、Vitest2、Playwright5，Ruff/格式/Pyright/TypeScript/Vite及真实同流链路通过：[快照](quality/checks.json)、[日志](full-quality.log) |
| 本次补充验证 | 本次仅裁剪离线档案与更新说明，活动算法未再修改；保留模型/规则真实推理仿真通过，2740次运行共141530条乘客记录独立重算通过，见[原始审计](reference-raw-audit.json) |
| 8000实际服务 | 首版代码运行；真实页面默认模型、实际仿真和8格四策略同流对比已验证：[浏览器核验](browser-check.json)、[截图](browser-comparison.png) |
| 生产原始重算 | 真实PPO运行的模型SHA正确、乘客完整服务并独立重算：[生产核验](production-smoke.json) |

没有重训或覆盖原模型。保留的第二轮数据只反映401与同先验规则的旧实验子集，不能沿用原三模型平均数或宣称PPO稳定胜过规则。见[两项对照说明](../../references/round2/README.md)、[对比数据](../../references/round2/reports/comparison.md)。当前设计见[建模与算法流程](../../docs/rl/前端PPO建模与流程.md)、[恢复说明](../../docs/maintenance/baseline-restore.md)。

恢复中曾遇SQLite事务内WAL checkpoint锁错误，回滚后调整为提交再checkpoint并通过复查；历史源码明确排除活动Ruff扫描。旧冻结清单、历史日志和Git冻结引用保留原记录以便追溯，不表示第三轮模型文件仍在工作区。最新核验见[交付核验](delivery-checks.json)。所有变更只发生在项目内，完成后暂存Git，未提交或推送。
