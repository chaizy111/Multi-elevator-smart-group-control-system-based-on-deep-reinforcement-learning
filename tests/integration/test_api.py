import time
from pathlib import Path

from fastapi.testclient import TestClient

from elevator_control.backend.app import create_app
from elevator_control.config.schema import SimulationConfig
from elevator_control.controllers.baselines import run_simulation
from elevator_control.evaluation.metrics import calculate
from elevator_control.storage.repository import Repository
from elevator_control.traffic.trace import generate

CONFIG = {
    "building": {"floor_count": 5, "elevator_count": 2, "capacity": 6},
    "simulation": {"arrival_horizon_s": 10, "max_drain_s": 100},
    "traffic": {"arrival_rate_per_min": 30},
}


def wait_for(client, id, statuses, timeout=15):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        job = client.get(f"/api/v1/simulations/{id}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting {statuses}: {job}")


def command(client, id, kind, command_id=None, payload=None):
    return client.post(
        f"/api/v1/simulations/{id}/commands",
        json={"command_id": command_id or kind, "type": kind, "payload": payload or {}},
    )


def test_worker_pause_resume_reset_archive(tmp_path):
    app = create_app(tmp_path / "artifacts", max_workers=1)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["ready"]
        response = client.post(
            "/api/v1/simulations", json={"config": CONFIG, "speed_multiplier": 1}
        )
        assert response.status_code == 200, response.text
        id = response.json()["run_id"]
        assert command(client, id, "start").status_code == 200
        wait_for(client, id, {"RUNNING"})
        result = command(client, id, "pause", "pause-1")
        assert result.status_code == 200, result.text
        assert command(client, id, "pause", "pause-1").json() == result.json()
        assert command(client, id, "resume", "pause-1").status_code == 409
        wait_for(client, id, {"PAUSED"})
        time.sleep(0.15)
        first = client.get(f"/api/v1/simulations/{id}/snapshot").json()["sim_time_s"]
        time.sleep(0.15)
        assert client.get(f"/api/v1/simulations/{id}/snapshot").json()["sim_time_s"] == first
        with client.websocket_connect(f"/ws/v1/simulations/{id}") as socket:
            message = socket.receive_json()
            assert message["status"] == "PAUSED"
            assert len(message["elevators"]) == 2
        assert command(client, id, "resume").status_code == 200
        assert command(client, id, "speed", payload={"speed_multiplier": 0}).status_code == 200
        job = wait_for(client, id, {"COMPLETED", "FAILED"})
        assert job["status"] == "COMPLETED", job
        metrics = client.get(f"/api/v1/simulations/{id}/metrics").json()
        cfg = SimulationConfig.model_validate(CONFIG)
        direct = run_simulation(cfg, generate(cfg))
        assert metrics == calculate(direct)
        series = client.get(f"/api/v1/simulations/{id}/timeseries?limit=5").json()
        assert series["available"] and len(series["items"]) == 5
        assert series["items"][0] == dict(time=0, wait=None)
        assert series["items"][-1]["time"] == direct.now / 1e6
        assert series["items"][-1]["wait"] == metrics["final"]["mean_wait_s"]
        assert series["total"] > len(series["items"])
        rows = client.get(f"/api/v1/simulations/{id}/passengers?limit=2").json()
        assert rows["available"] and len(rows["items"]) <= 2
        artifacts = client.get(f"/api/v1/simulations/{id}/artifacts").json()["items"]
        item = next(x for x in artifacts if x["name"] == "metrics.json")
        assert client.get(item["url"]).json() == metrics
        reset = command(client, id, "reset").json()
        assert reset["new_run_id"] != id
        assert Path(tmp_path / "artifacts" / "runs" / id / "passengers.csv").exists()
        assert (
            client.get(f"/api/v1/simulations/{reset['new_run_id']}").json()["status"] == "CREATED"
        )
        assert command(client, id, "pause", "late-pause").status_code == 409


