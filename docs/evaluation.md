# 运行评价与复现

先按根README安装随包模型。以下命令使用相同乘客流运行ETA和当前PPO，再进行小规模四策略对比；9001/9002为已知演示输入，不能作为新的盲测证据。

```bash
source scripts/project_env.sh
.venv/bin/python -m elevator_control.cli trace generate --config configs/simulation/demo.yaml --output data/traces/demo.csv
.venv/bin/python -m elevator_control.cli simulate --config configs/simulation/demo.yaml --trace data/traces/demo.csv --controller eta
.venv/bin/python -m elevator_control.cli simulate --config configs/simulation/demo.yaml --trace data/traces/demo.csv --controller ppo --model-id ppo-consequences-s801-n200000
.venv/bin/python -m elevator_control.cli evaluate --suite configs/evaluation/submission.yaml --output artifacts/submission/experiments/course-demo --resume
.venv/bin/python -m elevator_control.cli report --experiment artifacts/submission/experiments/course-demo
```

也可使用前端“实验评价”运行同流比较，表格与导出图均来自实际归档。每条Trace在各策略间共享字节，保存Trace/配置/模型/版本身份；`--resume`仅复用身份一致的成功运行。小规模演示不能替代135组开发验证，后者又不能替代尚未打开的确认与最终数据。

等待到登梯完成，乘梯到离梯完成；Throughput仅计H内完成数/H分钟。at_horizon与final分别报告；未完成或空样本停止排名，不用已接到乘客的条件均值宣称胜出。能耗是距离、门循环和启动的代理，不是真实kWh。按Trace配对做bootstrap，不能将同一客流的乘客视为独立算法重复。

[最新研究报告](../reports/candidate-ppo/report.md)保留三微调seed与各参照的结果及失败门槛；[课程报告](coursework/课程项目报告.md)解释单801演示与三seed汇总的区别。历史standard等矩阵配置继续作为输入生成及契约回归依据，其模型和完整复算工具应在dev研究环境使用，不能在main中套用旧模型ID假定随包存在。
