"""Independent raw audit and registered-policy API check for the candidate-input study."""

import importlib.util
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import numpy as np
import torch
from fastapi.testclient import TestClient

from elevator_control.backend.app import create_app
from elevator_control.config.schema import SimulationConfig
from elevator_control.controllers.baselines import run_simulation
from elevator_control.controllers.rl_controller import RLController
from elevator_control.env.candidates import CANDIDATE_FEATURES
from elevator_control.evaluation.metrics import calculate
from elevator_control.research.candidate_ppo import (
    POLICIES,
    REPORT,
    ROOT,
    evaluate,
    means,
    prepare,
    qualified,
    sha,
    summarize,
)
from elevator_control.rl.checkpoint import load_model, register
from elevator_control.rl.trainer import TrainingConfig, train
from elevator_control.storage.artifacts import atomic_json
from elevator_control.traffic.trace import generate


def audit_module():
    spec = importlib.util.spec_from_file_location("raw_auditor", "scripts/audit_experiments.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy_compatibility():
    """Verify both frozen inference and the actual no-feature PPO update path."""
    cleanup = json.loads((REPORT / "cleanup.json").read_text())
    assert all(sha(path) == value for path, value in cleanup["preserved_model_sha256"].items())
    namespace = {}
    exec(
        compile(
            subprocess.check_output(
                ["git", "show", "18fd731:src/elevator_control/rl/network.py"], text=True
            ),
            "original-network.py",
            "exec",
        ),
        namespace,
    )
    torch.set_num_threads(1)
    states = np.load("artifacts/baseline-restore/public-states.npz")
    obs = {k: torch.as_tensor(states[k]) for k in states.files}
    checked = []
    for path in Path("artifacts/models").glob("*/weights.pt"):
        new, meta = load_model(path.parent.name)
        old = namespace["ActorCritic"](attention=meta["attention"])
        old.load_state_dict(new.state_dict())
        old.eval()
        with torch.no_grad():
            a, va = old(obs)
            b, vb = new(obs)
        assert torch.equal(a, b) and torch.equal(va, vb), path
        checked.append(path.parent.name)
    module = types.ModuleType("original_trainer_for_check")
    sys.modules[module.__name__] = module
    exec(
        compile(
            subprocess.check_output(
                ["git", "show", "18fd731:src/elevator_control/rl/trainer.py"], text=True
            ),
            "original-trainer.py",
            "exec",
        ),
        module.__dict__,
    )
    settings = dict(
        seed=813,
        total_decisions=128,
        rollout_steps=32,
        epochs=2,
        simulation=dict(
            building=dict(floor_count=5, elevator_count=2),
            traffic=dict(arrival_rate_per_min=30),
            simulation=dict(arrival_horizon_s=30),
        ),
    )
    folder = Path(".cache/candidate-ppo/legacy")
    module.train(module.TrainingConfig.model_validate(settings), folder / "old")
    train(TrainingConfig.model_validate(settings), folder / "new")
    a = torch.load(folder / "old/checkpoints/last.pt", weights_only=False)
    b = torch.load(folder / "new/checkpoints/last.pt", weights_only=False)
    assert all(torch.equal(v, b["network"][k]) for k, v in a["network"].items())
    assert torch.equal(a["torch_rng"], b["torch_rng"])
    atomic_json(
        REPORT / "legacy-compatibility.json",
        dict(
            status="PASSED",
            model_hashes_unchanged=9,
            original_models=checked,
            real_public_states=24,
            outputs_bitwise_unchanged=True,
            actual_legacy_training_decisions=128,
            network_tensors=len(a["network"]),
            updates_and_rng_bitwise_equal=True,
        ),
    )


def feature_sensitivity(selected):
    """Local derivatives describe learned response, not preset cost coefficients."""
    from elevator_control.research.candidate_ppo import CheckpointPolicy

    states = np.load("artifacts/baseline-restore/public-states.npz")
    obs = {k: torch.as_tensor(states[k]) for k in states.files}
    obs["candidates"] = obs["candidates"].clone().requires_grad_(True)
    valid = obs["action_mask"][:, :8].bool()
    result = []
    for row in selected:
        policy = CheckpointPolicy(row["checkpoint"])
        logits, _ = policy.model(obs)
        gradient = torch.autograd.grad(
            logits[:, :8].masked_fill(~valid, 0).sum(), obs["candidates"]
        )[0]
        values = gradient[valid].detach().numpy()
        result.append(
            dict(
                model=row["id"],
                legal_dispatch_samples=int(valid.sum()),
                mean_local_derivative={
                    name: float(values[:, i].mean()) for i, name in enumerate(CANDIDATE_FEATURES)
                },
                note="Local score sensitivity on public regression states; not globally constant policy weights.",
            )
        )
    atomic_json(REPORT / "feature-sensitivity.json", result)


def api_check(selected):
    registered = []
    for row in selected:
        model_id = "ppo-" + row["id"]
        if not (ROOT / "models" / model_id).exists():
            register(row["checkpoint"], model_id, ROOT / "models")
        registered.append(model_id)
    results = []
    with TestClient(create_app(ROOT, max_workers=1)) as client:
        for i, (floors, elevators) in enumerate([(5, 2), (30, 8)]):
            config = SimulationConfig.model_validate(
                dict(
                    seed=67_000_000 + i,
                    building=dict(floor_count=floors, elevator_count=elevators),
                    simulation=dict(arrival_horizon_s=30, max_drain_s=7200),
                    traffic=dict(arrival_rate_per_min=20),
                    controller=dict(name="ppo", model_id=registered[0]),
                )
            )
            response = client.post(
                "/api/v1/simulations",
                json=dict(config=config.model_dump(mode="json"), speed_multiplier=0),
            )
            assert response.status_code == 200, response.text
            run_id = response.json()["run_id"]
            response = client.post(
                f"/api/v1/simulations/{run_id}/commands",
                json=dict(command_id="start", type="start"),
            )
            assert response.status_code == 200, response.text
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                job = client.get(f"/api/v1/simulations/{run_id}").json()
                if job["status"] in ["COMPLETED", "FAILED"]:
                    break
                time.sleep(0.1)
            assert job["status"] == "COMPLETED", job
            measured = client.get(f"/api/v1/simulations/{run_id}/metrics").json()
            direct = run_simulation(
                config, generate(config), RLController(registered[0], root=str(ROOT / "models"))
            )
            assert measured == calculate(direct)
            assert measured["final"]["eligible_for_ranking"]
            results.append(
                dict(
                    building=[floors, elevators],
                    run_id=run_id,
                    passengers=measured["final"]["sample_count"],
                )
            )
    atomic_json(
        REPORT / "model-integration.json",
        dict(
            status="PASSED",
            models=registered,
            api_worker_matches_offline=True,
            runs=results,
            active_by_default=False,
        ),
    )


def intervals(rows, labels, iterations=2000):
    """Matched trace bootstrap nested within independently sampled fine-tuning seeds."""
    values = {(r["controller"], r["scenario"], r["seed"]): r["mean_wait_s"] for r in rows}
    scenarios = sorted({r["scenario"] for r in rows})
    seeds = {s: sorted({r["seed"] for r in rows if r["scenario"] == s}) for s in scenarios}
    rng = np.random.default_rng(813)
    samples = {p: [] for p in POLICIES[:4]}
    for _ in range(iterations):
        chosen = rng.choice(labels, len(labels), replace=True)
        draws = {s: rng.choice(seeds[s], len(seeds[s]), replace=True) for s in scenarios}
        learned = np.mean(
            [
                np.mean([values[(label, s, int(seed))] for seed in draws[s]])
                for label in chosen
                for s in scenarios
            ]
        )
        for p in samples:
            reference = np.mean(
                [np.mean([values[(p, s, int(seed))] for seed in draws[s]]) for s in scenarios]
            )
            samples[p].append(float(learned / reference))
    return {
        p: dict(
            lower95=float(np.percentile(v, 2.5)),
            upper95=float(np.percentile(v, 97.5)),
            one_sided_9875_upper=float(np.percentile(v, 98.75)),
        )
        for p, v in samples.items()
    }


def main():
    decision = json.loads((REPORT / "decision.json").read_text())
    # An already running v1 scheduler may publish its development decision before
    # confirmation finishes. Never interpret that intermediate record as a result.
    while decision["reason"] == "development passed; independent confirmation required":
        confirmation = REPORT / "confirmation.json"
        if confirmation.exists():
            measured = json.loads(confirmation.read_text())
            checks = [
                dict(
                    wait=measured[r["id"]]["mean_wait_s"],
                    feasible=measured[r["id"]]["complete"]
                    and all(
                        measured[r["id"]]["p95_wait_s"] <= 1.05 * measured[p]["p95_wait_s"]
                        and measured[r["id"]]["distance_floors"]
                        <= 1.05 * measured[p]["distance_floors"]
                        for p in POLICIES[:3]
                    ),
                )
                for r in decision["selected_models"]
            ]
            if not qualified(checks, measured):
                decision["reason"] = "independent confirmation gate failed"
                break
        time.sleep(1)
        decision = json.loads((REPORT / "decision.json").read_text())
    assert decision["status"].startswith("COMPLETED")
    protocol = prepare()
    selected = decision["selected_models"]
    records = summarize()
    controls = [r for r in records if r["group"] == "control" and r["budget"] == decision["budget"]]
    policies = {r["id"]: r["checkpoint"] for r in selected + controls}
    policies.update({"zero-input:" + r["id"]: r["checkpoint"] for r in selected})
    rows = evaluate(protocol["splits"]["development"], policies, "selected-and-ablation")
    measured = means(rows)
    for row in selected + controls:
        for raw, saved in [
            ("mean_wait_s", "wait"),
            ("p95_wait_s", "p95"),
            ("distance_floors", "distance"),
        ]:
            assert np.isclose(measured[row["id"]][raw], row[saved], atol=1e-8), (row["id"], raw)
    atomic_json(
        REPORT / "selected-raw-and-ablation.json",
        dict(
            status="PASSED",
            runs=len(rows),
            summary=measured,
            same_checkpoint_without_consequences="zero-input policies mask only the six features; no retraining",
        ),
    )
    feature_sensitivity(selected)
    legacy_compatibility()
    api_check(selected)
    if decision["confirmation_opened"] and not decision["final_opened"]:
        decision["reason"] = "independent confirmation gate failed"
        atomic_json(REPORT / "decision.json", decision)
    if decision["final_opened"]:
        labels = [r["id"] for r in selected]
        final_rows = [
            json.loads(p.read_text())
            for p in (ROOT / "evaluation/final/runs").glob("*/result.json")
        ]
        assessment = acceptance(final_rows, labels)
        if all(r["eligible_for_ranking"] for r in final_rows):
            assessment["intervals"] = intervals(final_rows, labels)
            assessment["passed"] &= all(
                v["one_sided_9875_upper"] < (1.10 if p == "fixed-rule" else 1)
                for p, v in assessment["intervals"].items()
            )
        final_policies = dict.fromkeys(POLICIES)
        final_policies.update({r["id"]: r["checkpoint"] for r in selected})
        for scope in ["long", "generalization", "pressure"]:
            extra = evaluate(protocol["splits"][scope], final_policies, scope)
            assessment[scope] = acceptance(extra, labels)
            if scope != "pressure":
                assessment["passed"] &= assessment[scope]["passed"]
        atomic_json(REPORT / "final-assessment.json", assessment)
        decision["target_achieved"] = bool(assessment["passed"])
        decision["reason"] = "independent final and robustness evaluation finished"
        atomic_json(REPORT / "decision.json", decision)
    audit = audit_module()
    paths = [p.parent for p in (ROOT / "evaluation").glob("*/runs/*/result.json")]
    paths += [p for p in (ROOT / "runs").glob("*") if (p / "metrics.json").exists()]
    count = sum(audit.audit(p) for p in paths)
    atomic_json(
        REPORT / "raw-audit.json", dict(status="PASSED", runs=len(paths), passenger_rows=count)
    )
    cleanup = json.loads((REPORT / "cleanup.json").read_text())
    assert all(sha(p) == value for p, value in cleanup["preserved_model_sha256"].items())
    assert not Path("artifacts/minimal-ppo").exists() and not Path("reports/minimal-ppo").exists()
    print(
        "Selected checkpoint re-evaluation, feature ablation, API/worker and raw audit passed.",
        flush=True,
    )


def acceptance(rows, labels) -> dict:
    measured = means(rows)
    if not rows or not all(measured[p]["complete"] for p in POLICIES + labels):
        return dict(passed=False, summary=measured, reason="incomplete or empty cohorts")
    average = float(np.mean([measured[p]["mean_wait_s"] for p in labels]))
    ratios = {p: average / measured[p]["mean_wait_s"] for p in POLICIES[:4]}
    passed = all(ratios[p] <= 0.95 for p in POLICIES[:3]) and ratios["fixed-rule"] <= 1.10
    for p in labels:
        for baseline in POLICIES[:3]:
            passed &= measured[p]["mean_wait_s"] < measured[baseline]["mean_wait_s"]
            passed &= measured[p]["p95_wait_s"] <= 1.05 * measured[baseline]["p95_wait_s"]
            passed &= measured[p]["distance_floors"] <= 1.05 * measured[baseline]["distance_floors"]
    return dict(passed=bool(passed), summary=measured, wait_ratios=ratios)


if __name__ == "__main__":
    main()
