"""Trusted training checkpoints; inference registry contains weights-only models."""

import hashlib
import json
import re
from pathlib import Path

import torch

from elevator_control.env.observation import ACTION_VERSION, OBSERVATION_VERSION, REWARD_VERSION
from elevator_control.rl.network import (
    ARCHITECTURE_VERSION,
    FOCUSED_VERSION,
    RESIDUAL_VERSION,
    ActorCritic,
    model_from_config,
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


def versions_for_config(config: dict) -> dict:
    if config.get("candidate_policy", False):
        from elevator_control.env.candidates import CANDIDATE_VERSION

        focused = (
            config.get("structured_residual", False) or config.get("policy_temperature", 1) != 1
        )
        return {
            **VERSIONS,
            "architecture": FOCUSED_VERSION if focused else RESIDUAL_VERSION,
            "observation": CANDIDATE_VERSION,
            "reward": "wait-potential-v3"
            if config.get("potential_shaping")
            else VERSIONS["reward"],
        }
    return VERSIONS.copy()


def check_versions(versions: dict):
    allowed = [VERSIONS] + [
        versions_for_config(
            dict(candidate_policy=True, policy_temperature=temperature, potential_shaping=shaping)
        )
        for temperature in (1.0, 0.1)
        for shaping in (False, True)
    ]
    if versions not in allowed:
        raise ValueError(
            f"incompatible model semantics: expected a supported coherent version, got {versions}"
        )


def save_checkpoint(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    torch.save(data, temp)
    temp.replace(path)


def validate_model_settings(model: ActorCritic, config: dict):
    """Fixed policy priors belong to both the saved state and its declared configuration."""
    if config.get("candidate_policy", False):
        expected = torch.tensor(
            config["prior_weights"],
            dtype=model.prior_weights.dtype,
            device=model.prior_weights.device,
        )
        if not torch.equal(model.prior_weights, expected):
            raise ValueError(
                "prior configuration does not match checkpoint state; start a new prior family run"
            )


def register(checkpoint: str | Path, model_id: str, root: str | Path = "artifacts/models") -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", model_id):
        raise ValueError("invalid model_id")
    data = torch.load(checkpoint, map_location="cpu", weights_only=False)
    check_versions(data["versions"])
    if data["versions"] != versions_for_config(data["config"]):
        raise ValueError("checkpoint config/version mismatch")
    validated_model = model_from_config(data["config"])
    validated_model.load_state_dict(data["network"])
    validate_model_settings(validated_model, data["config"])
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
        parameter_count=sum(value.numel() for value in validated_model.parameters()),
        buffer_elements=sum(value.numel() for value in validated_model.buffers()),
        seed=data["config"]["seed"],
        validation=data.get("validation"),
        selection=data["config"].get("selection_mode", "cost"),
        policy_family="candidate-learned-weight-ppo"
        if data["config"].get("structured_residual")
        and not data["config"].get("contextual_weights", True)
        else "candidate-context-weight-ppo"
        if data["config"].get("structured_residual")
        else "candidate-cost-prior-residual-ppo"
        if data["config"].get("candidate_policy")
        else "shared-attention-ppo",
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
    check_versions(metadata["versions"])
    if hashlib.sha256((path / "weights.pt").read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("model checksum mismatch")
    if metadata["versions"] != versions_for_config(metadata["training_config"]):
        raise ValueError("model config/version mismatch")
    model = model_from_config(metadata["training_config"])
    model.load_state_dict(torch.load(path / "weights.pt", map_location="cpu", weights_only=True))
    validate_model_settings(model, metadata["training_config"])
    model.eval()
    return model, metadata
