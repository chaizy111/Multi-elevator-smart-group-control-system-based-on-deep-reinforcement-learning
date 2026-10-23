# 训练预算与模型说明

本报告由真实 progress.json / updates.csv / checkpoint 生成。初始建议20万/80万/200万未执行；本次使用方案允许覆盖的2万/4万/6万CPU预算，结果不代表收敛。

| 阶段 | 状态 | 决策 | episode | 秒 | Dispatch/Reposition样本 | 截断率 | 验证best成本 | 验证last成本 |
|---|---|---:|---:|---:|---|---:|---:|---:|
| smoke | COMPLETED | 10000 | 674 | 15.3 | 5351/4649 | 0.0000 | 0.6432 | 0.6432 |
| t1 | COMPLETED | 20000 | 926 | 23.5 | 11167/8833 | 0.0000 | 1.0725 | 1.1016 |
| t2 | COMPLETED | 40000 | 1988 | 50.6 | 23420/16580 | 0.0000 | 0.9656 | 0.9819 |
| t3 | COMPLETED | 60000 | 1541 | 124.5 | 46961/13039 | 0.0000 | 1.8120 | 2.1028 |

T1重定位动作强制Stay，其Reposition策略梯度为0属于明确课程设计；T0/T2/T3两个动作头均有真实采样和梯度。best按固定验证完整服务后成本排序，last仅表示最终更新；两者可能不同。

模型：`artifacts/models/ppo-curriculum/weights.pt` 与 metadata.json；输入上限30F8E，训练域5–20F/2–6E，12F3E与18F5E明确排除。跨域可加载不代表效果保证。

硬件与纯前向测量：`reports/training_hardware.json`。完整原始日志：`artifacts/training/{smoke,t1,t2,t3}/`。

训练效果是否超过ETA由独立测试实验判断，不能依据训练reward或单条验证曲线声称提升。