def test_validation_trace_and_failure(tmp_path):
    with TestClient(create_app(tmp_path / "artifacts")) as client:
        assert (
            client.post(
                "/api/v1/config/validate", json={"building": {"floor_count": 31}}
            ).status_code
            == 422
        )
        assert (
            client.post("/api/v1/simulations", json={"controller": {"name": "ppo"}}).status_code
            == 422
        )
        assert client.get("/api/v1/simulations/missing").status_code == 404
        trace = client.post("/api/v1/traces", json={"config": CONFIG}).json()
        bad = {**CONFIG, "seed": 43}
        assert (
            client.post(
                "/api/v1/simulations", json={"config": bad, "trace_id": trace["trace_id"]}
            ).status_code
            == 422
        )
        invalid = "passenger_id,arrival_time,origin_floor,destination_floor\nP,0,1,1\n"
        assert (
            client.post("/api/v1/traces", json={"config": CONFIG, "csv_text": invalid}).status_code
            == 422
        )
        manager = client.app.state.manager
        id = manager.create(
            "simulation", dict(config=CONFIG, trace_path=str(tmp_path / "missing.csv"))
        )
        manager.command(id, "start", "start", {})
        job = wait_for(client, id, {"FAILED"})
        assert job["error"]["code"] == "FileNotFoundError"
        assert (tmp_path / "artifacts" / "runs" / id / "failure.json").exists()


def test_stop_and_queued_limit(tmp_path):
    with TestClient(create_app(tmp_path / "artifacts", max_workers=1)) as client:
        a = client.post(
            "/api/v1/simulations", json={"config": CONFIG, "speed_multiplier": 1}
        ).json()["run_id"]
        b = client.post(
            "/api/v1/simulations", json={"config": CONFIG, "speed_multiplier": 1}
        ).json()["run_id"]
        command(client, a, "start")
        wait_for(client, a, {"RUNNING"})
        command(client, b, "start")
        assert command(client, b, "stop").status_code == 200
        assert wait_for(client, b, {"STOPPED"})
        assert command(client, a, "stop").status_code == 200
        assert wait_for(client, a, {"STOPPED", "FAILED"})["status"] == "STOPPED"
        metrics = client.get(f"/api/v1/simulations/{a}/metrics").json()
        assert metrics["termination_reason"] == "stopped"
        assert not metrics["final"]["eligible_for_ranking"]


def test_restart_repair(tmp_path):
    repo = Repository(tmp_path / "index.sqlite3")
    repo.create("run-test", "simulation", {})
    repo.update("run-test", status="PAUSED")
    repo.repair()
    assert repo.get("run-test")["status"] == "FAILED"
    assert repo.get("run-test")["error"]["code"] == "interrupted"


def test_experiment_and_worker_crash(tmp_path):
    with TestClient(create_app(tmp_path / "artifacts", max_workers=1)) as client:
        suite = {
            "controllers": ["round_robin", "eta", "eta_zone"],
            "scenarios": [{"name": "api-smoke", "seeds": [9001], "config": CONFIG}],
        }
        response = client.post("/api/v1/experiments", json={"suite": suite})
        assert response.status_code == 200, response.text
        id = response.json()["experiment_id"]
        start = time.monotonic()
        while time.monotonic() - start < 15:
            job = client.get(f"/api/v1/experiments/{id}").json()
            if job["status"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.03)
        assert job["status"] == "COMPLETED", job
        result = client.get(f"/api/v1/experiments/{id}/results").json()
        assert len(result["tables"]["runs"]) == 3
        assert client.get(result["report_url"]).status_code == 200
        run = client.post(
            "/api/v1/simulations", json={"config": CONFIG, "speed_multiplier": 1}
        ).json()["run_id"]
        command(client, run, "start")
        wait_for(client, run, {"RUNNING"})
        state = client.app.state.manager.active[run]
        state["process"].terminate()
        failed = wait_for(client, run, {"FAILED"})
        assert failed["error"]["code"] == "worker_exit"


def test_restart_preserves_live_cli_coordinator(tmp_path):
    import os

    repo = Repository(tmp_path / "index.sqlite3")
    repo.create("external-cli", "experiment", {"owner_pid": os.getpid()})
    repo.update("external-cli", status="RUNNING")
    repo.repair()
    assert repo.get("external-cli")["status"] == "RUNNING"


def test_training_curve_is_bounded_and_keeps_last_actual_update(tmp_path):
    folder = tmp_path / "artifacts" / "training" / "long-run"
    folder.mkdir(parents=True)
    (folder / "updates.csv").write_text(
        "step,policy_loss\n" + "".join(f"{i},0.1\n" for i in range(2100))
    )
    with TestClient(create_app(tmp_path / "artifacts")) as client:
        response = client.get("/api/v1/training-runs/long-run/curves")
        assert response.status_code == 200
        updates = response.json()["series"]["updates"]
        assert len(updates) == 1000
        assert updates[0]["step"] == 0 and updates[-1]["step"] == 2099
