"""Public consequence inputs for PPO: no fixed score, teacher action or policy fallback."""

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np
import torch
import yaml

from elevator_control.config.schema import SimulationConfig, canonical_hash
from elevator_control.controllers.baselines import Baseline, apply_controller_action
from elevator_control.controllers.rl_controller import RLController
from elevator_control.env.candidates import candidate_features
from elevator_control.evaluation.metrics import calculate
from elevator_control.rl.checkpoint import initialize_network
from elevator_control.rl.network import ActorCritic, tensor_observations
from elevator_control.rl.trainer import TrainingConfig, train
from elevator_control.simulator.engine import Simulator
from elevator_control.storage.artifacts import archive, atomic_json, write_csv
from elevator_control.traffic.trace import generate

ROOT = Path("artifacts/candidate-ppo")
REPORT = Path("reports/candidate-ppo")
REFERENCE = Path("references/round2/policies/candidate-prior.json")
POLICIES = ["eta", "eta_zone", "round_robin", "fixed-rule", "ppo-curriculum"]
CACHE = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def robustness_inputs() -> dict:
    """Reproduce the unopened v2 scopes using the original evaluation definitions."""
    standard = yaml.safe_load(Path("configs/evaluation/standard.yaml").read_text())["scenarios"]
    long = [
        scenario
        for scenario in standard
        if scenario["name"].endswith("medium")
        and scenario["config"]["traffic"]["pattern"] in {"normal", "morning", "burst"}
    ]
    groups = [("long", long, 64_000_000, 5)]
    for name, base, count in [("generalization", 65_000_000, 5), ("pressure", 66_000_000, 3)]:
        scenarios = yaml.safe_load(Path(f"configs/evaluation/{name}.yaml").read_text())["scenarios"]
        groups.append((name, scenarios, base, count))
    splits = {}
    for name, scenarios, base, count in groups:
        rows = []
        for i, scenario in enumerate(scenarios):
            for j in range(count):
                config = SimulationConfig.model_validate(scenario["config"])
                config.seed = base + 100 * i + j
                if name == "long":
                    config.simulation.arrival_horizon_s = 1800
                trace = generate(config)
                if not trace.records:
                    raise ValueError(f"empty robustness input: {name}/{config.seed}")
                rows.append(
                    dict(
                        scenario=scenario["name"],
                        config=config.model_dump(mode="json"),
                        trace_hash=trace.sha256,
                    )
                )
        splits[name] = rows
    return splits


