# 训练、模型与续训

当前提交默认使用已经训练好的801模型，启动只复制和验证载荷，不执行训练。先在项目根激活elevator环境并执行`source scripts/project_env.sh`。复现本轮20万决策微调时使用新的输出目录与注册ID：

```bash
.venv/bin/python -m elevator_control.cli train --config configs/training/submission.yaml --initialize assets/release/curriculum-initializer.pt --migrate-candidate-inputs --output artifacts/submission/training/replay-801
.venv/bin/python -m elevator_control.cli model register --checkpoint artifacts/submission/training/replay-801/checkpoints/best.pt --model-id ppo-replay-801
```

初始化检查点为原课程T3获选模型；显式迁移将新增输入列补零，再用真实PPO更新学习。默认关闭迁移，语义不匹配仍会拒绝。配置包含4并行环境、每环境128步、minibatch256、4epoch、共享网络及135组开发验证。完整服务、P95和距离约束先决定可行性，再按等待选检查点。随包801训练预算200000、获选143360步，两者不同。

`best.pt`是验证获选检查点；`last.pt`是最后保存边界。恢复已开始的新训练使用：

```bash
.venv/bin/python -m elevator_control.cli train --resume artifacts/submission/training/replay-801/checkpoints/last.pt
```

resume必须同配置和语义版本，不改奖励或观测冒充同一训练。Ctrl+C在完整update边界保存；恢复时重置仿真episode，属于统计可复现续训，不承诺逐位连续轨迹。跨课程显式initialize并建立新目录。模型只接受受信任本地checkpoint，Web不开放pickle上传。

日志包含双头样本/熵/梯度、loss/KL/clip fraction、四项原始成本、吞吐与截断率。episodes.csv保存reset配置、seed和Trace哈希；split_manifest记录训练/验证/测试边界。开发验证参与选模，不能当作独立最终测试。

smoke.yaml用于小规模工程验证，full.yaml及原T0—T3/消融配置保留作设计与回归参考；它们不等同于提交模型的训练配置。旧课程编排和完整历史复算工具留在dev，本分支不提供失效的旧命令。CUDA/MPS为显式选项，课堂推理使用CPU；跨设备不保证逐位一致。
