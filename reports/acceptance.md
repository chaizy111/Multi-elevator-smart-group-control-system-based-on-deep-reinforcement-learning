# 最终验收记录

验收对象：原始`实施方案.md` v1.0；2026-10-23。**P0–P10软件工程验收通过；建议的综合算法效果目标未达到。** 原始需求与方案保持原文。没有以随机模型或静态演示替代真实训练、推理和交互。

## 实际执行记录

项目根目录使用`conda activate elevator`及`source scripts/project_env.sh`；锁定依赖已在独立.venv安装。以下均为实际执行结果。

| 命令/检查 | 结果 | 证据 |
|---|---|---|
| `bash scripts/bootstrap.sh` | 退出0，uv frozen、npm ci、构建 | [安装日志](bootstrap.log) |
| `.venv/bin/python scripts/run_quality.py` | 10/10检查退出0 | [真实命令/退出码/耗时](quality/checks.json) |
| 完整pytest | 79 passed | [日志](quality/pytest.log)、[JUnit](quality/pytest.xml) |
| Ruff lint/format、Pyright | 全部通过，类型0错误 | [lint](quality/ruff.log)、[格式](quality/format.log)、[类型](quality/pyright.log) |
| Prettier/TypeScript/Vitest/Vite | 格式/类型/构建通过，2单测通过 | [格式](quality/frontend-format.log)、[类型](quality/frontend-types.log)、[单测](quality/frontend-unit.log)、[构建](quality/frontend-build.log) |
| `scripts/run_acceptance.py` | 四策略同一Trace全部完成 | [日志](quality/real-chain.log)、[真实run ID及指标](acceptance_smoke.json) |
| Playwright真实Chromium | 5 passed，真实服务/WS/worker/模型，最快模式归档趋势首尾已核验 | [日志](quality/browser-e2e.log)、[结构化结果](playwright.json) |
| `scripts/audit_experiments.py` | 9770次、322436乘客行独立重算通过 | [审计](formal/raw_audit.json)、[日志](formal/audit-console.log) |
| CI本地YAML解析及shell语法 | 通过，远端未执行 | [检查结果](ci-local-check.json)、[CI说明](../docs/ci.md) |

pytest保留一条第三方Starlette/httpx弃用提示，未造成失败。尚未推送触发GitHub runner，不将本机通过描述为远端或跨平台CI通过。

生产演示入口`http://127.0.0.1:8000`也已实际启动，30F8E加载ppo-curriculum完成仿真，终态趋势与下载指标一致；[生产入口记录](production_smoke.json)。

## 20.2 工程验收逐项证据

下列测试均包含在上述完整流水线中，链接用于定位具体断言。

| 必须验收项 | 结论及实际证据 |
|---|---|
| 干净环境安装及三端运行 | 通过；仓库内独立.venv、uv/npm锁文件；bootstrap重装构建；真实API与浏览器进程 |
| 建筑边界/非法配置，容量和速度生效 | 通过；[配置](../tests/unit/test_config.py)、[物理](../tests/unit/test_physics.py)、[路线](../tests/unit/test_routes.py)；浏览器5F2E/12F4E/30F8E |
| 五类客流、Burst、确定性Trace | 通过；[模式/哈希测试](../tests/unit/test_physics.py)、formal全部输入SHA复核 |
| 状态机、容量预留、顺序与守恒 | 通过；S01–S12语义由物理/路线/环境/指标/API组合测试覆盖；随机属性、冻结停站、满载未来接人、同刻排序 |
| 四控制策略共用物理路由 | 通过；[同流链路](acceptance_smoke.json)，统一Simulator和可行插入 |
| PPO真实训练、优化器与双头更新 | 通过；[课程记录](training_summary.json)：T0两头5351/4649样本、梯度非零；T2/T3两头更新，T1按设计约束Stay；[真实训练及中断续训](../tests/integration/test_training.py) |
| 跨楼层/梯数、padding/mask/置换 | 通过；[网络测试](../tests/unit/test_network.py)、[Gym检查](../tests/unit/test_environment.py)，三规模真实推理 |
| 重定位、抢占、cooldown、成本 | 通过；[路线边界](../tests/unit/test_routes.py)含长程到达后冷却、两次启动、drain截止；[积分守恒](../tests/unit/test_metrics.py) |
| Web配置、控制、显示、对比、下载 | 通过；[5个浏览器流程](../frontend/tests/e2e/application.spec.ts)含Pause/Resume/Reset/Stop、实验/曲线/下载、390px；[30F8E截图](browser-30F8E.png) |
| 必需CSV/JSON、输入输出隔离 | 通过；每run独立input_trace.csv/passengers.csv/elevator_trace.csv/metrics_timeseries.csv/decisions.jsonl/events.jsonl/metrics.json/config.json/manifest.json；[归档测试](../tests/unit/test_metrics.py)与9770次原始审计 |
| Mean/P95/Max/Travel/Throughput/Distance/LongWait/完成率 | 通过；[口径文档](../docs/evaluation.md)、[独立重算](formal/raw_audit.json)；严格微秒计算60秒阈值 |
| 未完成/空样本不误排名 | 通过；[反例测试](../tests/unit/test_metrics.py)、[压力完成度/下界](formal/pressure_summary.csv)，26次未完成完整披露 |
| CLI/Web最终指标一致 | 通过；[真实spawn API集成](../tests/integration/test_api.py)逐字段等于同配置内核结果；暂停及速度只影响墙钟 |
| 无核心占位/假模型/静态演示 | 通过；源目录无TODO/FIXME/NotImplemented占位；8个真实checkpoint SHA、日志、CSV、浏览器导出保留 |

