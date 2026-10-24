"""Deterministic masked inference, without silent baseline fallback."""

import torch

from elevator_control.config.schema import SimulationConfig
from elevator_control.controllers.baselines import DecisionView
from elevator_control.rl.checkpoint import load_model
from elevator_control.rl.network import tensor_observations
from elevator_control.rl.reference import CandidatePrior


class RLController:
    requires_observation = True

    def __init__(
        self,
        model_id: str,
        *,
        force_stay: bool = False,
        prior_only: bool = False,
        root="artifacts/models",
    ):
        torch.set_num_threads(1)
        self.model, self.metadata = load_model(model_id, root)
        self.requires_candidates = self.metadata["training_config"].get("candidate_policy", False)
        if prior_only and not self.requires_candidates:
            raise ValueError("prior ablation requires a candidate policy")
        self.reference = (
            CandidatePrior(self.model.prior_weights.detach().cpu().numpy()) if prior_only else None
        )
        self.version = (
            (CandidatePrior.version if prior_only else self.metadata["versions"]["architecture"])
            if self.requires_candidates
            else None
        )
        self.model_hash = self.metadata["sha256"]
        self.last_probabilities: list[float] | None = None
        self.force_stay = force_stay or self.metadata["training_config"].get("dispatch_only", False)

    def reset(self, config: SimulationConfig, seed: int) -> None:
        self.last_probabilities = None
        support = self.metadata["support"]
        if (
            config.building.floor_count > support["max_floors"]
            or config.building.elevator_count > support["max_elevators"]
        ):
            raise ValueError("building exceeds model support")

    def act(self, view: DecisionView) -> int:
        if self.reference is not None:
            action = self.reference.act(view)
            self.last_probabilities = [0.0] * 13
            self.last_probabilities[action] = 1.0
            return action
        if self.force_stay and view.request.kind == "reposition":
            self.last_probabilities = [0.0] * 13
            self.last_probabilities[8] = 1.0
            return 8
        if view.observation is None:
            raise ValueError("public observation required for RL inference")
        with torch.no_grad():
            observation = tensor_observations(view.observation)
            distribution, _ = self.model.distribution(observation)
        self.last_probabilities = distribution.probs[0].tolist()
        return int(distribution.logits.argmax(-1).item())

    def close(self) -> None:
        return None