def prepare() -> dict:
    path = ROOT / "protocol.json"
    if path.exists():
        return json.loads(path.read_text())
    assert not Path("artifacts/minimal-ppo").exists() and not Path("reports/minimal-ppo").exists()
    cfg = yaml.safe_load(Path("configs/evaluation/standard.yaml").read_text())
    splits = {}
    empty_inputs = []
    for name, start, count in [
        ("development", 61_000_000, 3),
        ("confirmation", 62_000_000, 10),
        ("final", 63_000_000, 30),
    ]:
        rows = []
        for i, scenario in enumerate(cfg["scenarios"]):
            reserve = 50
            for j in range(count):
                simulation = SimulationConfig.model_validate(scenario["config"])
                simulation.seed = start + 100 * i + j
                trace = generate(simulation)
                while not trace.records:
                    empty_inputs.append(
                        dict(
                            split=name,
                            scenario=scenario["name"],
                            seed=simulation.seed,
                            trace_hash=trace.sha256,
                        )
                    )
                    if reserve >= 100:
                        raise ValueError("nonempty input reserve exhausted")
                    simulation.seed = start + 100 * i + reserve
                    reserve += 1
                    trace = generate(simulation)
                rows.append(
                    dict(
                        scenario=scenario["name"],
                        config=simulation.model_dump(mode="json"),
                        trace_hash=trace.sha256,
                    )
                )
        splits[name] = rows
    # Retained and deleted prior studies have known disjoint ranges; also scan retained run indexes.
    import csv

    seen = set()
    for path_csv in Path("artifacts").rglob("runs.csv"):
        if path_csv.is_relative_to(ROOT):
            continue
        with path_csv.open() as stream:
            for row in csv.DictReader(stream):
                if row.get("seed"):
                    seen.add(int(row["seed"]))
    assert not any(row["config"]["seed"] in seen for rows in splits.values() for row in rows)
    checkpoint = Path("artifacts/training/t3/checkpoints/best.pt")
    original = torch.load(checkpoint, map_location="cpu", weights_only=False)
    registered = torch.load(
        "artifacts/models/ppo-curriculum/weights.pt", map_location="cpu", weights_only=True
    )
    assert all(torch.equal(v, registered[k]) for k, v in original["network"].items())
    protocol = dict(
        version=1,
        splits=splits,
        seeds=[801, 802, 803],
        initializer=str(checkpoint),
        initializer_sha256=sha(checkpoint),
        original_model_sha256=sha("artifacts/models/ppo-curriculum/weights.pt"),
        initialization="three independent fine-tuning RNG seeds from the same original pretrained PPO; not independent pretraining",
        groups=["control", "consequences"],
        pilot_budget=60000,
        extension_budget=200000,
        extension_gate="candidate wait improves >=3% in aggregate versus matched control, or >=5% first-to-last validation improvement in >=2 seeds",
        teacher_actions=False,
        fixed_dispatch_coefficients=False,
        rule_policy_fallback=False,
        original_reward=True,
        value_coefficient=0.5,
        attention=True,
        final_thresholds=dict(
            wait_ratio=0.95, p95_ratio=1.05, distance_ratio=1.05, rule_wait_ratio=1.10
        ),
        used_prior_seed_interval=[51_000_000, 57_000_001],
        retained_seed_count_checked=len(seen),
        reference_definition_sha256=sha(REFERENCE),
        excluded_empty_inputs=empty_inputs,
        input_admission="nonempty Poisson cohorts; empty seeds logged before any policy evaluation, replaced by frozen 50..99 reserve",
    )
    atomic_json(REPORT / "protocol-v1.json", protocol)
    protocol = dict(
        protocol,
        version=2,
        splits={**splits, **robustness_inputs()},
        previous_sha256=sha(REPORT / "protocol-v1.json"),
        amendment="Freeze unopened long/generalization/pressure scopes and statistical thresholds before candidate outcome selection; development inputs and training unchanged.",
        statistical_acceptance="paired model-seed/trace bootstrap; one-sided 98.75% upper ratio <1 for each of three classic baselines and <=1.10 versus rule; no claim of independent pretraining",
    )
    atomic_json(ROOT / "protocol.json", protocol)
    atomic_json(REPORT / "protocol.json", protocol)
    return protocol


class CheckpointPolicy:
    requires_observation = True

    def __init__(self, checkpoint, *, zero_candidates=False):
        data = torch.load(checkpoint, map_location="cpu", weights_only=False)
        self.model = ActorCritic(
            attention=data["config"]["attention"],
            candidate_inputs=data["config"].get("candidate_inputs", False),
        )
        initialize_network(self.model, data)
        self.model.eval()
        self.requires_candidates = self.model.candidate_inputs
        self.zero_candidates = zero_candidates

    def reset(self, config, seed):
        return None

    def close(self):
        return None

    def act(self, view):
        obs = view.observation
        if self.zero_candidates:
            obs = dict(obs)
            obs["candidates"] = np.zeros_like(obs["candidates"])
        with torch.no_grad():
            dist, _ = self.model.distribution(tensor_observations(obs))
        return int(dist.logits.argmax(-1).item())


def evaluate_cell(task):
    row, label, checkpoint, folder = task
    torch.set_num_threads(1)
    config = SimulationConfig.model_validate(row["config"])
    fingerprint = (
        sha(checkpoint)
        if checkpoint
        else sha("artifacts/models/ppo-curriculum/weights.pt")
        if label == "ppo-curriculum"
        else canonical_hash(
            dict(definition=sha(REFERENCE), features=sha("src/elevator_control/env/candidates.py"))
        )
        if label == "fixed-rule"
        else label
    )
    identity = canonical_hash(
        dict(
            config=row["config"], label=label, fingerprint=fingerprint, trace_hash=row["trace_hash"]
        )
    )
    path = Path(folder) / "runs" / identity[:24]
    if (path / "result.json").exists():
        result = json.loads((path / "result.json").read_text())
        assert result["identity"] == identity
        return result
    trace = generate(config)
    assert trace.sha256 == row["trace_hash"]
    sim = Simulator(config, trace)
    if label != "fixed-rule":
        key = (label, fingerprint)
        if key not in CACHE:
            CACHE[key] = (
                CheckpointPolicy(checkpoint, zero_candidates=label.startswith("zero-input:"))
                if checkpoint
                else RLController(label)
                if label == "ppo-curriculum"
                else Baseline(label)
            )
        controller = CACHE[key]
        controller.reset(config, config.seed)
    else:
        weights = np.asarray(json.loads(REFERENCE.read_text())["weights"], dtype=np.float32)
    while sim.advance_until_decision_or_end() is not None:
        if label == "fixed-rule":
            request = sim.current
            assert request is not None
            scores = candidate_features(sim) @ weights
            action = (
                8
                if request.kind == "reposition"
                else min(
                    (i for i in range(8) if request.action_mask[i]), key=lambda i: (scores[i], i)
                )
            )
            sim.apply_action(request.decision_id, action)
        else:
            apply_controller_action(sim, controller)
    sim.assert_invariants()
    archive(sim, path.parent, run_id=path.name, controller_name=label, model_hash=fingerprint)
    result = dict(
        identity=identity,
        scenario=row["scenario"],
        seed=config.seed,
        trace_hash=trace.sha256,
        controller=label,
        run_id=path.name,
        **{k: v for k, v in calculate(sim)["final"].items() if not isinstance(v, dict)},
    )
    atomic_json(path / "result.json", result)
    return result


