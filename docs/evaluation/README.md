# evaluation

评价以 [0,H) 到达 cohort 为单位。等待以登梯完成为终点，乘梯以离梯完成为终点。未接齐时等待均值明确 conditional，另给全体下界；未送齐或零样本不参与排名。at_horizon 与 final 分别计算，Throughput 永远以 H 内送达人数/H分钟计，不把 drain 当窗口吞吐。

suite 固定 seed，先生成 trace，再共用字节运行所有策略。scenario_hash 核对配置、物理、trace、内核和路线版本；图表从 runs.csv 生成。差值按 trace 配对，并对 trace 做2000次 bootstrap。快照间隔不进入可比性哈希。smoke 仅开发验证，不能冒充正式实验。

## 正式矩阵

`prepare_formal.py`在训练/评价前冻结所有配置与split。标准45格×20trace×6策略（3基线+3独立PPO）；generalization为30格×20trace×4策略；mixed为20trace×6；ablation为15格×20trace×6；pressure为2格×5trace×5。常规到达窗口120秒，常规drain7200秒（压力矩阵1800秒），快照5秒。短窗口与有界60000决策预算均是本次实验限制，不能声称百万步训练或长时稳态结论。

重新训练的Dispatch-only、无Attention、无公平性采用与seed101完整模型相同的60000预算。Stay干预直接使用同一完整checkpoint，仅禁用重定位；与重新训练Dispatch-only分别报告。

离线重算CSV时间戳时先还原整数微秒再相减，特别是严格`wait > 60s`阈值。直接用二进制浮点相减可能把恰好60秒变成60.00000000000001，造成错误长等待比例。`scripts/audit_experiments.py`使用Decimal恢复微秒，独立核对全部当前运行。

`report_sections.py`仅从完整矩阵的运行索引生成消融、泛化和压力汇总，不参与模拟或选模。消融区间先按scenario与trace_hash配对，再以完整seed101为参照；重新训练与强制Stay分别标识。域汇总为每Trace指标的描述性平均，不能当作乘客级独立样本推断。压力表保留未完成cohort，汇总等待下界，避免条件均值误导。

`scripts/compare_baselines.py`复算完整standard与中负载子集的三基线对比；校验每条Trace恰有6种策略且不重复，PPO三个独立训练模型等权平均，再计算相对基线的比例变化。场景胜出数按每场景20条Trace的均值比较，只作描述，不表示显著性。输出与原中负载目标判定交叉核对，解读见[策略效果解读](../../reports/formal/策略效果解读.md)。
