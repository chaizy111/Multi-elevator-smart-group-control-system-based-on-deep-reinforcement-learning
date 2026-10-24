"""Explicit development-only validation, independent of training scenario sampling."""

import numpy as np
import torch

from elevator_control.env.environment import ElevatorEnv
from elevator_control.evaluation.metrics import calculate, reward_from_costs
from elevator_control.rl.network import tensor_observations


def summarize_validation(results: list[dict], limits: dict[str, float]) -> dict:
    valid = bool(results) and all(r["eligible_for_ranking"] for r in results)
    means = {}
    for key in ("cost", "mean_wait_s", "p95_wait_s", "distance_floors"):
        values = [r[key] for r in results]
        means[key] = (
            float(np.mean(values)) if values and all(v is not None for v in values) else None
        )
    violation = sum(
        max(0.0, means[k] / limit - 1) for k, limit in limits.items() if means.get(k) is not None
    )
    return dict(
        complete=valid,
        feasible=valid and violation <= 1e-12,
        constraint_violation=violation if valid else None,
        cost=means["cost"],
        mean_wait=means["mean_wait_s"],
        p95=means["p95_wait_s"],
        distance=means["distance_floors"],
        results=results,
    )


def validation_score(result: dict) -> tuple:
    if not result["complete"]:
        return (float("inf"), float("inf"), float("inf"))
    # Infeasible snapshots remain diagnostic candidates; never called accepted models.
    return (result["constraint_violation"], result["mean_wait"], result["p95"])


def expanded_validation(model, config, device) -> dict:
    results = []
    for cfg in config.validation_scenarios:
        building = (cfg.building.floor_count, cfg.building.elevator_count)
        if building in {(12, 3), (18, 5)} or cfg.seed < 1_000_000:
            raise ValueError("validation must exclude held-out buildings and training seeds")
        env = ElevatorEnv(cfg, candidate_inputs=config.candidate_inputs)
        obs, _ = env.reset(seed=cfg.seed)
        while env.sim and not env.sim.done:
            if config.dispatch_only and obs["decision_kind"][1]:
                obs["action_mask"][9:] = False
            with torch.no_grad():
                dist, _ = model.distribution(tensor_observations(obs, device))
            obs, _, terminated, truncated, _ = env.step(int(dist.logits.argmax(-1).item()))
            if terminated or truncated:
                break
        assert env.sim is not None
        metrics = calculate(env.sim)["final"]
        results.append(
            dict(
                seed=cfg.seed,
                trace_hash=env.sim.trace.sha256,
                building=list(building),
                pattern=cfg.traffic.pattern,
                rate=cfg.traffic.arrival_rate_per_min,
                cost=-reward_from_costs(env.sim.costs, cfg),
                **{
                    k: metrics[k]
                    for k in (
                        "eligible_for_ranking",
                        "sample_count",
                        "completion_ratio",
                        "mean_wait_s",
                        "p95_wait_s",
                        "distance_floors",
                    )
                },
            )
        )
        env.close()
    return summarize_validation(results, config.validation_limits)
