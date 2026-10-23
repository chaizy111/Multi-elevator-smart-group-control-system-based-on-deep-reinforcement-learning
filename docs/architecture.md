# 体系结构与扩展

`config → domain/traffic → simulator → controllers/env → rl/evaluation → storage → backend/frontend`。物理内核只依赖配置、领域、Trace，不导入PyTorch、FastAPI或数据库。所有入口复用同一Simulator和可行插入，前端只显示服务器权威状态。

- [配置](config/README.md)：严格校验、单位、规范哈希。
- [领域](domain/README.md)：生命周期、微秒实体与决策绑定。
- [交通](traffic/README.md)：独立随机流与不可变CSV。
- [内核](simulator/README.md)：微阶段、冻结前缀、容量预留与冷却。
- [控制器](controllers/README.md)：只读公开状态与基线。
- [环境](env/README.md)：特征、mask、事件积分、终止与截断。
- [强化学习](rl/README.md)：共享编码器、Attention、SMDP PPO、checkpoint。
- [评价](evaluation/README.md)：配对Trace、完整cohort、统计区间。
- [存储](storage/README.md)：原子归档、manifest、协调器索引。
- [后端](backend/README.md)：spawn作业、幂等命令与WebSocket。
- [前端](frontend/README.md)：页面、状态和SVG生命周期。

新增控制器实现reset/act/close，不改物理；新增交通模式明确OD与生成器版本；改变输入、动作、物理或奖励含义必须升级相应版本，重新验证并拒绝旧模型。扩大30F/8E上限需要同时升级mask、网络契约和模型，不能只放宽UI。

单机单用户设计，默认两个计算worker和一个CLI训练进程；正式实验脚本可显式覆盖训练并发，记录在execution.json，计算worker不写SQLite。仅协调器登记状态、模型和产物索引。
