"""Recompute equal-trace, three-model comparisons from the frozen standard matrix."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

BASELINES = ["eta", "eta_zone", "round_robin"]
MODELS = [f"ppo:ppo-seed{seed}" for seed in (101, 202, 303)]
FIELDS = ["mean_wait_s", "p95_wait_s", "distance_floors", "energy_proxy", "completion_ratio"]


def main():
    runs = pd.read_csv("artifacts/experiments/standard/runs.csv")
    if len(runs) != 5400 or runs.scenario.nunique() != 45:
        raise ValueError("expected the complete frozen standard matrix")
    if not ((runs.completion_ratio == 1) & (runs.sample_count > 0)).all():
        raise ValueError("incomplete or empty cohorts cannot be summarized as ranked results")
    identities = ["scenario", "trace_hash", "controller"]
    if (
        set(runs.controller) != set(BASELINES + MODELS)
        or not (runs.groupby(identities).size() == 1).all()
        or not (runs.groupby(["scenario", "trace_hash"]).size() == 6).all()
    ):
        raise ValueError("each paired trace requires exactly one run of each expected policy")
    summary, changes, wins = [], [], []
    for scope, frame in [
        ("standard_all", runs),
        ("standard_medium", runs[runs.scenario.str.endswith("-medium")]),
    ]:
        means = frame.groupby("controller")[FIELDS].mean()
        ppo = means.loc[MODELS].mean()
        for policy in [*BASELINES, "ppo_3_seed_mean"]:
            values = ppo if policy == "ppo_3_seed_mean" else means.loc[policy]
            summary.append(
                dict(scope=scope, controller=policy, **{k: float(values[k]) for k in FIELDS})
            )
        for policy in BASELINES:
            changes.append(
                dict(
                    scope=scope,
                    baseline=policy,
                    **{
                        f"{key}_change_pct": float((ppo[key] / means.loc[policy, key] - 1) * 100)
                        for key in FIELDS
                        if key != "completion_ratio"
                    },
                )
            )
            p = (
                frame[frame.controller.isin(MODELS)]
                .groupby(["scenario", "trace_hash"])[FIELDS]
                .mean()
            )
            b = frame[frame.controller == policy].set_index(["scenario", "trace_hash"])[FIELDS]
            if not p.index.is_unique or not b.index.is_unique or set(p.index) != set(b.index):
                raise ValueError("baseline and PPO do not share unique paired trace identities")
            paired = (
                pd.merge(p, b, left_index=True, right_index=True, suffixes=("_ppo", "_baseline"))
                .groupby(level="scenario")
                .mean()
            )
            wins.append(
                dict(
                    scope=scope,
                    baseline=policy,
                    mean_wait_scenario_wins=int(
                        (paired.mean_wait_s_ppo < paired.mean_wait_s_baseline).sum()
                    ),
                    scenarios=len(paired),
                )
            )
    output = Path("reports/formal")
    target = json.loads((output / "effect_target.json").read_text())
    medium_eta = next(
        row for row in changes if row["scope"] == "standard_medium" and row["baseline"] == "eta"
    )
    if not np.isclose(medium_eta["mean_wait_s_change_pct"], target["mean_wait_change_pct"]):
        raise ValueError("comparison disagrees with the original medium-load target evaluation")
    pd.DataFrame(summary).to_csv(output / "baseline_comparison.csv", index=False)
    pd.DataFrame(changes).to_csv(output / "baseline_changes.csv", index=False)
    pd.DataFrame(wins).to_csv(output / "scenario_win_counts.csv", index=False)
    print("Verified 5400 paired runs; wrote all-load/medium-load baseline comparisons")


if __name__ == "__main__":
    main()
