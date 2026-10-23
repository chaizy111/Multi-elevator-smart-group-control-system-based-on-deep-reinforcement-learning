# controllers

Controller 的 reset/act/close 与物理内核解耦。DecisionView 含不可变决策、复制快照、预计登梯延迟和已发生的300秒到达，不含未来堆和 Trace。RR 逐个轮转，ETA 选择登梯完成最快者，平局选最低槽位。ETA-Zone 用过去300秒热度除以区域空闲驻留数+1，同区域目标、动作去重、冷却与 PPO 共用。
