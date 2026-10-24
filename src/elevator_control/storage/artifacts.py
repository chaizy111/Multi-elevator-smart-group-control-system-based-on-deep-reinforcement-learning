"""Atomic manifests and explicit archive schemas; raw traces are never mutated."""

import csv
import json
import platform
import uuid
from collections.abc import Iterable
from itertools import chain
from pathlib import Path

from elevator_control.config.schema import canonical_hash
from elevator_control.evaluation.metrics import METRICS_VERSION, calculate
from elevator_control.simulator.engine import SIMULATOR_VERSION, Simulator
from elevator_control.simulator.route_planner import ROUTE_VERSION


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    temp.replace(path)


def write_csv(path: Path, rows: Iterable[dict], fields: list[str] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    iterator = iter(rows)
    first = next(iterator, None)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields or (list(first) if first is not None else []),
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(chain([first] if first is not None else [], iterator))
    temporary.replace(path)


def scenario_hash(config, trace_hash: str) -> str:
    value = config.model_dump(mode="json")
    value.pop("controller")
    value["simulation"].pop("snapshot_interval_s")
    return canonical_hash(
        dict(
            config=value,
            trace_hash=trace_hash,
            simulator=SIMULATOR_VERSION,
            route=ROUTE_VERSION,
            metrics=METRICS_VERSION,
        )
    )


def passenger_rows(sim: Simulator) -> list[dict]:
    rows = []
    for p in sim.passengers.values():
        pick = p.pickup_us
        finish = p.finish_us
        rows.append(
            dict(
                passenger_id=p.id,
                arrival_time=p.arrival_us / 1e6,
                origin_floor=p.origin,
                destination_floor=p.destination,
                status=p.status.value,
                assigned_elevator=f"E{p.assigned_elevator + 1}"
                if p.assigned_elevator is not None
                else None,
                assigned_time=p.assigned_us / 1e6 if p.assigned_us is not None else None,
                pickup_time=pick / 1e6 if pick is not None else None,
                finish_time=finish / 1e6 if finish is not None else None,
                waiting_time=(pick - p.arrival_us) / 1e6 if pick is not None else None,
                travel_time=(finish - pick) / 1e6
                if finish is not None and pick is not None
                else None,
                system_time=(finish - p.arrival_us) / 1e6 if finish is not None else None,
                censored_wait_age=(sim.now - p.arrival_us) / 1e6
                if pick is None and p.arrival_us <= sim.now
                else None,
            )
        )
    return rows


def archive(
    sim: Simulator,
    root: str | Path | None = None,
    *,
    run_id: str | None = None,
    controller_name: str | None = None,
    model_hash: str | None = None,
    controller_version: str | None = None,
) -> Path:
    from elevator_control.storage.paths import artifact_root

    root = root if root is not None else artifact_root() / "runs"
    path = Path(root) / (run_id or ("run-" + uuid.uuid4().hex[:12]))
    path.mkdir(parents=True, exist_ok=True)
    config = sim.config.model_dump(mode="json")
    manifest = dict(
        schema_version=1,
        run_id=path.name,
        status="RUNNING",
        simulator_version=SIMULATOR_VERSION,
        route_version=ROUTE_VERSION,
        metrics_version=METRICS_VERSION,
        config_hash=canonical_hash(sim.config),
        trace_hash=sim.trace.sha256,
        generator_version=sim.trace.generator_version,
        scenario_hash=scenario_hash(sim.config, sim.trace.sha256),
        controller=controller_name or sim.config.controller.name,
        model_hash=model_hash,
        controller_version=controller_version,
        python=platform.python_version(),
    )
    atomic_json(path / "manifest.json", manifest)
    atomic_json(path / "config.json", config)
    (path / "input_trace.csv").write_bytes(sim.trace.bytes())
    write_csv(
        path / "passengers.csv",
        passenger_rows(sim),
        [
            "passenger_id",
            "arrival_time",
            "origin_floor",
            "destination_floor",
            "status",
            "assigned_elevator",
            "assigned_time",
            "pickup_time",
            "finish_time",
            "waiting_time",
            "travel_time",
            "system_time",
            "censored_wait_age",
        ],
    )
    extra_snapshot = (
        [sim.snapshot()]
        if not sim.snapshots or sim.snapshots[-1]["sim_time_s"] != sim.now / 1e6
        else []
    )

    def snapshots():
        return chain(sim.snapshots, extra_snapshot)

    write_csv(
        path / "elevator_trace.csv",
        (
            dict(
                timestamp=s["sim_time_s"],
                elevator_id=e["id"],
                position_floor=e["position_floor"],
                at_floor=e["at_floor"],
                direction=e["direction"],
                load=e["load"],
                target=e["target_floor"],
                phase=e["phase"],
                purpose=e["purpose"],
                distance_floors=e["distance_floors"],
            )
            for s in snapshots()
            for e in s["elevators"]
        ),
    )
    write_csv(
        path / "metrics_timeseries.csv",
        (dict(timestamp=s["sim_time_s"], **s["metrics"]) for s in snapshots()),
    )
    for name, rows in [("decisions", sim.decisions), ("events", sim.event_log)]:
        with (path / f"{name}.jsonl").open("w") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    atomic_json(path / "metrics.json", calculate(sim))
    (path / "run.log").write_text(
        f"run_id={path.name} simulation_time={sim.now / 1e6} reason={sim.reason}\n"
    )
    atomic_json(path / "snapshot.json", sim.snapshot())
    manifest["status"] = "COMPLETED" if sim.reason == "completed" else "STOPPED"
    manifest["termination_reason"] = sim.reason
    atomic_json(path / "manifest.json", manifest)
    return path
