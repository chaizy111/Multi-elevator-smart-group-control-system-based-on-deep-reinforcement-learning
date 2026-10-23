"""Measure full archive wall time and acknowledged controls with a real worker."""

import json
import os
import platform
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from elevator_control.backend.app import create_app
from elevator_control.config.schema import load_config
from elevator_control.controllers.baselines import run_simulation
from elevator_control.evaluation.metrics import calculate
from elevator_control.storage.artifacts import archive, atomic_json
from elevator_control.traffic.trace import generate


def main():
    config = load_config("configs/simulation/performance.yaml")
    start = time.perf_counter()
    sim = run_simulation(config, generate(config))
    path = archive(sim, controller_name="eta", controller_version="eta-v1")
    elapsed = time.perf_counter() - start
    atomic_json(
        Path("reports/full_archive_benchmark.json"),
        dict(
            building="12F4E",
            horizon_s=1800,
            controller="eta",
            passengers=len(sim.trace.records),
            completion_ratio=calculate(sim)["final"]["completion_ratio"],
            wall_seconds=elapsed,
            run_id=path.name,
            includes="trace generation + full physical audit + all CSV/JSON archive",
            target_seconds=30,
            target_passed=elapsed < 30,
        ),
    )
    samples = []
    with TestClient(create_app(Path(".cache/control-measurement"))) as client:
        run = client.post(
            "/api/v1/simulations",
            json=dict(config=config.model_dump(mode="json"), speed_multiplier=20),
        ).json()["run_id"]

        def send(kind, index):
            result = client.post(
                f"/api/v1/simulations/{run}/commands",
                json=dict(type=kind, command_id=f"{kind}-{index}", payload={}),
            )
            assert result.status_code == 200, result.text

        def wait(status):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                job = client.get(f"/api/v1/simulations/{run}").json()
                if job["status"] == status:
                    return job
                if job["status"] == "FAILED":
                    raise AssertionError(job["error"])
                time.sleep(0.01)
            raise TimeoutError(status)

        send("start", 0)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            snap = client.get(f"/api/v1/simulations/{run}/snapshot").json()
            if snap.get("metrics", {}).get("arrived_count", 0) > 0:
                break
            time.sleep(0.02)
        assert snap.get("metrics", {}).get("arrived_count", 0) > 0
        for index in range(5):
            for kind, status in [("pause", "PAUSED"), ("resume", "RUNNING")]:
                start = time.perf_counter()
                send(kind, index)
                wait(status)
                samples.append(
                    dict(command=kind, milliseconds=(time.perf_counter() - start) * 1000)
                )
        send("stop", 0)
        wait("STOPPED")
    values = [s["milliseconds"] for s in samples]
    atomic_json(
        Path("reports/control_latency.json"),
        dict(
            scope="in-process HTTP client with real spawn worker; 10ms status polling, 12F4E normal traffic at20x after actual arrivals",
            samples=samples,
            p95_ms=float(np.percentile(values, 95)),
            max_ms=max(values),
            target_ms=500,
            target_passed=max(values) < 500,
        ),
    )
    benchmark = json.loads(Path("reports/benchmark.json").read_text())
    info = {k: benchmark[k] for k in ["platform", "machine", "cpu", "python"]}
    info.update(
        logical_cpu_count=os.cpu_count(),
        memory_bytes=os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        if hasattr(os, "sysconf")
        else None,
        inference=benchmark["inference"],
        platform_system=platform.system(),
    )
    atomic_json(Path("reports/training_hardware.json"), info)


if __name__ == "__main__":
    main()
