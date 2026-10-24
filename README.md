# 多电梯智能群控系统 · 课程提交版

在统一离散事件仿真中比较轮询、ETA、ETA-Zone与深度强化学习PPO，支持5—30层、2—8梯、容量6—20人，提供场景配置、实时仿真、同流评价、真实训练曲线及原始数据导出。

**近期提交：** [两页问题陈述与需求设计](submission/00_问题陈述与需求设计.pdf) · [可编辑Word](submission/00_问题陈述与需求设计.docx)

**完整材料：** [交付目录](submission/README.md) · [项目报告原稿](docs/coursework/课程项目报告.md) · [八项要求映射](docs/coursework/作业要求映射.md) · [零基础使用手册](docs/frontend/用户使用手册.md)

## 运行

已配置环境的本机，在项目根执行：

```bash
conda activate elevator
source scripts/project_env.sh
.venv/bin/python -m elevator_control.submission
npm --prefix frontend run build
.venv/bin/python -m elevator_control.cli serve --host 127.0.0.1 --port 8000
```

打开 **http://127.0.0.1:8000**，也可执行 `make demo`。启动仅校验和复制真实模型，不重新训练。首次安装执行 `bash scripts/bootstrap.sh`；Python 3.11、Node及依赖版本固定于版本文件、uv.lock和frontend/package-lock.json。缓存、模型和运行数据留在项目内。

## 模型与结果

默认PPO为 **ppo-consequences-s801-n200000**：完成200000决策训练，选中143360步，427399参数。六项接单后果作为神经网络输入，由PPO学习权衡；没有固定候选评分、教师动作或规则兜底。另提供802/803和原ppo-curriculum作参照。

在同一135组开发客流上，单801的等待/P95/距离为 **13.1399秒 / 33.0974秒 / 147.9481层**；新PPO三微调seed平均等待13.7975秒，原PPO24.4030秒，固定规则11.3546秒。开发数据参与选模，不能称为独立盲测。课程开发交付已获认可；历史严格研究门槛仍未全部通过，确认与最终未打开，见[冻结研究报告](reports/candidate-ppo/report.md)。

本次整理不重新训练或修改PPO网络、奖励、GAE与仿真数学，只整理默认入口、运行路径和交付材料。

## 分支与目录

`dev` 冻结点 **bc0fef6**（源码4adf1be）保留原开发代码、12份注册模型及原始档案清单；`main` 面向教师提交。约10.06GB原始档案继续留在本机artifacts，由Git忽略，分支本身不包含这10GB文件，迁移研究环境时需另复制。

| 目录 | 内容 |
|---|---|
| src/elevator_control | 配置、客流、仿真、控制器、Gym/PPO、评价、存储、API |
| frontend | React/TypeScript页面与浏览器测试 |
| assets/release | 冻结权重、初始化检查点、真实曲线和SHA，约14.7MB |
| configs、tests、scripts | 配置、自动验证、审计、启动与材料生成工具 |
| docs、submission | 模块文档、可修改原稿与可直接提交材料 |
| reports | 冻结研究证据及当前质量检查 |

默认运行归档为artifacts/submission，与历史开发数据隔离。[架构](docs/architecture.md) · [PPO建模](docs/rl/前端PPO建模与流程.md) · [进度](docs/IMPLEMENTATION_STATUS.md) · [发布说明](docs/release/README.md) · [开发记录](history.md)

## 验证与训练复现

```bash
source scripts/project_env.sh
.venv/bin/python scripts/run_quality.py
```

当前10/10通过：Python90、Vitest2、Playwright5，以及格式、类型、构建和真实链路；[证据](reports/quality/checks.json)。远程Linux CI尚未实际运行。

重新训练须使用新的输出目录与模型ID：

```bash
.venv/bin/python -m elevator_control.cli train --config configs/training/submission.yaml --initialize assets/release/curriculum-initializer.pt --migrate-candidate-inputs --output artifacts/submission/training/replay-801
.venv/bin/python -m elevator_control.cli model register --checkpoint artifacts/submission/training/replay-801/checkpoints/best.pt --model-id ppo-replay-801
```

该配置预算200000决策，不在启动时自动执行。完整历史研究重算需要dev及本机归档；教师演示只依赖main内文件。
