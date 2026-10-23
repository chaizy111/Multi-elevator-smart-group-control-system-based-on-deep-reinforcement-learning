"""Paired trace experiments; resume keys include config, trace and policy identity."""

import json
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from elevator_control.config.schema import SimulationConfig, canonical_hash
from elevator_control.controllers.baselines import Baseline
from elevator_control.storage.artifacts import atomic_json, scenario_hash, write_csv
from elevator_control.traffic.trace import generate


def paired_bootstrap(differences, seed=42, iterations=2000) -> tuple[float, float]:
    x = np.asarray(differences, dtype=float)
    if len(x) == 0:
        raise ValueError("paired bootstrap requires nonempty traces")
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(iterations, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def verify_comparable(manifests: list[dict]):
    if len({m["scenario_hash"] for m in manifests}) != 1:
        raise ValueError("incompatible configuration/trace/version; comparison rejected")


def evaluate_suite(
    suite: dict,
    output: str | Path,
    *,
    model_ids: list[str] | None = None,
    resume=False,
    model_root: str | Path = "artifacts/models",
    workers: int = 1,
) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    policies = list(suite.get("controllers", ["round_robin", "eta", "eta_zone"]))
    if model_ids:
        policies = list(dict.fromkeys(policies + [f"ppo:{m}" for m in model_ids]))
    controllers = {}
    for policy in policies:
        if policy.startswith(("ppo:", "ppo_stay:")):
            from elevator_control.controllers.rl_controller import RLController

            controllers[policy] = RLController(
                policy.split(":", 1)[1],
                root=str(model_root),
                force_stay=policy.startswith("ppo_stay:"),
            )
        else:
            controllers[policy] = Baseline(policy)
    suite_hash = canonical_hash(
        dict(
            suite=suite,
            policies=policies,
            models={p: getattr(c, "model_hash", None) for p, c in controllers.items()},
        )
    )
    manifest_path = output / "manifest.json"
    if (
        resume
        and manifest_path.exists()
        and json.loads(manifest_path.read_text()).get("suite_hash") != suite_hash
    ):
        raise ValueError("resume requires identical suite and model hashes")
    (output / "suite.yaml").write_text(yaml.safe_dump(suite, allow_unicode=True))
    if workers not in (1, 2):
        raise ValueError("evaluation workers must be 1 or 2")
    tasks = []
    for scenario in suite["scenarios"]:
        seeds = scenario.get("seeds", [9001, 9002])
        if len(seeds) != len(set(seeds)):
            raise ValueError("duplicate trace seed in scenario")
        for seed in seeds:
            config = SimulationConfig.model_validate({**scenario["config"], "seed": seed})
            trace = generate(config)
            scenario_key = scenario_hash(config, trace.sha256)
            for policy in policies:
                model_hash = getattr(controllers[policy], "model_hash", None)
                key_fields = dict(scenario=scenario_key, policy=policy, model_hash=model_hash)
                if policy == "eta_zone":
                    key_fields["controller_version"] = controllers[policy].version
                key = canonical_hash(key_fields)[:20]
                tasks.append(
                    dict(
                        path=str(output / "runs" / key),
                        scenario=scenario["name"],
                        seed=seed,
                        config=config.model_dump(mode="json"),
                        trace=trace,
                        policy=policy,
                        model_hash=model_hash,
                        model_root=str(model_root),
                        scenario_hash=scenario_key,
                        resume=resume,
                        controller_version=getattr(controllers[policy], "version", None),
                    )
                )
    rows, failures = [], []
    total = len(tasks)
    manifest = dict(
        schema_version=1,
        status="RUNNING",
        completed=0,
        total=total,
        failed=failures,
        suite_hash=suite_hash,
        policies=policies,
        workers=workers,
        controller_versions={p: getattr(c, "version", None) for p, c in controllers.items()},
    )
    atomic_json(manifest_path, manifest)
    from elevator_control.evaluation.worker import execute_cell

    def collect(results):
        comparable = {}
        for result in results:
            if result["error"]:
                failures.append(result["error"])
            else:
                row = result["row"]
                rows.append(row)
                comparable.setdefault((row["scenario"], row["seed"]), []).append(result["manifest"])
            processed = len(rows) + len(failures)
            if processed % 10 == 0 or processed == total:
                write_csv(output / "runs.csv", rows)
                if failures:
                    write_csv(output / "failures.csv", failures)
            manifest["completed"] = len(rows)
            atomic_json(manifest_path, manifest)
            if processed % 100 == 0 or processed == total:
                print(
                    f"evaluation={output.name} completed={len(rows)}/{total} failures={len(failures)}",
                    flush=True,
                )
        for group in comparable.values():
            verify_comparable(group)

    if workers == 1:
        collect(map(execute_cell, tasks))
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
            collect(pool.map(execute_cell, tasks, chunksize=1))
    manifest["status"] = "FAILED" if failures else "COMPLETED"
    atomic_json(manifest_path, manifest)
    if rows:
        report(output)
    if failures:
        raise RuntimeError(
            f"{len(failures)} failed experiment cells; inspect failures.csv and retry --resume"
        )
    return output


def report(output: str | Path) -> Path:
    output = Path(output)
    frame = pd.read_csv(output / "runs.csv")
    valid = frame[(frame.completion_ratio == 1) & (frame.sample_count > 0)]
    fields = [
        "mean_wait_s",
        "p95_wait_s",
        "max_wait_s",
        "mean_travel_s",
        "long_wait_ratio",
        "throughput_per_min",
        "completion_ratio",
        "distance_floors",
        "energy_proxy",
    ]
    summary = (
        valid.groupby(["scenario", "controller"])[fields].agg(["mean", "median"]).reset_index()
    )
    summary.to_csv(output / "summary.csv", index=False)
    pairs = []
    intervals = []
    for scenario, part in valid.groupby("scenario"):
        base = pd.DataFrame(part[part.controller == "eta"]).set_index("trace_hash")
        for policy, group in part.groupby("controller"):
            if policy == "eta":
                continue
            match = pd.merge(
                group.set_index("trace_hash"),
                base,
                left_index=True,
                right_index=True,
                suffixes=("_policy", "_eta"),
                how="inner",
            )
            for metric in ["mean_wait_s", "p95_wait_s", "distance_floors", "energy_proxy"]:
                delta = match[f"{metric}_policy"] - match[f"{metric}_eta"]
                if len(delta):
                    lo, hi = paired_bootstrap(delta)
                    intervals.append(
                        dict(
                            scenario=scenario,
                            controller=policy,
                            metric=metric,
                            trace_count=len(delta),
                            mean_difference=float(np.asarray(delta, dtype=float).mean()),
                            ci_low=lo,
                            ci_high=hi,
                        )
                    )
                    pairs.extend(
                        dict(
                            scenario=scenario,
                            controller=policy,
                            trace_hash=key,
                            metric=metric,
                            difference=value,
                        )
                        for key, value in delta.items()
                    )
    write_csv(output / "paired_differences.csv", pairs)
    write_csv(output / "confidence_intervals.csv", intervals)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 4))
    for policy, group in valid.groupby("controller"):
        ax.scatter(group.distance_floors, group.mean_wait_s, label=str(policy), alpha=0.7)
    ax.set(xlabel="Distance (floors)", ylabel="Mean wait (s)")
    ax.legend()
    fig.tight_layout()
    for suffix in ["svg", "png"]:
        fig.savefig(figures / f"wait_distance.{suffix}")
    plt.close(fig)
    distributions = []
    for policy, group in frame.groupby("controller"):
        samples = []
        for run_id in group.run_id:
            source = output / "runs" / str(run_id) / "passengers.csv"
            if source.exists():
                values = pd.read_csv(source)["waiting_time"].dropna().to_numpy(dtype=float)
                samples.extend(values.tolist())
        if samples:
            quantiles = np.percentile(samples, [0, 25, 50, 75, 100], method="linear").tolist()
            distributions.append(
                dict(
                    controller=str(policy),
                    count=len(samples),
                    box=quantiles,
                    conditional=not bool(group.eligible_for_ranking.all()),
                )
            )
    atomic_json(output / "distributions.json", distributions)
    manifest = json.loads((output / "manifest.json").read_text())
    text = f"# Experiment report\n\nCompleted: {manifest['completed']}/{manifest['total']}. Failed: {len(manifest['failed'])}.\n\nOnly complete, nonempty cohorts enter summaries. Differences are paired by immutable trace hash; 2,000 trace bootstrap samples, 95% percentile interval. Energy is a proxy, not kWh.\n\n"
    text += (
        "```csv\n"
        + summary.to_csv(index=False)
        + "```\n\n![Wait versus distance](figures/wait_distance.svg)\n\n"
    )
    text += "No claim that PPO improves on ETA is made without independent test evidence. Raw records: runs.csv; paired differences: paired_differences.csv; intervals: confidence_intervals.csv.\n"
    (output / "report.md").write_text(text)
    return output / "report.md"