def evaluate(rows, policies, name):
    tasks = [
        (row, label, checkpoint, str(ROOT / "evaluation" / name))
        for label, checkpoint in policies.items()
        for row in rows
    ]
    with ProcessPoolExecutor(max_workers=3) as pool:
        result = list(pool.map(evaluate_cell, tasks, chunksize=3))
    write_csv(ROOT / "evaluation" / name / "runs.csv", result)
    return result


def means(rows):
    result = {}
    for label in sorted({r["controller"] for r in rows}):
        subset = [r for r in rows if r["controller"] == label]
        complete = all(r["eligible_for_ranking"] for r in subset)
        result[label] = dict(
            complete=complete,
            runs=len(subset),
            **{
                k: float(np.mean([r[k] for r in subset])) if complete else None
                for k in ["mean_wait_s", "p95_wait_s", "distance_floors"]
            },
        )
    return result


def train_cell(task):
    seed, group, budget, protocol, limits = task
    output = ROOT / "training" / f"{group}-s{seed}-n{budget}"
    config = TrainingConfig.model_validate(
        yaml.safe_load(Path("configs/training/curriculum.yaml").read_text())
    )
    config.seed = seed
    config.stage = "candidate-input-" + group
    config.total_decisions = budget
    config.candidate_inputs = group == "consequences"
    config.validate_initial = True
    config.validation_scenarios = [
        SimulationConfig.model_validate(r["config"]) for r in protocol["splits"]["development"]
    ]
    config.validation_limits = limits
    if (output / "progress.json").exists():
        assert json.loads((output / "config.json").read_text()) == config.model_dump(mode="json")
        status = json.loads((output / "progress.json").read_text())["status"]
        if status == "COMPLETED":
            return str(output)
        raise ValueError(f"explicit resume needed for incomplete job: {output}")
    output.mkdir(parents=True, exist_ok=True)
    assert sha(protocol["initializer"]) == protocol["initializer_sha256"]
    with (
        (output / "console.log").open("w", buffering=1) as stream,
        redirect_stdout(stream),
        redirect_stderr(stream),
    ):
        train(
            config,
            output,
            initialize=protocol["initializer"],
            migrate_candidate_inputs=config.candidate_inputs,
        )
    return str(output)


def train_groups(protocol, limits, budget):
    tasks = [
        (seed, group, budget, protocol, limits)
        for group in protocol["groups"]
        for seed in protocol["seeds"]
    ]
    with ProcessPoolExecutor(max_workers=3) as pool:
        for output in pool.map(train_cell, tasks):
            print("completed", output, flush=True)


def summarize():
    result = []
    for path in (ROOT / "training").glob("*/checkpoints/best.pt"):
        data = torch.load(path, map_location="cpu", weights_only=False)
        v = data["validation"]
        result.append(
            dict(
                id=path.parents[1].name,
                checkpoint=str(path),
                seed=data["config"]["seed"],
                group="consequences" if data["config"]["candidate_inputs"] else "control",
                budget=data["config"]["total_decisions"],
                selected_step=data["steps"],
                feasible=v["feasible"],
                wait=v["mean_wait"],
                p95=v["p95"],
                distance=v["distance"],
                violation=v["constraint_violation"],
                learned_input_norm=float(data["network"]["dispatch.0.weight"][:, 224:].norm()),
            )
        )
    atomic_json(REPORT / "development.json", result)
    return result


