"""Controllers consume detached, public decision views, never future events."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from elevator_control.config.schema import SimulationConfig
from elevator_control.domain.models import DecisionRequest
from elevator_control.simulator.engine import Simulator, region_index, region_targets


@dataclass(frozen=True)
class DecisionView:
    request: DecisionRequest
    snapshot: dict
    eta_s: tuple[float, ...]
    arrivals: tuple[tuple[float, int, int], ...]
    observation: dict[str, np.ndarray] | None = None


class Controller(Protocol):
    def reset(self, config: SimulationConfig, seed: int) -> None: ...
    def act(self, view: DecisionView) -> int: ...
    def close(self) -> None: ...


def decision_view(
    sim: Simulator, *, include_observation: bool = False, include_candidates: bool = False
) -> DecisionView:
    d = sim.current
    if d is None:
        raise ValueError("no decision")
    etas = (
        tuple((sim.proposal(i).pickup_us - sim.now) / 1e6 for i in range(len(sim.elevators)))
        if d.kind == "dispatch"
        else ()
    )
    arrivals = tuple(
        (
            sim.passengers[p].arrival_us / 1e6,
            sim.passengers[p].origin,
            sim.passengers[p].destination,
        )
        for p in sim.arrived
        if sim.now - sim.passengers[p].arrival_us <= 300000000
    )
    observation = None
    if include_observation or include_candidates:
        from elevator_control.env.observation import build_observation

        observation, _ = build_observation(sim)
        if include_candidates:
            from elevator_control.env.candidates import candidate_features

            observation["candidates"] = candidate_features(sim)
    return DecisionView(d, sim.snapshot(), etas, arrivals, observation)


class Baseline:
    def __init__(self, name: str = "eta"):
        if name not in ("round_robin", "eta", "eta_zone"):
            raise ValueError(f"unknown baseline {name}")
        self.name = name
        self.version = "eta-zone-partition-v2" if name == "eta_zone" else name + "-v1"
        self.pointer = 0

    def reset(self, config: SimulationConfig, seed: int) -> None:
        self.pointer = 0

    def close(self) -> None:
        return None

    def act(self, view: DecisionView) -> int:
        d = view.request
        if d.kind == "dispatch":
            if self.name == "round_robin":
                action = self.pointer % len(view.eta_s)
                self.pointer += 1
                return action
            return min(range(len(view.eta_s)), key=lambda i: (view.eta_s[i], i))
        if self.name != "eta_zone" or not view.arrivals:
            return 8
        elevators = view.snapshot["elevators"]
        assert d.subject_elevator_id is not None
        subject = elevators[d.subject_elevator_id]
        targets = region_targets(len(view.snapshot["floor_queues"]))

        def zone(floor):
            return region_index(int(floor), len(view.snapshot["floor_queues"]))

        heat = [sum(zone(o) == j for _, o, _ in view.arrivals) for j in range(4)]
        scores = []
        for j, target in enumerate(targets):
            action = 9 + j
            if not d.action_mask[action]:
                continue
            residents = sum(
                not e.get("has_service", False)
                and e["load"] == 0
                and (e["phase"] == "IDLE_CLOSED" or e["purpose"] == "REPOSITION")
                and zone(e["target_floor"] or e["position_floor"]) == j
                for e in elevators
                if e["id"] != subject["id"]
            )
            scores.append(
                (-heat[j] / (residents + 1), abs(target - subject["position_floor"]), action)
            )
        return min(scores)[2] if scores and min(scores)[0] < 0 else 8


def apply_controller_action(
    sim: Simulator, controller: Controller, on_timing: Callable[[str, float], None] | None = None
) -> None:
    d = sim.current
    if d is None:
        raise ValueError("no active decision barrier")
    start = time.perf_counter()
    action = controller.act(
        decision_view(
            sim,
            include_observation=getattr(controller, "requires_observation", False),
            include_candidates=getattr(controller, "requires_candidates", False),
        )
    )
    sim.apply_action(d.decision_id, action)
    elapsed = (time.perf_counter() - start) * 1000
    if sim.audit and sim.decisions:
        fields = {"inference_ms": elapsed}
        probabilities = getattr(controller, "last_probabilities", None)
        if probabilities is not None:
            fields["probabilities"] = probabilities
        sim.decisions.update_last(fields)
    if on_timing is not None:
        on_timing(d.kind, elapsed)


def run_simulation(
    config: SimulationConfig,
    trace,
    controller: Controller | None = None,
    *,
    audit=True,
    on_timing: Callable[[str, float], None] | None = None,
) -> Simulator:
    controller = controller or Baseline(config.controller.name)
    controller.reset(config, config.seed)
    sim = Simulator(config, trace, audit=audit)
    try:
        while sim.advance_until_decision_or_end() is not None:
            apply_controller_action(sim, controller, on_timing)
        sim.assert_invariants()
        return sim
    finally:
        controller.close()
