"""Measured CPU performance, including route features; controlled long-run stability."""

import platform
import time
from pathlib import Path

import numpy as np

from elevator_control.config.schema import SimulationConfig
from elevator_control.controllers.baselines import Baseline, run_simulation
from elevator_control.domain.models import us
from elevator_control.evaluation.metrics import calculate
from elevator_control.storage.artifacts import atomic_json
from elevator_control.traffic.trace import Record, TrafficTrace, generate


def benchmark(
    config: SimulationConfig,
    *,
    requests: int | None = None,
    model_id="ppo-curriculum",
    output="reports/benchmark.json",
) -> dict:
    cfg = config.model_copy(deep=True)
    if requests is not None:
        if not 1 <= requests <= 100000:
            raise ValueError("requests must be 1..100000")
        cfg.simulation.arrival_horizon_s = max(cfg.simulation.arrival_horizon_s, requests * 8.0)
        cfg.simulation.max_passengers = max(cfg.simulation.max_passengers, requests)
        rng = np.random.default_rng(cfg.seed)
        records = []
        for i in range(requests):
            origin, destination = rng.choice(
                np.arange(1, cfg.building.floor_count + 1), size=2, replace=False
            )
            records.append(Record(f"P{i:07d}", us(i * 8.0), int(origin), int(destination)))
        trace = TrafficTrace(tuple(records), cfg.seed, "controlled-long-run", "controlled-8s-v1")
    else:
        trace = generate(cfg)
    latencies = []
    start = time.perf_counter()
    sim = run_simulation(
        cfg, trace, Baseline("eta"), audit=False, on_timing=lambda kind, ms: latencies.append(ms)
    )
    wall = time.perf_counter() - start
    result = dict(
        schema_version=1,
        platform=platform.platform(),
        machine=platform.machine(),
        cpu=platform.processor(),
        python=platform.python_version(),
        controller="eta",
        passengers=len(trace.records),
        simulated_seconds=sim.now / 1e6,
        wall_seconds=wall,
        events=sim.processed_events,
        decisions=sim.decision_sequence,
        decisions_per_second=sim.decision_sequence / max(wall, 1e-9),
        total_decision_ms_p50=float(np.percentile(latencies, 50)) if latencies else None,
        total_decision_ms_p95=float(np.percentile(latencies, 95)) if latencies else None,
        metrics=calculate(sim),
        scope="route proposals + public view + action commit; physics separately included in total wall time",
        stress_note="controlled 8-second spacing long-run stability, not overload throughput"
        if requests
        else "configured stochastic trace",
        inference=None,
    )
    model_path = Path("artifacts/models") / model_id
    if model_path.exists():
        import torch

        from elevator_control.env.environment import ElevatorEnv
        from elevator_control.rl.checkpoint import load_model
        from elevator_control.rl.network import tensor_observations

        torch.set_num_threads(1)
        model, metadata = load_model(model_id)
        obs, _ = ElevatorEnv(config).reset(seed=cfg.seed)
        tensor = tensor_observations(obs)
        samples = []
        with torch.no_grad():
            for _ in range(20):
                model(tensor)
            for _ in range(200):
                start = time.perf_counter()
                model(tensor)
                samples.append((time.perf_counter() - start) * 1000)
        result["inference"] = dict(
            model_id=model_id,
            model_hash=metadata["sha256"],
            torch=str(torch.__version__),
            device="cpu",
            threads=1,
            p50_ms=float(np.percentile(samples, 50)),
            p95_ms=float(np.percentile(samples, 95)),
            scope="batch1 network only; excludes route and observation",
        )
    atomic_json(Path(output), result)
    return result
