"""A fresh submission needs neither development data nor hidden training."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from elevator_control.backend.app import create_app
from elevator_control.rl.checkpoint import load_model
from elevator_control.storage.paths import artifact_root
from elevator_control.submission import DEFAULT_MODEL_ID, prepare


def test_fresh_payload_is_idempotent_and_serves_the_selected_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATOR_ARTIFACTS", str(tmp_path))
    assert artifact_root() == tmp_path
    assert prepare() == prepare()
    model, metadata = load_model(DEFAULT_MODEL_ID)
    assert model.candidate_inputs and metadata["training_steps"] == 143360
    with TestClient(create_app(max_workers=1)) as client:
        models = client.get("/api/v1/models").json()["items"]
        assert len(models) == 4 and any(m["model_id"] == DEFAULT_MODEL_ID for m in models)
        runs = client.get("/api/v1/training-runs").json()["items"]
        assert len(runs) == 3 and all(r["progress"]["status"] == "COMPLETED" for r in runs)
        curves = client.get("/api/v1/training-runs/consequences-s801-n200000/curves").json()[
            "series"
        ]
        assert curves["updates"][-1]["step"] == 200000


def test_changed_payload_is_rejected_without_overwriting(tmp_path, monkeypatch):
    from elevator_control import submission

    def interrupted_copy(source, destination):
        destination.write_bytes(b"interrupted partial copy")
        raise OSError("simulated interrupted copy")

    with monkeypatch.context() as patch:
        patch.setattr(submission.shutil, "copyfile", interrupted_copy)
        with pytest.raises(OSError, match="interrupted copy"):
            prepare(tmp_path)
    # A leftover temporary file must not become a corrupted installed payload.
    prepare(tmp_path)
    target = tmp_path / "models" / DEFAULT_MODEL_ID / "weights.pt"
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="existing runtime payload differs"):
        prepare(tmp_path)
    assert target.read_bytes() == b"changed"


def test_payload_weights_match_the_frozen_manifest():
    from elevator_control.storage.paths import PROJECT_ROOT

    manifest = json.loads((PROJECT_ROOT / "assets/release/manifest.json").read_text())
    for row in manifest["files"]:
        path = PROJECT_ROOT / "assets/release" / row["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
