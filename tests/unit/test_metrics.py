import csv
import json

import pytest

from elevator_control.config.schema import SimulationConfig
from elevator_control.controllers.baselines import run_simulation
from elevator_control.evaluation.metrics import calculate
from elevator_control.evaluation.suite import paired_bootstrap, verify_comparable
from elevator_control.storage.artifacts import archive
from elevator_control.traffic.trace import Record, TrafficTrace


def test_archive_recompute_and_horizon(tmp_path):
    cfg = SimulationConfig.model_validate(
        {"simulation": {"arrival_horizon_s": 10, "max_drain_s": 100}}
    )
    sim = run_simulation(cfg, TrafficTrace((Record("P", 9999999, 1, 3),)))
    path = archive(sim, tmp_path)
    metrics = json.loads((path / "metrics.json").read_text())
    row = list(csv.DictReader((path / "passengers.csv").open()))[0]
    assert metrics["final"]["mean_wait_s"] == pytest.approx(
        float(row["pickup_time"]) - float(row["arrival_time"])
    )
    assert metrics["at_horizon"]["completed_count"] == 0
    assert metrics["final"]["completion_ratio"] == 1
    assert (path / "input_trace.csv").read_bytes() == sim.trace.bytes()


def test_censored_and_empty():
    cfg = SimulationConfig.model_validate(
        {"simulation": {"arrival_horizon_s": 1, "max_drain_s": 0}}
    )
    sim = run_simulation(cfg, TrafficTrace((Record("P", 0, 12, 1),)))
    m = calculate(sim)["final"]
    assert m["mean_wait_s"] is None
    assert m["conditional_wait"]
    assert not m["eligible_for_ranking"]
    assert m["censored_mean_wait_lower_bound_s"] == 1
    empty = run_simulation(cfg, TrafficTrace(()))
    assert calculate(empty)["final"]["completion_ratio"] == 1
    assert calculate(empty)["final"]["mean_wait_s"] is None


def test_bootstrap_and_comparison():
    assert paired_bootstrap([2, 2, 2]) == (2, 2)
    with pytest.raises(ValueError):
        verify_comparable([{"scenario_hash": "a"}, {"scenario_hash": "b"}])


def test_snapshot_frequency_independence():
    a = SimulationConfig.model_validate(
        {"simulation": {"arrival_horizon_s": 60, "snapshot_interval_s": 1}}
    )
    b = a.model_copy(deep=True)
    b.simulation.snapshot_interval_s = 0.37
    trace = TrafficTrace((Record("P", 1000001, 5, 1), Record("Q", 19000001, 1, 4)))
    x, y = run_simulation(a, trace), run_simulation(b, trace)
    assert [{k: v for k, v in d.items() if k != "inference_ms"} for d in x.decisions] == [
        {k: v for k, v in d.items() if k != "inference_ms"} for d in y.decisions
    ]
    assert x.costs == pytest.approx(y.costs)
    assert calculate(x)["final"]["mean_wait_s"] == calculate(y)["final"]["mean_wait_s"]
