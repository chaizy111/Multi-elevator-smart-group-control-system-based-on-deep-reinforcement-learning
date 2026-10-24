"""Trusted training checkpoints; inference registry contains weights-only models."""

import hashlib
import json
import re
from pathlib import Path

import torch

from elevator_control.env.candidates import CANDIDATE_OBSERVATION_VERSION
from elevator_control.env.observation import ACTION_VERSION, OBSERVATION_VERSION, REWARD_VERSION
from elevator_control.rl.network import (
    ARCHITECTURE_VERSION,
    CANDIDATE_ARCHITECTURE_VERSION,
    ActorCritic,
)
from elevator_control.simulator.engine import SIMULATOR_VERSION
from elevator_control.simulator.route_planner import ROUTE_VERSION
from elevator_control.storage.artifacts import atomic_json

VERSIONS = dict(
    simulator=SIMULATOR_VERSION,
    observation=OBSERVATION_VERSION,
    action=ACTION_VERSION,
    reward=REWARD_VERSION,
    route=ROUTE_VERSION,
    architecture=ARCHITECTURE_VERSION,
)


def versions_for(candidate_inputs: bool = False):
    return (
        dict(
            VERSIONS,
            observation=CANDIDATE_OBSERVATION_VERSION,
            architecture=CANDIDATE_ARCHITECTURE_VERSION,
        )
        if candidate_inputs
        else VERSIONS.copy()
    )


def check_versions(versions: dict, *, candidate_inputs: bool = False):
    expected = versions_for(candidate_inputs)
    if versions != expected:
        raise ValueError(f"incompatible model semantics: expected {expected}, got {versions}")


def initialize_network(model, data, *, migrate_candidate_inputs=False):
    """Copy old learned weights; new consequence inputs start with zero influence."""
    source = data["config"].get("candidate_inputs", False)
    check_versions(data["versions"], candidate_inputs=source)
    state = data["network"]
    if source != model.candidate_inputs:
        if not (migrate_candidate_inputs and model.candidate_inputs and not source):
            raise ValueError("candidate architecture requires explicit migration")
        state = dict(state)
        old = state["dispatch.0.weight"]
        if old.shape != (128, 224):
            raise ValueError("expected legacy 128x224 dispatch input")
        state["dispatch.0.weight"] = torch.cat((old, old.new_zeros(128, 6)), -1)
    model.load_state_dict(state, strict=True)


def save_checkpoint(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    torch.save(data, temp)
    temp.replace(path)


def register(checkpoint: str | Path, model_id: str, root: str | Path = "artifacts/models") -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", model_id):
        raise ValueError("invalid model_id")
    data = torch.load(checkpoint, map_location="cpu", weights_only=False)
    check_versions(data["versions"], candidate_inputs=data["config"].get("candidate_inputs", False))
    path = Path(root) / model_id
    if path.exists():
        raise ValueError("model_id already exists; register a new immutable ID")
    path.mkdir(parents=True)
    torch.save(data["network"], path / "weights.pt")
    sha = hashlib.sha256((path / "weights.pt").read_bytes()).hexdigest()
    metadata = dict(
        schema_version=1,
        model_id=model_id,
        sha256=sha,
        versions=data["versions"],
        attention=data["config"]["attention"],
        support=dict(max_floors=30, max_elevators=8),
        region_mapping="array_split(2..F,3), lower median; Lobby=1",
        training_config=data["config"],
        training_steps=data["steps"],
        parameter_count=sum(value.numel() for value in data["network"].values()),
        seed=data["config"]["seed"],
        validation=data.get("validation"),
        selection=data.get("selection", "complete-service validation cost; P95 tie break"),
        torch_version=str(torch.__version__),
    )
    atomic_json(path / "metadata.json", metadata)
    atomic_json(path / "validation_metrics.json", data.get("validation", {}))
    from elevator_control.storage.repository import Repository

    repo = Repository(Path(root).parent / "index.sqlite3")
    repo.create(model_id, "model", metadata)
    repo.update(model_id, status="COMPLETED")
    return path


def load_model(model_id: str, root: str | Path = "artifacts/models") -> tuple[ActorCritic, dict]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", model_id):
        raise ValueError("invalid model_id")
    path = Path(root) / model_id
    metadata = json.loads((path / "metadata.json").read_text())
    candidate_inputs = metadata.get("training_config", {}).get("candidate_inputs", False)
    check_versions(metadata["versions"], candidate_inputs=candidate_inputs)
    if hashlib.sha256((path / "weights.pt").read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("model checksum mismatch")
    model = ActorCritic(attention=metadata["attention"], candidate_inputs=candidate_inputs)
    model.load_state_dict(torch.load(path / "weights.pt", map_location="cpu", weights_only=True))
    model.eval()
    return model, metadata
