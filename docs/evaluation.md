# 运行评价与复现

```bash
python -m elevator_control.cli trace generate --config configs/simulation/demo.yaml --output data/traces/demo.csv
python -m elevator_control.cli simulate --config configs/simulation/demo.yaml --trace data/traces/demo.csv --controller eta
python -m elevator_control.cli simulate --config configs/simulation/demo.yaml --trace data/traces/demo.csv --controller ppo --model-id ppo-curriculum
python -m elevator_control.cli evaluate --suite configs/evaluation/standard.yaml --output artifacts/experiments/standard --resume
python -m elevator_control.cli report --experiment artifacts/experiments/standard
python scripts/formal_report.py
python scripts/audit_experiments.py
```

正式矩阵共9770格，常规20条独立Trace/格，压力5条/格。常规H=120秒，drain=7200秒；压力drain=1800秒。drain以非测试验证seed2000100校准，模型参数不依据测试集修改。两个插值建筑12F3E/18F5E明确排除训练，24F7E/30F8E直接外推。

核心口径：等待到登梯完成，乘梯到离梯完成；Throughput只计H内完成/H分钟。at_horizon与final分离。未完成显示未接到/未送达、等待下界和条件统计，不用条件均值排名；空样本为null。能耗是距离、门循环和启动的代理，不是真实kWh。

每个模型seed分别配对Trace并做2000次bootstrap；跨seed使用先抽模型再抽Trace的分层区间。原始格、模型哈希、Trace哈希、场景版本及CSV均保留。`--resume`仅复用版本/配置/模型一致的成功格，失败可重试。ETA-Zone控制器版本独立记录，规则更改只作废其缓存。

原始文件见artifacts/experiments各矩阵，正式解读见reports/formal/report.md，逐CSV独立重算结果见reports/formal/raw_audit.json。软件验收与相对ETA的5%建议效果目标分别判定，不选择性隐藏坏场景。
