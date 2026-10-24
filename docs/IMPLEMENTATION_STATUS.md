> 2026-10-24：已清理最小改动优化产物，完成[候选后果输入PPO研究](rl/candidate-ppo.md)的12次/156万决策训练。开发等待13.80秒（原PPO 24.40秒，固定规则11.35秒），完整效果门槛未通过，确认/最终未打开；[结果与限制](../reports/candidate-ppo/report.md)。默认模型仍为原始ppo-curriculum；下方恢复与首版验收记录为此前时点。

# 实施进度与验证证据

2026-10-24按用户要求恢复首版`18fd731`，默认使用原始`ppo-curriculum`。此前仅保留第二轮固定规则与规则加PPO两项离线对照，第三轮9模型及结果、第四轮23模型及后续旧尝试产物均已删除；恢复时训练/环境/网络/控制器及原配置与首版逐文件一致。本轮在该起点新增默认关闭的候选输入研究路径，原模型权重不变。见[恢复验收](../reports/baseline-restore/acceptance.md)、[默认模型建模](rl/前端PPO建模与流程.md)、[历史参考](../references/round2/README.md)。以下P0–P10是首版历史验收。

依据原始`实施方案.md` v1.0，P0–P10已实施并完成本机CPU验收。原始需求和方案保持原文。软件验收通过；建议的综合算法效果目标未达到。逐项记录见[验收报告](../reports/acceptance.md)，真实退出码见[质量流水线](../reports/quality/checks.json)。

| 阶段 | 状态 | 当前版本实际证据 |
|---|---|---|
| P0 工程契约 | 已验证完成 | Python3.11.17/Node24.21.0；uv/npm锁文件；独立.venv；bootstrap重新安装/构建；配置边界 |
| P1 流与物理 | 已验证完成 | 五模式/分段/Burst/Trace哈希；S01精确时间、空流和非法输入测试 |
| P2 多梯与基线 | 已验证完成 | 容量预留、冻结停站、精确ETA、三基线、随机守恒、重定位抢占/到达后冷却测试 |
| P3 归档评价 | 已验证完成 | cohort/H/final口径、原子CSV/JSON、同流配对；独立原始数据审计9770次/322436乘客行 |
| P4 Gym | 已验证完成 | Gym checker、三规模合法rollout、padding/mask、无未来信息、积分守恒 |
| P5 PPO | 已验证完成 | T0一万决策、674episodes、双头非零梯度；共享编码/Attention/置换；真实保存加载与Ctrl+C续训 |
| P6 课程与注册 | 已验证完成（有界预算） | T1/T2/T3=2万/4万/6万；8个真实模型逐一核验SHA256；验证选模与训练报告 |
| P7 服务 | 已验证完成 | 真实spawn控制/幂等/故障/重启/WS；CLI/API指标相等；完整产物下载 |
| P8 Web | 已验证完成 | Playwright5项、Vitest2项；三规模RR/ETA/PPO、控制/下载/实验/曲线、390px窄屏 |
| P9 正式实验 | 已验证完成 | standard5400、mixed120、generalization2400、ablation1800、pressure50；3独立seed、配对与分层区间；失败效果全部披露 |
| P10 性能与交付 | 已验证完成 | pytest79项、10项质量检查；1800秒全归档1.158秒、万请求无丢失、前向p95 0.341ms、控制最大41.822ms；README/模块文档/history/验收记录 |

## 版本与历史隔离

simulator=`event-v3-arrival-cooldown`，route=`insertion-16-v1`；observation=`public-24-8-9-20-v1`，action=`dispatch8-reposition5-v1`；reward=`integrated-v2-start-cutoff`，metrics=`cohort-v2-all-floors`；generator=`poisson-od-v2-quantized-window`，导入保留来源版本。旧v1/v2模型和运行保留`artifacts/legacy/`，不混入当前正式统计。修复经过见[history](../history.md)。

## 已明确的实验决定与限制

方案11.4允许预算覆盖。本次T0/T1/T2/T3为1万/2万/4万/6万；独立seed101/202/303及3种重新训练消融均各6万。原建议20万/80万/200万课程未执行；best checkpoint可早于预算终点，两者分别报告。完整200万配置仍可显式运行。

正式到达窗口120秒、常规drain7200秒在非测试验证seed2000100确定，压力drain1800秒。训练/验证明确排除12F3E/18F5E，24F7E/30F8E为外推，评价不追加训练。短窗口和3个模型seed限制研究结论。

中负载MeanWait改善14.87%、P95改善29.65%，距离增加59.74%，综合目标未满足。压力50次中26次cohort未全服务，全部保留完成率/未完成/等待下界，不用条件均值排名。详见[正式报告](../reports/formal/report.md)。

CPU已验证；GPU/MPS未实测；单机单用户研究系统未接入真实电梯，能源为代理量。GitHub工作流已加入并本地解析检查，尚未推送触发，不声称远端CI通过。源代码、文档、模型和数据均在指定项目目录，后续缓存/临时目录统一项目.cache。早期pytest曾使用系统默认临时目录，随后纠正，不声称全程没有项目外临时文件；未修改项目外业务文件。
