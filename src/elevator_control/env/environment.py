"""Event-driven Gymnasium SMDP: one action advances to the next decision barrier."""

from typing import Any

import gymnasium as gym
import numpy as np

from elevator_control.config.schema import SimulationConfig
from elevator_control.env.observation import build_observation, observation_space
from elevator_control.evaluation.metrics import reward_from_costs
from elevator_control.simulator.engine import Simulator
from elevator_control.traffic.trace import TrafficTrace, generate


class ElevatorEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        config: SimulationConfig | None = None,
        trace: TrafficTrace | None = None,
        *,
        candidate_inputs: bool = False,
    ):
        self.candidate_inputs = candidate_inputs
        self.base_config = config or SimulationConfig()
        self.fixed_trace = trace
        self.observation_space = observation_space()
        if candidate_inputs:
            self.observation_space["candidates"] = gym.spaces.Box(
                -1000, 1000, shape=(8, 6), dtype=np.float32
            )
        self.action_space = gym.spaces.Discrete(13)
        self.sim: Simulator | None = None

    def _observation(self, sim):
        obs, clipping = build_observation(sim)
        if self.candidate_inputs:
            from elevator_control.env.candidates import candidate_features

            obs["candidates"] = candidate_features(sim)
        return obs, clipping

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        cfg = self.base_config.model_copy(deep=True)
        if seed is not None:
            cfg.seed = int(seed)
        self.sim = Simulator(cfg, self.fixed_trace or generate(cfg), audit=False)
        self.sim.advance_until_decision_or_end()
        obs, clip = self._observation(self.sim)
        return obs, dict(
            decision_id=self.sim.current.decision_id if self.sim.current else None,
            clipping_ratio=clip,
        )

    def step(self, action):
        sim = self.sim
        if sim is None or sim.done or sim.current is None:
            raise RuntimeError("reset required before step or after episode end")
        d = sim.current
        previous = sim.costs.copy()
        time = sim.now
        sim.apply_action(d.decision_id, int(action))
        sim.advance_until_decision_or_end()
        costs = {k: sim.costs[k] - previous[k] for k in previous}
        obs, clip = self._observation(sim)
        terminated = sim.done and sim.reason == "completed"
        truncated = sim.done and not terminated
        info: dict[str, Any] = dict(
            decision_id=d.decision_id,
            decision_kind=d.kind,
            delta_t_s=(sim.now - time) / 1e6,
            reward_components=costs,
            counts=sim.summary(),
            termination_reason=sim.reason,
            clipping_ratio=clip,
        )
        if sim.done:
            info["final_observation"] = {k: v.copy() for k, v in obs.items()}
            info["final_state"] = sim.snapshot()
        return obs, reward_from_costs(costs, sim.config), terminated, truncated, info

    def render(self):
        return self.sim.snapshot() if self.sim else None


class CheckerDiscrete(gym.spaces.Discrete):
    """Only for generic Gym checker sampling, which does not supply action masks."""

    def __init__(self, env: ElevatorEnv):
        super().__init__(13)
        self.env = env

    def sample(self, mask=None, probability=None):
        if mask is None and self.env.sim and self.env.sim.current:
            mask = np.asarray(self.env.sim.current.action_mask, dtype=np.int8)
        return super().sample(mask=mask, probability=probability)