FR-1/2对应配置和交通；FR-3对应策略和模型；FR-4对应控制；FR-5/6对应SVG电梯、楼层队列、分页乘客及权威快照；FR-7对应实时/离线指标；FR-8对应同流评价与导出。Shared Encoder、Self-Attention、Global Conditioning、双类决策、多目标积分、泛化及复现均由网络/环境测试和正式矩阵验证。[模块架构索引](../docs/architecture.md)、[特征顺序与单位](../docs/env/features.md)包含设计依据。

## 20.3 实验、模型与文档交付

8个真实可加载模型逐一重算checkpoint SHA256并核对metadata，见[模型清单](model_inventory.json)。演示默认`artifacts/models/ppo-curriculum/`，SHA256=`1a8600fdbecbd2933afed8f4d9fd8c8651f8b88858d9ceffb5f6feccb3cf68c1`。T3实际训练60000决策，验证选中的best为40960；预算与选中步数分别记录。

T0/T1/T2/T3实际预算10000/20000/40000/60000，[训练报告](training.md)含配置、截断率、两头梯度/熵、耗时、验证成本和checkpoint。3个正式模型seed101/202/303均独立初始化、各60000决策，[记录](formal/training_seeds.csv)含参数、耗时、选模及模型哈希。

| 矩阵 | 实际/预定 | 原始索引 |
|---|---:|---|
| standard | 5400/5400 | `artifacts/experiments/standard/runs.csv`；3建筑×5交通×3负载×20Trace×6策略 |
| mixed | 120/120 | `artifacts/experiments/mixed/runs.csv` |
| generalization | 2400/2400 | `artifacts/experiments/generalization/runs.csv` |
| ablation | 1800/1800 | `artifacts/experiments/ablation/runs.csv` |
| pressure | 50/50 | `artifacts/experiments/pressure/runs.csv` |

全部9770个作业执行成功；常规模型全部cohort完整；压力26次cohort在1800秒drain截止仍未全服务，与执行失败区分。322436是跨策略重复归档的乘客行数，不能视为相互独立的乘客样本量。[矩阵覆盖](formal/matrix_coverage.json)、[正式报告](formal/report.md)保留所有差场景。

训练/验证/测试seed隔离；12F3E/18F5E在训练和验证采样中排除，24F7E/30F8E为外推，同一checkpoint直接评估。消融包含同模型强制Stay、同预算重训Dispatch-only、无Attention、无公平性；[汇总](formal/ablation_summary.csv)与[相对完整模型配对区间](formal/ablation_vs_full.csv)分别报告。单seed消融不构成跨seed稳定因果结论。

