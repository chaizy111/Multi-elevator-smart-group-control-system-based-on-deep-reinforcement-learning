import json

import pandas as pd
import pytest
import torch

from elevator_control.controllers.rl_controller import RLController
from elevator_control.env.environment import ElevatorEnv
from elevator_control.rl.checkpoint import register
from elevator_control.rl.network import ActorCritic, tensor_observations
from elevator_control.rl.trainer import TrainingConfig, train


def test_real_train_register_restore(tmp_path):
    cfg = TrainingConfig.model_validate(
        {
            "total_decisions": 128,
            "rollout_steps": 64,
            "epochs": 2,
            "simulation": {
                "building": {"floor_count": 5, "elevator_count": 2, "capacity": 6},
                "simulation": {"arrival_horizon_s": 60},
                "traffic": {"arrival_rate_per_min": 4},
            },
        }
    )
    out = train(cfg, tmp_path / "training")
    progress = json.loads((out / "progress.json").read_text())
    assert progress["steps"] == 128 and progress["changed_tensors"] > 0
    episodes = pd.read_csv(out / "episodes.csv")
    from elevator_control.config.schema import SimulationConfig, canonical_hash
    from elevator_control.traffic.trace import generate

    for record in episodes.head(3).to_dict(orient="records"):
        actual = SimulationConfig.model_validate(json.loads(record["config_json"]))
        assert canonical_hash(actual) == record["config_hash"]
        assert generate(actual).sha256 == record["trace_hash"]
        assert 100000 <= actual.seed <= 999999
    updates = pd.read_csv(out / "updates.csv")
    assert updates.dispatch_samples.sum() > 0 and updates.reposition_samples.sum() > 0
    assert updates.dispatch_gradient.sum() > 0 and updates.reposition_gradient.sum() > 0
    ckpt = out / "checkpoints/best.pt"
    register(ckpt, "test-model", tmp_path / "models")
    controller = RLController("test-model", root=tmp_path / "models")
    data = torch.load(ckpt, weights_only=False)
    model = ActorCritic()
    model.load_state_dict(data["network"])
    model.eval()
    env = ElevatorEnv(cfg.simulation)
    obs, _ = env.reset(seed=1)
    with torch.no_grad():
        a, va = model(tensor_observations(obs))
        b, vb = controller.model(tensor_observations(obs))
    torch.testing.assert_close(a, b, rtol=0, atol=0)
    torch.testing.assert_close(va, vb, rtol=0, atol=0)
    train(cfg, out, resume=str(out / "checkpoints/last.pt"))
    with pytest.raises(ValueError):
        changed = cfg.model_copy(update={"entropy_coefficient": 0.02})
        train(changed, tmp_path / "wrong", resume=str(out / "checkpoints/last.pt"))


def test_real_interrupt_and_resume(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time

    import yaml

    if os.name != "posix":
        pytest.skip("POSIX SIGINT lifecycle integration")
    config = {
        "total_decisions": 1024,
        "rollout_steps": 64,
        "epochs": 2,
        "validation_interval": 2,
        "simulation": {
            "building": {"floor_count": 5, "elevator_count": 2, "capacity": 6},
            "simulation": {"arrival_horizon_s": 60},
            "traffic": {"arrival_rate_per_min": 4},
        },
    }
    source = tmp_path / "training.yaml"
    source.write_text(yaml.safe_dump(config))
    output = tmp_path / "interrupted"
    env = {
        **os.environ,
        "PYTHONPATH": str(__import__("pathlib").Path("src").resolve()),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    with (tmp_path / "console.log").open("w") as stream:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "elevator_control.cli",
                "train",
                "--config",
                str(source),
                "--output",
                str(output),
            ],
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 15
        checkpoint = output / "checkpoints/last.pt"
        while not checkpoint.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert checkpoint.exists()
        process.send_signal(signal.SIGINT)
        process.wait(timeout=15)
    progress = json.loads((output / "progress.json").read_text())
    assert progress["status"] == "INTERRUPTED"
    saved = torch.load(output / "checkpoints/last.pt", map_location="cpu", weights_only=False)
    assert 0 < saved["steps"] < 1024
    resumed = subprocess.run(
        [sys.executable, "-m", "elevator_control.cli", "train", "--resume", str(checkpoint)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads((output / "progress.json").read_text())["steps"] == 1024
    updates = pd.read_csv(output / "updates.csv")
    assert updates.step.is_monotonic_increasing and updates.step.is_unique
