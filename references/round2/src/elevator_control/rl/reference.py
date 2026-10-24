"""Explicit non-learning reference used in RL incremental-benefit experiments."""

import numpy as np

from elevator_control.controllers.baselines import DecisionView


class CandidatePrior:
    requires_observation = True
    requires_candidates = True
    version = "candidate-prior-only-v2"

    def __init__(self, weights, *, dtype=np.float32):
        # Registered policies use float32; historical grid searches used float64.
        self.weights = np.asarray(weights, dtype=dtype)
        if self.weights.shape != (6,) or not np.isfinite(self.weights).all():
            raise ValueError("expected six finite prior weights")

    def reset(self, config, seed):
        return None

    def close(self):
        return None

    def act(self, view: DecisionView) -> int:
        if view.request.kind == "reposition":
            return 8
        if view.observation is None:
            raise ValueError("public candidate observation required")
        costs = view.observation["candidates"] @ self.weights
        return min(
            (i for i in range(8) if view.request.action_mask[i]), key=lambda i: (costs[i], i)
        )