每常规格20条相同字节Trace，配对bootstrap2000次；跨3模型seed另做分层bootstrap。[分层区间](formal/hierarchical_intervals.csv)、[泛化](formal/generalization_summary.csv)、[负载图](formal/load_response.svg)、[全场景差异图](formal/paired_wait_all_scenarios.svg)均由实际CSV生成。报告覆盖平均/尾部等待、完成率、距离、代理能耗、差值及区间。

**效果判定：未达到。** 中负载相对ETA，MeanWait变化−14.866%、P95变化−29.646%、距离变化+59.744%，未满足距离恶化≤5%要求，[机器判定](formal/effect_target.json)。未修改Trace、弱化ETA或隐藏差场景。标量奖励没有保证距离约束，有限预算和确定性argmax集中派单等仍限制效果。

## 性能与稳定性

硬件macOS arm64、10逻辑核、24GiB，Python3.11.17/PyTorch2.14.1；CPU网络单线程。[硬件及当前模型哈希](training_hardware.json)。

| 项目 | 实际结果 | 明确的测量口径/证据 |
|---|---|---|
| 12F4E、1800s、12人/分钟 | 351人全服务，1.158s | 生成+完整审计+全部CSV/JSON落盘；目标30s；[记录](full_archive_benchmark.json)，run-5803c4926fc4 |
| 同场景纯内核 | 0.118s，总决策p95 0.612ms | 无完整日志，不混同全归档测量；[记录](benchmark.json) |
| 30F8E、10000请求 | 28.866s，189995事件，全完成/无丢失；总决策p95 2.023ms | 每8秒一人的长程稳定性，非过载吞吐；[记录](stress10000.json) |
| PPO batch1纯前向 | CPU p95 0.341ms | 不含ETA/观测，目标20ms；[当前模型测量](training_hardware.json) |
| Pause/Resume确认 | 10次，p95 40.373ms、max 41.822ms | 真实spawn、实际到达后、20x正常负载；进程内HTTP客户端10ms轮询；目标500ms；[记录](control_latency.json) |
| 推送/界面/内存 | 100ms推送周期；30F8E与390px流程通过 | 当前UI状态/表图有界，曲线≤1000点；审计2MB后溢写、最近100条尾部；[真实溢写测试](../tests/unit/test_audit.py) |

中断恢复后再次执行完整质量入口：79项pytest、2项Vitest、5项Playwright及全部静态检查/构建通过。报告仅清理生成SVG行尾空白和日志末尾空行，SVG经XML解析；模型SHA、文档链接和生产入口健康状态复核通过。Git暂存差异检查通过。

## 版本、限制与复现

当前simulator=`event-v3-arrival-cooldown`、route=`insertion-16-v1`、reward=`integrated-v2-start-cutoff`、metrics=`cohort-v2-all-floors`。模型检查物理/观测/动作/奖励/路线/架构兼容。旧v1/v2完整保留`artifacts/legacy/`，不混入当前正式比较。

方案11.4允许预算覆盖；本次未执行20万/80万/200万建议课程，提供`full.yaml`显式200万入口。正式到达窗口120秒、常规drain7200秒在非测试验证seed2000100预先校准，压力1800秒。短窗口/3个模型seed不能解释为长时稳态或生产证明。能源是代理量，未接入真实电梯；GPU/MPS及Linux远端CI未实测。

本地源代码、文档、模型及数据在指定项目目录，后续缓存/临时目录统一项目.cache。早期pytest曾使用系统默认临时目录，随后纠正，不声称全程没有系统临时文件；未更改项目外业务文件，未修改原始需求、方案或用户.vscode。依赖/缓存/模型/大实验产物按方案.gitignore处理，实际交付工作区保留完整文件。

```bash
conda activate elevator
make demo
# http://127.0.0.1:8000 ，交互式API文档 /docs
```

最短同流复核：`source scripts/project_env.sh && .venv/bin/python scripts/run_acceptance.py`。完整训练、保存加载、同流评价、Web展示与下载均已执行，不要求用户完成中间步骤。安装、前端开发、正式resume和审计命令见[README](../README.md)。架构/物理/特征/训练/评价/存储/API/前端/CI/故障排查文档齐全，开发记录见[history](../history.md)。
