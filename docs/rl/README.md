# rl

当前提交模型为后果输入PPO，默认801检查点。共享电梯编码、两层4头Attention、双任务actor-critic和原奖励/时间GAE保持原定义，派梯评分输入224→230，新增768参数；[建模与流程](前端PPO建模与流程.md)。

PPO按实际事件间隔使用gamma^(dt/10)、lambda^(dt/10)。自然终止不bootstrap，截断使用旧episode最终观测，边界阻断优势递推；采样和更新使用同一mask。模型检查点保存优化器、RNG、配置与版本；跨架构补零迁移必须显式开启。

配置见configs/training/submission.yaml，初始化检查点与模型见assets/release。启动系统只安装载荷，不执行训练。重新训练应指定新目录和ID，命令见根README。held-out 12F3E与18F5E继续排除训练；开发验证与最终数据分离。

[候选输入研究记录](candidate-ppo.md)保留整理前的实验过程，文中“当时默认原PPO”属于历史状态；当前入口以main发布清单为准。固定候选规则仅作离线参照，不进入提交网络的动作评分。
