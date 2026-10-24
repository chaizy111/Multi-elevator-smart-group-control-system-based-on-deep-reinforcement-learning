# rl

默认基础路径已恢复首版`ppo-curriculum`训练与建模；共享Attention、双任务actor-critic、四目标奖励、原时间GAE/PPO和T0→T3流程均与`18fd731`一致。本轮只在显式开启候选输入时扩展派梯头。[默认模型流程](前端PPO建模与流程.md)、[恢复说明](../maintenance/baseline-restore.md)。第二轮两项对照仅[离线留存](../../references/round2/README.md)，第三轮已删除，当前不启用候选先验、残差、塑形或门控。

网络遵循实施方案9节尺寸：路线8→32→32的有效楼层mean/max，基础24与路线64送入共享88→128→128；两层4头attention后重新清零padding。楼层、请求和global编码形成96维context；Dispatch逐梯共享评分，Reposition按subject和有效均值，critic按有效mean/max。无电梯编号位置embedding，支持去attention的同输入消融。

PPO按事件实际间隔计算gamma^(dt/10)和lambda^(dt/10)。自然终止不bootstrap，截断使用旧episode最终观测，所有episode边界阻断优势递推。rollout尾部不结束episode。采样时保存mask，更新复用相同mask。双头熵、梯度、样本数和原始成本写入updates.csv。

训练checkpoint为受信任本地产物，保存优化器、线性学习率进度、RNG、版本、配置与依赖。resume仅允许同配置并在update边界重置episode，属于统计续训；跨课程用initialize显式开启新阶段。注册模型仅保存weights-only与JSON元数据，校验所有语义版本和SHA256。held-out 12F3E/18F5E从训练采样器排除；train种子100000–999999，validation为2000000+，测试9001–99999。

## 本次课程预算

`smoke.yaml`为T0一万；`t1.yaml`为固定8F3E且重定位强制Stay的两万；`t2.yaml`为Normal/Morning/Evening双任务四万；`curriculum.yaml`为域随机化六万。`scripts/run_curriculum.py`依次从上一阶段best初始化，每阶段重新创建优化器并保留独立日志，不把阶段切换伪装为无缝resume。`full.yaml`保留200万预算，可由CLI另启；本次有界训练不构成该规模的收敛证据。

注册CPU模型位置：`artifacts/models/ppo-curriculum/`。以当前实际 `progress.json` 与 `updates.csv` 为准，未完成进程不能声明已完成。

[当前模型的优化路线](优化路线.md)从现有派梯/距离分项、验证覆盖和消融出发，区分已观察证据与待验证假设；列出目标约束、基线引导、重定位专项、预算和新盲测要求。它是后续研发建议，不表示已实施新优化或已经达到效果目标。

## 当前候选输入研究

[候选后果输入PPO](candidate-ppo.md)提供逐梯插单预测给网络学习，默认开关关闭；上一轮专用优化已清理，固定规则只作离线对照。
