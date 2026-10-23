"""Freeze independent-seed training and every mandatory evaluation cell before execution."""

from copy import deepcopy
from pathlib import Path

import yaml

SEEDS = list(range(9001, 9021))
POLICIES = ["round_robin", "eta", "eta_zone"] + [f"ppo:ppo-seed{s}" for s in [101, 202, 303]]
PATTERNS = ["normal", "morning", "evening", "interfloor", "burst"]


def configuration(f, e, pattern, load):
    return dict(
        building=dict(floor_count=f, elevator_count=e, capacity=12),
        simulation=dict(arrival_horizon_s=120, max_drain_s=7200, snapshot_interval_s=5),
        traffic=dict(pattern=pattern, arrival_rate_per_min=e * load),
    )


def scenario(f, e, pattern, load, label, seeds=SEEDS):
    return dict(
        name=f"{f}F{e}E-{pattern}-{label}", seeds=seeds, config=configuration(f, e, pattern, load)
    )


def main():
    base = yaml.safe_load(Path("configs/training/curriculum.yaml").read_text())
    for seed in [101, 202, 303]:
        value = {
            **deepcopy(base),
            "seed": seed,
            "stage": "T4-independent",
            "total_decisions": 60000,
        }
        Path(f"configs/training/formal-{seed}.yaml").write_text(
            yaml.safe_dump(value, sort_keys=False)
        )
    for name, patch in [
        ("dispatch-only", {"dispatch_only": True}),
        ("no-attention", {"attention": False}),
        ("no-fairness", {}),
    ]:
        value = {
            **deepcopy(base),
            "seed": 101,
            "stage": f"T4-ablation-{name}",
            "total_decisions": 60000,
            **patch,
        }
        if name == "no-fairness":
            for sim in [value["simulation"], *value["scenarios"]]:
                sim["reward"] = {"fairness_weight": 0}
        Path(f"configs/training/{name}.yaml").write_text(yaml.safe_dump(value, sort_keys=False))
    standard = [
        scenario(f, e, p, load, label)
        for f, e in [(8, 3), (12, 4), (20, 6)]
        for p in PATTERNS
        for load, label in [(1, "low"), (3, "medium"), (5, "high")]
    ]
    general = [
        scenario(f, e, p, 3, "interpolation") for f, e in [(12, 3), (18, 5)] for p in PATTERNS
    ]
    general += [
        scenario(f, e, p, load, label)
        for f, e in [(24, 7), (30, 8)]
        for p in PATTERNS
        for load, label in [(1, "extrapolation-low"), (3, "extrapolation-medium")]
    ]
    mixed = configuration(12, 4, "normal", 3)
    mixed["traffic"]["segments"] = [
        dict(start_s=a, end_s=b, pattern=p, arrival_rate_per_min=12)
        for a, b, p in [(0, 40, "morning"), (40, 80, "normal"), (80, 120, "evening")]
    ]
    ablation = [
        scenario(f, e, p, 3, "ablation") for f, e in [(8, 3), (12, 4), (20, 6)] for p in PATTERNS
    ]
    pressure = [
        scenario(30, 8, p, 15, "stress", list(range(9101, 9106))) for p in ["normal", "burst"]
    ]
    for item in pressure:
        item["config"]["simulation"]["max_drain_s"] = 1800
    pressure[1]["config"]["traffic"]["bursts"] = [dict(time_s=30, window_s=0, count=100, origin=30)]
    suites = {
        "standard": dict(controllers=POLICIES, scenarios=standard),
        "generalization": dict(controllers=["eta"] + POLICIES[3:], scenarios=general),
        "mixed": dict(
            controllers=POLICIES, scenarios=[dict(name="12F4E-mixed", seeds=SEEDS, config=mixed)]
        ),
        "ablation": dict(
            controllers=[
                "eta",
                "ppo:ppo-seed101",
                "ppo_stay:ppo-seed101",
                "ppo:ppo-dispatch-only",
                "ppo:ppo-no-attention",
                "ppo:ppo-no-fairness",
            ],
            scenarios=ablation,
        ),
        "pressure": dict(controllers=["round_robin", "eta"] + POLICIES[3:], scenarios=pressure),
    }
    for name, value in suites.items():
        Path(f"configs/evaluation/{name}.yaml").write_text(yaml.safe_dump(value, sort_keys=False))
    Path("configs/evaluation/split_manifest.yaml").write_text(
        yaml.safe_dump(
            dict(
                training_seed_range=[100000, 999999],
                validation_seeds=[2000000, 2000001, 2000002],
                test_seeds=SEEDS,
                pressure_seeds=list(range(9101, 9106)),
                excluded_training_buildings=[[12, 3], [18, 5]],
                extrapolation_buildings=[[24, 7], [30, 8]],
                training_domain=dict(floors=[5, 20], elevators=[2, 6]),
                arrival_horizon_s=120,
                reason="fixed short episodes for complete CPU matrix; conclusions limited to this exposure",
            ),
            sort_keys=False,
        )
    )


if __name__ == "__main__":
    main()
