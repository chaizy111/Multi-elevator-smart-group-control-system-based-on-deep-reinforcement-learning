"""Descriptive tables and scenario-paired ablations derived from complete run indexes."""

from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from elevator_control.evaluation.suite import paired_bootstrap
from elevator_control.storage.artifacts import write_csv


def supplementary_tables(root: Path, output: Path) -> list[str]:
    ablation = pd.read_csv(root / "ablation" / "runs.csv")
    fields = [
        "mean_wait_s",
        "p95_wait_s",
        "max_wait_s",
        "long_wait_ratio",
        "completion_ratio",
        "distance_floors",
        "energy_proxy",
    ]
    ablation_summary = cast(pd.DataFrame, ablation.groupby("controller")[fields].mean())
    ablation_summary.to_csv(output / "ablation_summary.csv")
    paired = []
    for scenario, part in ablation.groupby("scenario"):
        frame = pd.DataFrame(part)
        base = pd.DataFrame(frame[frame.controller == "ppo:ppo-seed101"]).set_index("trace_hash")
        for policy, group in frame.groupby("controller"):
            if policy == "ppo:ppo-seed101":
                continue
            joined = pd.merge(
                pd.DataFrame(group).set_index("trace_hash"),
                base,
                left_index=True,
                right_index=True,
                suffixes=("_variant", "_full"),
            )
            for metric in ["mean_wait_s", "p95_wait_s", "distance_floors", "energy_proxy"]:
                delta = joined[f"{metric}_variant"] - joined[f"{metric}_full"]
                low, high = paired_bootstrap(delta)
                paired.append(
                    dict(
                        scenario=scenario,
                        controller=policy,
                        metric=metric,
                        trace_count=len(delta),
                        mean_difference=float(np.asarray(delta, dtype=float).mean()),
                        ci_low=low,
                        ci_high=high,
                    )
                )
    write_csv(output / "ablation_vs_full.csv", paired)
    generalization = pd.read_csv(root / "generalization" / "runs.csv")
    generalization["domain"] = np.where(
        generalization.scenario.str.endswith("interpolation"),
        "held-out interpolation",
        np.where(
            generalization.scenario.str.contains("extrapolation-low"),
            "extrapolation low",
            "extrapolation medium",
        ),
    )
    generalization_summary = cast(
        pd.DataFrame,
        generalization.groupby(["domain", "controller"])[
            ["mean_wait_s", "p95_wait_s", "completion_ratio", "distance_floors"]
        ].mean(),
    )
    generalization_summary.to_csv(output / "generalization_summary.csv")
    pressure = pd.read_csv(root / "pressure" / "runs.csv")
    pressure_summary = pressure.groupby("controller").agg(
        runs=("completion_ratio", "size"),
        complete_cohorts=("completion_ratio", lambda values: int((values == 1).sum())),
        completion_ratio=("completion_ratio", "mean"),
        unpicked=("unpicked", "sum"),
        unfinished=("unfinished", "sum"),
        mean_wait_lower_bound_s=("censored_mean_wait_lower_bound_s", "mean"),
    )
    pressure_summary.to_csv(output / "pressure_summary.csv")
    incomplete = int((pressure.completion_ratio < 1).sum())
    return [
        "",
        "## 消融的实际结果",
        "",
        "下表使用完全相同300条Trace；重新训练变体与完整seed101均为60000决策。单个训练seed的消融不构成跨seed稳定因果结论。",
        "",
        "```csv",
        ablation_summary.to_csv(),
        "```",
        "",
        "逐场景相对完整seed101的20条Trace配对差异及2000次区间见ablation_vs_full.csv。",
        "",
        "## 泛化的实际结果",
        "",
        "同一checkpoint直接测试，不在held-out或外推配置追加训练。下表为域内描述性均值，各配置的配对区间单独保留在原矩阵。",
        "",
        "```csv",
        generalization_summary.to_csv(),
        "```",
        "",
        "## 压力与排空截止",
        "",
        f"压力{len(pressure)}次中{incomplete}次cohort未在1800秒drain内全部完成。仅报告完成度、未接到/未完成和等待下界，不按已接到者条件均值排名。",
        "",
        "```csv",
        pressure_summary.to_csv(),
        "```",
        "",
        "中负载等待改善同时距离增加，本次标量奖励没有保证距离5%约束。有限预算、确定性argmax集中派单、重定位空驶和事件信用分配仍需研究；这些结果不构成已达到生产调度目标的证据。",
    ]
