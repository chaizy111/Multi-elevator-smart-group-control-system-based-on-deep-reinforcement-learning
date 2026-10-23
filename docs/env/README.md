# env

`observation.py` 注册所有特征名称和顺序，形状与实施方案8节相同。只遍历已到达乘客，固定计数/时间尺度，padding全零；不读取 trace 总人数、未来模式或未来到达。归一化后[-10,10]裁剪并报告比例，评估不更新统计量。

`environment.py` 每次只提交一个当前屏障动作，推进到下一屏障，将期间四项原始成本差映射为奖励；同时间 delta_t 可为0。自然完成 terminated，排空截止 truncated，尾值保留真实最终状态，终态 mask 为0，禁止继续采样。CheckerDiscrete 仅供官方checker自动合法采样，环境本身不容忍非法动作。
