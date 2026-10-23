# 基于深度强化学习的多电梯智能群控系统

本地运行的确定性多电梯仿真、真实双任务 PPO 训练、同流评价与中文 Web 工作台。支持 5–30 层、2–8 梯、容量 6–20 人；Normal、Morning、Evening、Inter-floor、Burst 及分段组合；RR、ETA、ETA-Zone、PPO 共用同一物理和路线内核。

[实施进度](docs/IMPLEMENTATION_STATUS.md) · [最终验收](reports/acceptance.md) · [正式实验](reports/formal/report.md) · [训练记录](reports/training.md) · [架构与模块文档](docs/architecture.md)

[零基础前端使用手册](docs/frontend/用户使用手册.md) · [PPO与经典算法的数据解读](reports/formal/策略效果解读.md) · [后续优化路线](docs/rl/优化路线.md)

## 启动

在项目根目录，使用已配置的 conda 环境：

```bash
conda activate elevator
source scripts/project_env.sh
python -m elevator_control.cli serve --host 127.0.0.1 --port 8000
```

打开 **http://127.0.0.1:8000**。生产构建由 FastAPI 同源托管，API 文档为 **http://127.0.0.1:8000/docs**。

交付目录包含真实 CPU 模型 `artifacts/models/ppo-curriculum/`。`make demo` 会构建网页并启动服务；没有该模型时明确提示训练命令，不隐式训练或使用随机权重。

## 从干净环境安装

Python **3.11.17**、Node **24.21.0**，具体依赖固定于 `uv.lock` 与 `frontend/package-lock.json`。已在仓库内独立 `.venv` 实测，不修改 conda 包。

```bash
conda activate elevator
bash scripts/bootstrap.sh
source scripts/project_env.sh
uv sync --frozen
npm --prefix frontend ci --cache "$PWD/.cache/npm"
npm --prefix frontend run build
uv run elevator serve --host 127.0.0.1 --port 8000
```

bootstrap 在缺少 uv 时仅安装到本项目 `.tools`；缓存、浏览器和测试临时目录均在项目 `.cache`。Python 不自动下载到项目外。

开发前端可另开终端 `npm --prefix frontend run dev`，Vite 地址 **http://127.0.0.1:5173**，代理 `/api` 与 `/ws` 至8000；后端仍需运行。生产页面使用8000。

## 真实数据与训练

```bash
uv run elevator trace generate --config configs/simulation/demo.yaml --output data/traces/demo.csv
uv run elevator simulate --config configs/simulation/demo.yaml --trace data/traces/demo.csv --controller round_robin
uv run elevator simulate --config configs/simulation/demo.yaml --trace data/traces/demo.csv --controller eta
uv run elevator simulate --config configs/simulation/demo.yaml --trace data/traces/demo.csv --controller ppo --model-id ppo-curriculum
uv run elevator train --config configs/training/smoke.yaml --output artifacts/training/smoke-new
uv run elevator model register --checkpoint artifacts/training/smoke-new/checkpoints/best.pt --model-id ppo-new
```

T0实际一万决策；本次CPU课程T1/T2/T3分别两万/四万/六万。正式3个独立seed与3个重新训练消融各六万。原建议的20万/80万/200万课程预算未执行，不把有界训练当作该规模的收敛证据。`full.yaml`提供200万显式预算。启动/续训、选模、版本与隔离说明见[训练教程](docs/training.md)。

当前物理版本 **event-v3-arrival-cooldown**；旧v1/v2模型与结果完整保存在 `artifacts/legacy/`，不混入当前比较。

## 评价与复现

```bash
uv run elevator evaluate --suite configs/evaluation/smoke.yaml --model-id ppo-curriculum --output artifacts/experiments/smoke-new
uv run elevator evaluate --suite configs/evaluation/standard.yaml --output artifacts/experiments/standard --resume
uv run elevator report --experiment artifacts/experiments/standard
uv run python scripts/formal_report.py
uv run python scripts/audit_experiments.py
```

正式矩阵9770格，常规格20条独立Trace；三模型seed全部保留，含两种插值held-out、两种外推、4类必要消融及压力。当前正式暴露窗口120秒、常规drain7200秒、压力drain1800秒，结论不外推为长时稳态性能。

报告逐Trace配对、2000次bootstrap，并提供跨模型seed分层区间。等待改善、P95、距离、完成率分别报告；综合效果目标的结论见[正式报告](reports/formal/report.md)，不以编译通过或单条训练曲线代替实验结论。

## 检查与性能

```bash
make test
make lint
make acceptance-smoke
uv run python scripts/run_quality.py
uv run elevator benchmark --config configs/simulation/performance.yaml --output reports/benchmark.json
uv run elevator benchmark --config configs/simulation/large.yaml --requests 10000 --output reports/stress10000.json
```

首次浏览器测试：`PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/playwright" node frontend/node_modules/playwright/cli.js install chromium`。真实E2E包含配置、三规模RR/ETA/PPO、暂停/继续/重置/停止、同流实验、训练曲线和下载。

`--requests 10000`为每8秒一人的长程稳定性测试；高负载与集中Burst另见正式pressure矩阵，不将低负载稳定性称为极限吞吐。纯网络前向和含ETA/观测的总决策耗时分开计量。

## 数据与规则

- 输入Trace只含乘客ID、到达、起终点；不会回写分配结果。run保存全cohort乘客CSV、固定采样/关键快照、决策、事件、指标与manifest。
- 等待截止登梯完成，乘梯截止离梯完成；H/final分离。未完成样本保留并显示下界，空样本为null，能源是代理量。
- 整数微秒、同刻固定微阶段；冻结停站名单、完整容量预留、相邻层运动不可中途反转；到达后重新锚定重定位冷却。
- 训练/控制器不能读取未来流；观测为固定padding和mask，共享电梯编码器、两层Self-Attention、全局条件与双动作头均接入真实训练。
- 审计完整保留并有界溢写；worker独立spawn，协调器使用SQLite WAL；控制命令幂等，Reset保留旧数据，断开浏览器不丢作业。

详细语义见[仿真](docs/simulator/README.md)、[环境](docs/env/README.md)、[评价](docs/evaluation.md)、[API](docs/api.md)与[故障排查](docs/troubleshooting.md)。每次开发记录于 `history.md`。

[CI工作流](docs/ci.md)使用相同质量入口并真实训练浏览器所需模型；本次本地验收证据与尚未触发的远端CI分别记录。
