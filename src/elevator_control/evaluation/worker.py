"""Independent evaluation cells for spawn pools; only the parent writes the run index."""

import json
from pathlib import Path

from elevator_control.config.schema import ControllerConfig, SimulationConfig
from elevator_control.controllers.baselines import Baseline, run_simulation
from elevator_control.evaluation.metrics import calculate
from elevator_control.storage.artifacts import archive, atomic_json

_CONTROLLERS = {}


def execute_cell(task: dict) -> dict:
    path = Path(task["path"])
    try:
        policy = task["policy"]
        cache = (str(Path(task["model_root"]).resolve()), policy, task["model_hash"])
        if cache not in _CONTROLLERS:
            if policy.startswith(("ppo:", "ppo_stay:")):
                from elevator_control.controllers.rl_controller import RLController

                _CONTROLLERS[cache] = RLController(
                    policy.split(":", 1)[1],
                    root=task["model_root"],
                    force_stay=policy.startswith("ppo_stay:"),
                )
            else:
                _CONTROLLERS[cache] = Baseline(policy)
        controller = _CONTROLLERS[cache]
        saved = (
            json.loads((path / "manifest.json").read_text())
            if (path / "manifest.json").exists()
            else {}
        )
        reusable = (
            task["resume"]
            and saved.get("status") == "COMPLETED"
            and saved.get("scenario_hash") == task["scenario_hash"]
            and saved.get("controller") == policy
            and saved.get("model_hash") == task["model_hash"]
        )
        if reusable:
            metrics = json.loads((path / "metrics.json").read_text())
        else:
            config = SimulationConfig.model_validate(task["config"])
            config.controller = ControllerConfig.model_validate(
                dict(
                    name="ppo" if ":" in policy else policy,
                    model_id=policy.split(":", 1)[1] if ":" in policy else None,
                )
            )
            sim = run_simulation(config, task["trace"], controller)
            archive(
                sim,
                path.parent,
                run_id=path.name,
                controller_name=policy,
                model_hash=task["model_hash"],
                controller_version=task.get("controller_version"),
            )
            metrics = calculate(sim)
        row = dict(
            scenario=task["scenario"],
            seed=task["seed"],
            trace_hash=task["trace"].sha256,
            controller=policy,
            run_id=path.name,
            **{k: v for k, v in metrics["final"].items() if not isinstance(v, dict)},
        )
        return dict(row=row, manifest=json.loads((path / "manifest.json").read_text()), error=None)
    except Exception as error:
        failure = dict(
            scenario=task["scenario"],
            seed=task["seed"],
            trace_hash=task["trace"].sha256,
            controller=task["policy"],
            run_id=path.name,
            error_type=type(error).__name__,
            message=str(error),
        )
        atomic_json(path / "failure.json", failure)
        return dict(row=None, manifest=None, error=failure)
