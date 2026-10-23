# 训练、模型与续训

从项目根运行，先 `conda activate elevator` 和 `source scripts/project_env.sh`。隔离安装用户也可用 `uv run elevator` 替代 `python -m elevator_control.cli`。

```bash
python -m elevator_control.cli train --config configs/training/smoke.yaml --output artifacts/training/smoke
python -m elevator_control.cli model register --checkpoint artifacts/training/smoke/checkpoints/best.pt --model-id ppo-smoke
python scripts/run_curriculum.py
python scripts/prepare_formal.py
python scripts/run_formal_training.py --workers 3
```

T0一万决策用于真实双头工程验证；T1两万、T2四万、T3六万为本次有界CPU课程。正式3个独立seed和3个单因素消融各六万，不把这些记录称作20万/80万/200万建议预算的收敛验证。`configs/training/full.yaml`提供200万预算，启动是显式动作，demo不会隐式开始训练。

`best.pt`按固定验证完整服务后成本/P95选择，可能早于最终预算；`last.pt`是最后保存边界。报告同时记录实际训练预算与选中checkpoint步数，避免混淆。

```bash
python -m elevator_control.cli train --resume artifacts/training/t3/checkpoints/last.pt
python -m elevator_control.cli train --config configs/training/full.yaml --output artifacts/training/full --initialize artifacts/training/t3/checkpoints/best.pt
```

resume必须同配置/版本，不改奖励或观察冒充同一训练。Ctrl+C在完整update边界保存；恢复时重置仿真episode，属于统计可复现续训，不承诺逐位连续轨迹。跨课程显式initialize并建立新目录。模型只接受受信任本地checkpoint，Web不开放pickle上传。

日志包括两头样本/熵/梯度、loss/KL/clip fraction、原始四项成本、吞吐和截断率。episodes.csv保存每次reset的完整配置、seed和Trace哈希；split_manifest记录训练/验证/测试隔离和held-out建筑。CPU已实测，CUDA/MPS只作为显式设备选项，跨设备逐位一致性不保证。