def qualified(models, references):
    return (
        all(r["feasible"] for r in models)
        and all(r.get("selected_step", 1) > 0 for r in models)
        and all(r.get("learned_input_norm", 1) > 1e-8 for r in models)
        and all(r["wait"] < min(references[p]["mean_wait_s"] for p in POLICIES[:3]) for r in models)
        and np.mean([r["wait"] for r in models])
        <= 0.95 * min(references[p]["mean_wait_s"] for p in POLICIES[:3])
        and np.mean([r["wait"] for r in models]) <= 1.10 * references["fixed-rule"]["mean_wait_s"]
    )


def run_study(protocol, references):
    limits = {
        k: 1.05 * min(references[p][k] for p in POLICIES[:3])
        for k in ["p95_wait_s", "distance_floors"]
    }
    budget = protocol["pilot_budget"]
    train_groups(protocol, limits, budget)
    records = summarize()
    models = [r for r in records if r["group"] == "consequences" and r["budget"] == budget]
    controls = [r for r in records if r["group"] == "control" and r["budget"] == budget]
    trend = sum(
        json.loads(
            (Path(r["checkpoint"]).parents[1] / "validation-results" / "60000.json").read_text()
        )["mean_wait"]
        <= 0.95
        * json.loads(
            (Path(r["checkpoint"]).parents[1] / "validation-results" / "10240.json").read_text()
        )["mean_wait"]
        for r in models
    )
    extend = (
        np.mean([r["wait"] for r in models]) <= 0.97 * np.mean([r["wait"] for r in controls])
        or trend >= 2
    )
    atomic_json(
        REPORT / "pilot-decision.json",
        dict(extension_gate_passed=bool(extend), improving_seeds=trend),
    )
    if not qualified(models, references) and extend:
        budget = protocol["extension_budget"]
        train_groups(protocol, limits, budget)
        records = summarize()
        models = [r for r in records if r["group"] == "consequences" and r["budget"] == budget]
    decision = dict(
        status="RUNNING" if qualified(models, references) else "COMPLETED_NEGATIVE",
        budget=budget,
        selected_models=models,
        confirmation_opened=False,
        final_opened=False,
        target_achieved=False,
        reason="bounded development gate failed"
        if not qualified(models, references)
        else "development passed; independent confirmation required",
    )
    atomic_json(REPORT / "decision.json", decision)
    # A successful development candidate must pass unseen confirmation before final data.
    if qualified(models, references):
        policies = dict.fromkeys(POLICIES)
        policies.update({r["id"]: r["checkpoint"] for r in models})
        decision["confirmation_opened"] = True
        atomic_json(REPORT / "decision.json", decision)
        rows = evaluate(protocol["splits"]["confirmation"], policies, "confirmation")
        measured = means(rows)
        atomic_json(REPORT / "confirmation.json", measured)
        checks = [
            dict(
                wait=measured[r["id"]]["mean_wait_s"],
                p95=measured[r["id"]]["p95_wait_s"],
                distance=measured[r["id"]]["distance_floors"],
                feasible=measured[r["id"]]["complete"]
                and all(
                    measured[r["id"]]["p95_wait_s"] <= 1.05 * measured[p]["p95_wait_s"]
                    and measured[r["id"]]["distance_floors"]
                    <= 1.05 * measured[p]["distance_floors"]
                    for p in POLICIES[:3]
                ),
            )
            for r in models
        ]
        if qualified(checks, measured):
            decision["final_opened"] = True
            atomic_json(REPORT / "decision.json", decision)
            final = means(evaluate(protocol["splits"]["final"], policies, "final"))
            atomic_json(REPORT / "final.json", final)
            decision["status"] = "COMPLETED"
            decision["reason"] = (
                "final evaluation complete; report paired uncertainty before any stable-benefit claim"
            )
        else:
            decision["status"] = "COMPLETED_NEGATIVE"
            decision["reason"] = "independent confirmation gate failed"
    atomic_json(REPORT / "decision.json", decision)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "references", "run", "summarize"])
    args = parser.parse_args()
    protocol = prepare()
    if args.stage == "prepare":
        return
    if args.stage == "references":
        result = means(
            evaluate(
                protocol["splits"]["development"], dict.fromkeys(POLICIES), "development-reference"
            )
        )
        atomic_json(REPORT / "references.json", result)
        return
    if args.stage == "summarize":
        summarize()
        return
    run_study(protocol, json.loads((REPORT / "references.json").read_text()))


if __name__ == "__main__":
    main()
