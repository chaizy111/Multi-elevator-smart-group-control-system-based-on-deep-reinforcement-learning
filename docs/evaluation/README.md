# evaluation

评价以[0,H)到达cohort为单位，等待终点为登梯完成，乘梯终点为离梯完成。未接齐时等待均值明确为conditional，另给全体下界；未送齐或零样本不参与排名。at_horizon与final分别计算，Throughput始终按H内送达人数/H分钟计，不把drain当作窗口吞吐。

suite固定seed，先生成Trace，再共用字节运行所有策略。scenario_hash核对配置、物理、Trace、内核和路线版本；图表从runs.csv生成。差值按Trace配对，bootstrap以Trace为抽样单位。快照间隔不进入可比性哈希。当前可直接运行的四策略配置为configs/evaluation/submission.yaml，命令见[评价说明](../evaluation.md)。

原始审计函数scripts/audit_experiments.py中的audit(path)从乘客CSV、事件与电梯轨迹独立重算指标，供测试和研究核验复用。时间戳用Decimal恢复整数微秒，避免把恰好60秒误算为大于60秒。该文件的main入口针对dev旧完整矩阵，不是提交版快速检查；main使用scripts/run_quality.py的真实链路及[提交演示原始审计](../../reports/submission/screenshot-audit.json)。

standard、mixed、generalization、ablation、pressure与split_manifest保留原输入定义，供最新研究模块及实验契约测试使用；相关旧报告和完整复算脚本已冻结至dev。report_sections.py保留通用矩阵汇总能力，不能将其历史seed101消融定义混入最新三微调seed的结论。当前效果说明见[课程报告](../coursework/课程项目报告.md)，原始研究门槛见reports/candidate-ppo。
