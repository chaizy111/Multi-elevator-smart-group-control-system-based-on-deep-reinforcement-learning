"""Short real chain using the current trusted model; no fabricated results or hidden full training."""

import json
from pathlib import Path

from elevator_control.config.schema import ControllerConfig, load_config
from elevator_control.controllers.baselines import Baseline, run_simulation
from elevator_control.controllers.rl_controller import RLController
from elevator_control.evaluation.metrics import calculate
from elevator_control.storage.artifacts import archive, atomic_json
from elevator_control.storage.indexing import index_run
from elevator_control.traffic.trace import TrafficTrace, generate


def main():
    config = load_config("configs/simulation/small.yaml")
    trace = generate(config)
    trace.save("data/traces/acceptance.csv")
    reloaded = TrafficTrace.load("data/traces/acceptance.csv", config)
    assert trace.bytes() == reloaded.bytes()
    rows = []
    for name, controller in [
        ("round_robin", Baseline("round_robin")),
        ("eta", Baseline("eta")),
        ("eta_zone", Baseline("eta_zone")),
        ("ppo", RLController("ppo-curriculum")),
    ]:
        run_config = config.model_copy(deep=True)
        run_config.controller = ControllerConfig.model_validate(
            dict(name=name, model_id="ppo-curriculum" if name == "ppo" else None)
        )
        sim = run_simulation(run_config, reloaded, controller)
        metrics = calculate(sim)
        assert metrics["final"]["completion_ratio"] == 1
        assert metrics["final"]["sample_count"] == len(trace.records)
        path = archive(
            sim,
            controller_name=name,
            model_hash=getattr(controller, "model_hash", None),
            controller_version=getattr(controller, "version", None),
        )
        index_run(path)
        rows.append(
            dict(
                controller=name, trace_hash=trace.sha256, run_id=path.name, metrics=metrics["final"]
            )
        )
    atomic_json(Path("reports/acceptance_smoke.json"), dict(status="PASSED", runs=rows))
    print(json.dumps(dict(status="PASSED", report="reports/acceptance_smoke.json"), indent=2))


if __name__ == "__main__":
    main()
