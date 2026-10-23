"""Recompute every archived cohort, costs and distance from raw records."""

import csv
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

import numpy as np

from elevator_control.config.schema import SimulationConfig
from elevator_control.evaluation.metrics import METRICS_VERSION
from elevator_control.simulator.engine import SIMULATOR_VERSION
from elevator_control.storage.artifacts import atomic_json, scenario_hash


def close(a, b):
    if not math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-6):
        raise AssertionError(f"{a} != {b}")


def microseconds(value) -> int:
    return int((Decimal(str(value)) * 1_000_000).to_integral_value())


def audit(path: Path):
    manifest = json.loads((path / "manifest.json").read_text())
    config = SimulationConfig.model_validate(json.loads((path / "config.json").read_text()))
    metrics = json.loads((path / "metrics.json").read_text())
    final = metrics["final"]
    if (
        manifest["simulator_version"] != SIMULATOR_VERSION
        or manifest["metrics_version"] != METRICS_VERSION
    ):
        raise AssertionError(f"incompatible archive {path}")
    trace = (path / "input_trace.csv").read_bytes()
    assert hashlib.sha256(trace).hexdigest() == manifest["trace_hash"]
    assert scenario_hash(config, manifest["trace_hash"]) == manifest["scenario_hash"]
    rows = list(csv.DictReader((path / "passengers.csv").open()))
    assert len(rows) == final["sample_count"]
    waits = []
    rides = []
    wait_cost = 0.0
    ride_cost = 0.0
    fairness = 0.0
    end = microseconds(json.loads((path / "snapshot.json").read_text())["sim_time_s"])
    for row in rows:
        arrival = microseconds(row["arrival_time"])
        assert row["origin_floor"] != row["destination_floor"]
        if row["assigned_time"]:
            assert microseconds(row["assigned_time"]) >= arrival
        pickup = microseconds(row["pickup_time"]) if row["pickup_time"] else None
        finish = microseconds(row["finish_time"]) if row["finish_time"] else None
        age = max(0, (pickup if pickup is not None else end) - arrival) / 1e6
        wait_cost += age
        fairness += (
            max(0, (age - config.reward.long_wait_threshold_s) / config.reward.time_scale_s) ** 2
        )
        if pickup is not None:
            assert pickup >= microseconds(row["assigned_time"])
            waits.append((pickup - arrival) / 1e6)
            ride_cost += ((finish if finish is not None else end) - pickup) / 1e6
        if finish is not None:
            assert pickup is not None and finish >= pickup
            rides.append((finish - pickup) / 1e6)
    if waits:
        close(float(np.mean(waits)), final["mean_wait_s"])
        close(float(np.percentile(waits, 95, method="linear")), final["p95_wait_s"])
        close(max(waits), final["max_wait_s"])
        close(
            sum(w > config.metrics.long_wait_threshold_s for w in waits) / len(waits),
            final["long_wait_ratio"],
        )
    else:
        assert final["mean_wait_s"] is None
    if rides:
        close(float(np.mean(rides)), final["mean_travel_s"])
    finished_rows = [r for r in rows if r["finish_time"]]
    n = len(rows)
    close(len(finished_rows) / n if n else 1, final["completion_ratio"])
    horizon = config.simulation.arrival_horizon_s
    done_h = sum(microseconds(r["finish_time"]) <= microseconds(horizon) for r in finished_rows)
    close(done_h / (horizon / 60), final["throughput_per_min"])
    close(done_h / n if n else 1, metrics["at_horizon"]["completion_ratio"])
    if finished_rows:
        close(
            float(
                np.mean(
                    [
                        (microseconds(r["finish_time"]) - microseconds(r["arrival_time"])) / 1e6
                        for r in finished_rows
                    ]
                )
            ),
            final["mean_system_time_s"],
        )
    if n:
        close(wait_cost / n, final["censored_mean_wait_lower_bound_s"])
    for floor, value in final["floor_fairness"].items():
        subset = [
            float(r["waiting_time"])
            for r in rows
            if r["origin_floor"] == floor and r["waiting_time"]
        ]
        assert value["count"] == len(subset)
        if subset:
            close(float(np.mean(subset)), value["mean_wait_s"])
        else:
            assert value["mean_wait_s"] is None
    close(wait_cost, final["costs"]["wait"])
    close(ride_cost, final["costs"]["ride"])
    close(fairness, final["costs"]["fairness"])
    close(
        final["distance_floors"], final["empty_distance_floors"] + final["loaded_distance_floors"]
    )
    ph = config.physics
    close(
        final["energy_proxy"],
        final["empty_distance_floors"] * ph.empty_distance_weight
        + final["loaded_distance_floors"] * ph.loaded_distance_weight
        + final["door_cycles"] * ph.door_cycle_weight
        + final["starts"] * ph.start_weight,
    )
    last = {}
    with (path / "elevator_trace.csv").open() as stream:
        for row in csv.DictReader(stream):
            last[row["elevator_id"]] = float(row["distance_floors"])
    close(sum(last.values()), final["distance_floors"])
    assert len(final["floor_fairness"]) == config.building.floor_count
    return len(rows)


def main():
    total = passengers = 0
    matrices = {}
    for name in ["standard", "mixed", "generalization", "ablation", "pressure"]:
        folder = Path("artifacts/experiments") / name
        records = list(csv.DictReader((folder / "runs.csv").open()))
        count = 0
        for row in records:
            passengers += audit(folder / "runs" / row["run_id"])
            total += 1
            count += 1
        matrices[name] = count
        print(f"audited {name}: {count}", flush=True)
    result = dict(
        status="PASSED",
        runs=total,
        passengers=passengers,
        matrices=matrices,
        checks=[
            "trace SHA256",
            "version/scenario identity",
            "lifecycle timestamps",
            "mean/P95/max wait",
            "mean ride",
            "cost integral conservation",
            "fairness quadratic increments",
            "energy composition",
            "distance from elevator CSV",
            "all floor fairness entries",
        ],
    )
    atomic_json(Path("reports/formal/raw_audit.json"), result)


if __name__ == "__main__":
    main()
