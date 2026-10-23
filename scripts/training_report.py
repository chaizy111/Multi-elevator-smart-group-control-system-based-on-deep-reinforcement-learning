"""Generate a budget and numerical-diagnostics report from actual training files."""

import json
from pathlib import Path

import pandas as pd
import torch


def main():
    lines = [
        "# 训练预算与模型说明",
        "",
        "本报告由真实 progress.json / updates.csv / checkpoint 生成。初始建议20万/80万/200万未执行；本次使用方案允许覆盖的2万/4万/6万CPU预算，结果不代表收敛。",
        "",
        "| 阶段 | 状态 | 决策 | episode | 秒 | Dispatch/Reposition样本 | 截断率 | 验证best成本 | 验证last成本 |",
        "|---|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    rows = []
    for name in ["smoke", "t1", "t2", "t3"]:
        root = Path("artifacts/training") / name
        progress = json.loads((root / "progress.json").read_text())
        updates = pd.read_csv(root / "updates.csv")
        best = torch.load(root / "checkpoints/best.pt", map_location="cpu", weights_only=False)
        row = dict(
            stage=name,
            status=progress["status"],
            steps=progress["steps"],
            episodes=progress["episodes"],
            elapsed_s=progress["elapsed_s"],
            dispatch_samples=int(updates.dispatch_samples.sum()),
            reposition_samples=int(updates.reposition_samples.sum()),
            truncation_rate=float(updates.truncation_rate.iloc[-1]),
            best_validation_cost=best["validation"]["cost"],
            last_validation_cost=progress["validation"]["cost"],
            dispatch_gradient=float(updates.dispatch_gradient.sum()),
            reposition_gradient=float(updates.reposition_gradient.sum()),
            best_step=best["steps"],
        )
        rows.append(row)
        lines.append(
            f"| {name} | {row['status']} | {row['steps']} | {row['episodes']} | {row['elapsed_s']:.1f} | {row['dispatch_samples']}/{row['reposition_samples']} | {row['truncation_rate']:.4f} | {row['best_validation_cost']:.4f} | {row['last_validation_cost']:.4f} |"
        )
    lines.extend(
        [
            "",
            "T1重定位动作强制Stay，其Reposition策略梯度为0属于明确课程设计；T0/T2/T3两个动作头均有真实采样和梯度。best按固定验证完整服务后成本排序，last仅表示最终更新；两者可能不同。",
            "",
            "模型：`artifacts/models/ppo-curriculum/weights.pt` 与 metadata.json；输入上限30F8E，训练域5–20F/2–6E，12F3E与18F5E明确排除。跨域可加载不代表效果保证。",
            "",
            "硬件与纯前向测量：`reports/training_hardware.json`。完整原始日志：`artifacts/training/{smoke,t1,t2,t3}/`。",
            "",
            "训练效果是否超过ETA由独立测试实验判断，不能依据训练reward或单条验证曲线声称提升。",
        ]
    )
    Path("reports/training.md").write_text("\n".join(lines) + "\n")
    Path("reports/training_summary.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
