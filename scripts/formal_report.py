"""Generate independent-test conclusions and trace/seed-level intervals from actual files."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from elevator_control.evaluation.report_sections import supplementary_tables
from elevator_control.evaluation.statistics import hierarchical_interval
from elevator_control.storage.artifacts import atomic_json, write_csv

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("artifacts/experiments")
SEEDS = [101, 202, 303]


def main():
    report = Path("reports/formal")
    report.mkdir(parents=True, exist_ok=True)
    matrices = []
    for name in ["standard", "mixed", "generalization", "ablation", "pressure"]:
        path = ROOT / name
        manifest = json.loads((path / "manifest.json").read_text())
        if (
            manifest["status"] != "COMPLETED"
            or manifest["completed"] != manifest["total"]
            or manifest["failed"]
        ):
            raise ValueError(f"incomplete matrix {name}: {manifest}")
        frame = pd.read_csv(path / "runs.csv")
        if len(frame) != manifest["total"]:
            raise ValueError(f"missing run index rows in {name}")
        matrices.append(
            dict(
                matrix=name,
                completed=len(frame),
                total=manifest["total"],
                incomplete_cohorts=int((frame.completion_ratio < 1).sum()),
                empty_cohorts=int((frame.sample_count == 0).sum()),
                report=str(path / "report.md"),
                raw=str(path / "runs.csv"),
            )
        )
    standard = pd.read_csv(ROOT / "standard" / "runs.csv")
    hierarchy = []
    for scenario, group in standard.groupby("scenario"):
        complete = group[(group.completion_ratio == 1) & (group.sample_count > 0)]
        base = complete[complete.controller == "eta"].set_index("trace_hash")
        for metric in ["mean_wait_s", "p95_wait_s", "distance_floors", "energy_proxy"]:
            vectors = []
            for seed in SEEDS:
                part = complete[complete.controller == f"ppo:ppo-seed{seed}"].set_index(
                    "trace_hash"
                )
                vectors.append(
                    part[metric].reindex(base.index).to_numpy(dtype=float)
                    - base[metric].to_numpy(dtype=float)
                )
            differences = np.stack(vectors)
            valid = np.isfinite(differences).all(axis=0)
            if valid.any():
                hierarchy.append(
                    dict(
                        scenario=scenario,
                        metric=metric,
                        **hierarchical_interval(differences[:, valid]),
                    )
                )
    write_csv(report / "hierarchical_intervals.csv", hierarchy)
    rows = []
    for seed in SEEDS:
        model = json.loads(
            (Path("artifacts/models") / f"ppo-seed{seed}" / "metadata.json").read_text()
        )
        progress = json.loads(
            (Path("artifacts/training") / f"formal-{seed}" / "progress.json").read_text()
        )
        rows.append(
            dict(
                seed=seed,
                steps=progress["steps"],
                elapsed_s=progress["elapsed_s"],
                episodes=progress["episodes"],
                parameter_count=model["parameter_count"],
                best_checkpoint_steps=model["training_steps"],
                model_hash=model["sha256"],
                validation_cost=model["validation"]["cost"],
            )
        )
    write_csv(report / "training_seeds.csv", rows)
    table = standard.groupby("controller")[
        [
            "mean_wait_s",
            "p95_wait_s",
            "max_wait_s",
            "mean_travel_s",
            "long_wait_ratio",
            "completion_ratio",
            "distance_floors",
            "energy_proxy",
        ]
    ].mean()
    table.to_csv(report / "overall_means.csv")
    medium = standard[standard.scenario.str.endswith("-medium")]
    reference = medium[medium.controller == "eta"][
        ["mean_wait_s", "p95_wait_s", "distance_floors"]
    ].mean()
    candidate = medium[medium.controller.str.startswith("ppo:")][
        ["mean_wait_s", "p95_wait_s", "distance_floors"]
    ].mean()
    effect = dict(
        mean_wait_change_pct=float((candidate["mean_wait_s"] / reference["mean_wait_s"] - 1) * 100),
        p95_change_pct=float((candidate["p95_wait_s"] / reference["p95_wait_s"] - 1) * 100),
        distance_change_pct=float(
            (candidate["distance_floors"] / reference["distance_floors"] - 1) * 100
        ),
        complete=bool((medium.completion_ratio == 1).all()),
    )
    effect["target_achieved"] = bool(
        effect["complete"]
        and effect["mean_wait_change_pct"] <= -5
        and effect["p95_change_pct"] <= 5
        and effect["distance_change_pct"] <= 5
    )
    atomic_json(report / "effect_target.json", effect)
    atomic_json(report / "matrix_coverage.json", matrices)
    # Every figure is a direct transformation of trace-level outcomes.
    plot = standard.copy()
    plot["load"] = plot.scenario.str.rsplit("-", n=1).str[-1]
    fig, ax = plt.subplots(figsize=(9, 4))
    for policy, group in plot.groupby("controller"):
        values = group.groupby("load").mean_wait_s.mean().reindex(["low", "medium", "high"])
        ax.plot([1, 3, 5], values, marker="o", label=policy)
    ax.set(
        xlabel="Arrival rate per elevator (persons/min)", ylabel="Mean wait over paired traces (s)"
    )
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(report / "load_response.svg")
    fig.savefig(report / "load_response.png", dpi=160)
    plt.close(fig)
    intervals = pd.read_csv(ROOT / "standard" / "confidence_intervals.csv")
    chosen = intervals[
        (intervals.metric == "mean_wait_s") & (intervals.controller == "ppo:ppo-seed101")
    ].sort_values("mean_difference")
    fig, ax = plt.subplots(figsize=(11, 11))
    ax.errorbar(
        chosen.mean_difference,
        np.arange(len(chosen)),
        xerr=np.stack(
            [chosen.mean_difference - chosen.ci_low, chosen.ci_high - chosen.mean_difference]
        ),
        fmt="o",
        markersize=3,
        color="#177e73",
    )
    ax.set_yticks(np.arange(len(chosen)), chosen.scenario, fontsize=7)
    ax.axvline(0, color="#a77836", linewidth=1)
    ax.set_xlabel("PPO seed101 minus ETA, mean wait (s), paired 95% CI")
    fig.tight_layout()
    fig.savefig(report / "paired_wait_all_scenarios.svg")
    fig.savefig(report / "paired_wait_all_scenarios.png", dpi=160)
    plt.close(fig)
    worst = (
        hierarchy
        and sorted(
            [x for x in hierarchy if x["metric"] == "mean_wait_s"],
            key=lambda x: x["mean"],
            reverse=True,
        )[:5]
    )
    text = [
        "# 正式实验报告",
        "",
        "本报告基于预先固定的独立测试矩阵。到达窗口120秒，常规排空上限7200秒（压力矩阵1800秒）；每常规格20条独立Trace。3个完整PPO为独立随机初始化，训练seed 101/202/303，每个60000决策。本次并未执行原建议的百万决策预算，也不把短窗口实验解释为长时稳态效果。",
        "",
        "## 矩阵完整性",
        "",
        "| 矩阵 | 已完成/预定 | 未完成cohort | 空cohort | 原始索引 |",
        "|---|---:|---:|---:|---|",
    ]
    for m in matrices:
        text.append(
            f"| {m['matrix']} | {m['completed']}/{m['total']} | {m['incomplete_cohorts']} | {m['empty_cohorts']} | `{m['raw']}` |"
        )
    text += [
        "",
        "## 主要结果",
        "",
        "以下为每条Trace指标的等权均值，非把所有乘客当独立样本。P95为每Trace内部P95再跨Trace平均。所有未完成和空样本均明确保留，禁止以条件均值排名。",
        "",
        "```csv",
        table.to_csv(),
        "```",
        "",
        "## 中负载效果目标",
        "",
        f"MeanWait变化 {effect['mean_wait_change_pct']:.2f}%，P95变化 {effect['p95_change_pct']:.2f}%，距离变化 {effect['distance_change_pct']:.2f}%。建议目标（等待改善≥5%，P95/距离恶化≤5%，完整服务）：{'达到' if effect['target_achieved'] else '未达到'}。",
        "",
        "软件流程和工程验收独立于该效果目标；没有弱化ETA、替换Trace或排除差场景来制造提升。",
        "",
        "## 泛化、消融与不确定性",
        "",
        "12F3E和18F5E在训练与验证采样中明确排除，24F7E和30F8E超过训练域上限。所有泛化直接使用同一原模型，不追加训练。逐场景结果见generalization/runs.csv与配对区间。",
        "",
        "完整seed101、同模型强制Stay、重新训练Dispatch-only、无Attention、无公平性，均有独立标识；3个重新训练消融均与完整模型同seed101、60000决策预算。参数量与种子记录在模型metadata。原始结果位于ablation/runs.csv，不能把直接禁用动作与重新训练混为一谈。",
        "",
        "每模型seed的区间按Trace配对bootstrap2000次。跨3模型seed采用先抽模型seed、再抽配对Trace的分层bootstrap，区间及跨seed均值范围见hierarchical_intervals.csv。3个训练seed仅提供有限的模型方差估计。",
        "",
        "## 表现较差的场景（全部结果仍保留）",
        "",
    ]
    for row in worst or []:
        text.append(
            f"- {row['scenario']}: MeanWait比ETA增加 {row['mean']:.2f}s，分层95%区间 [{row['ci_low']:.2f},{row['ci_high']:.2f}]。"
        )
    text += [
        "",
        "## 解释与限制",
        "",
        "ETA直接使用同一可行插入的精确预计接人时间，是强启发式基线。PPO的mask保证合法性而非最优性；有限预算、未见交通强度及长路线压缩均可造成较差服务时间。负奖励改善不自动意味着P95改善。公平性代价使用超时平方增量，能耗为明确系数的相对代理，不是真实kWh。",
        "",
        "120秒短暴露对初始全部大堂和重定位冷却敏感。应通过full.yaml延长训练，并增加1800秒及更长暴露后再讨论生产结论；本系统不连接真实电梯。所有预算、原始输入、模型哈希及运行明细已保留，结果可用原命令复现。",
        "",
        "![Load response](load_response.svg)",
        "",
        "![All paired scenarios](paired_wait_all_scenarios.svg)",
        "",
        "训练明细：training_seeds.csv；硬件：../training_hardware.json；模型注册表：artifacts/models；最终工程验收见../acceptance.md。",
    ]
    text.extend(supplementary_tables(ROOT, report))
    (report / "report.md").write_text("\n".join(text) + "\n")


if __name__ == "__main__":
    main()
