import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def test_cross_process_hash_seed_does_not_change_cost_accumulation(tmp_path):
    config = {
        "building": {"floor_count": 5, "elevator_count": 1, "capacity": 2},
        "simulation": {"arrival_horizon_s": 1, "max_drain_s": 1000},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    trace = tmp_path / "input.csv"
    trace.write_text(
        "passenger_id,arrival_time,origin_floor,destination_floor\n"
        + "".join(f"P{i},0,1,5\n" for i in range(12))
    )
    results = []
    # Drive the real kernel in fresh interpreters with deliberately different hash orders.
    code = """import json,sys
from elevator_control.config.schema import load_config
from elevator_control.traffic.trace import TrafficTrace
from elevator_control.controllers.baselines import run_simulation
cfg=load_config(sys.argv[1]); sim=run_simulation(cfg,TrafficTrace.load(sys.argv[2],cfg))
print(json.dumps(sim.summary(),sort_keys=True))"""
    for seed in ["1", "9"]:
        env = {
            **os.environ,
            "PYTHONPATH": str(Path("src").resolve()),
            "PYTHONHASHSEED": seed,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        value = subprocess.run(
            [sys.executable, "-c", code, str(path), str(trace)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        results.append(json.loads(value.stdout))
    assert results[0] == results[1]
    assert results[0]["costs"]["fairness"] > 0
