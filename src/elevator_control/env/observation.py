"""Fixed-shape public observation registry; no trace/future-count features."""

from dataclasses import dataclass

import gymnasium.spaces as spaces
import numpy as np

from elevator_control.domain.models import Phase
from elevator_control.simulator.engine import Simulator
from elevator_control.simulator.route_planner import predict

OBSERVATION_VERSION = "public-24-8-9-20-v1"
ACTION_VERSION = "dispatch8-reposition5-v1"
REWARD_VERSION = "integrated-v2-start-cutoff"

ELEVATOR_FEATURES = (
    "position",
    "direction",
    "load_ratio",
    "capacity",
    "seconds_per_floor",
    "operation_remaining",
    "idle",
    "reposition",
    "opening",
    "closing",
    "doors_open",
    "moving",
    "assigned_waiting",
    "onboard",
    "stop_count",
    "next_target",
    "has_next",
    "reposition_target",
    "has_reposition",
    "pickup_eta",
    "has_eta",
    "idle_age",
    "cooldown",
    "subject",
)
ROUTE_FEATURES = (
    "floor",
    "has_stop",
    "pickup_up",
    "pickup_down",
    "dropoffs",
    "first_eta",
    "first_order",
    "visits",
)
FLOOR_FEATURES = (
    "floor",
    "waiting_up",
    "waiting_down",
    "oldest_up",
    "oldest_down",
    "origins_60",
    "destinations_60",
    "stationary",
    "reposition_to",
)
GLOBAL_FEATURES = (
    "floors",
    "elevators",
    "capacity",
    "waiting",
    "oldest_wait",
    "onboard",
    "idle_ratio",
    "mean_load",
    "rate_60",
    "rate_300",
    "lobby_origin_ratio",
    "lobby_destination_ratio",
    "up_ratio",
    "time_sin",
    "time_cos",
    "horizon_remaining",
    "drain",
    "mean_wait_age",
    "open_ratio",
    "reposition_ratio",
)
REQUEST_FEATURES = ("origin", "destination", "direction", "wait_age", "valid")


@dataclass(frozen=True)
class FeatureSpec:
    names: tuple[str, ...]
    shape: tuple[int, ...]
    unit: str = "fixed normalized; count=log1p(n)/log(101); time scales per design section 8"


FEATURE_REGISTRY = {
    "elevators": FeatureSpec(ELEVATOR_FEATURES, (8, 24)),
    "elevator_routes": FeatureSpec(ROUTE_FEATURES, (8, 30, 8)),
    "floors": FeatureSpec(FLOOR_FEATURES, (30, 9)),
    "request": FeatureSpec(REQUEST_FEATURES, (5,)),
    "global": FeatureSpec(GLOBAL_FEATURES, (20,)),
    "decision_kind": FeatureSpec(("dispatch", "reposition"), (2,)),
}


def observation_space():
    spec: dict[str, spaces.Space] = {
        k: spaces.Box(-10, 10, shape=v.shape, dtype=np.float32) for k, v in FEATURE_REGISTRY.items()
    }
    spec.update(
        {
            k: spaces.MultiBinary(n)
            for k, n in [("elevator_mask", 8), ("floor_mask", 30), ("action_mask", 13)]
        }
    )
    return spaces.Dict(spec)


def count(n):
    return np.log1p(n) / np.log(101)


def build_observation(sim: Simulator) -> tuple[dict[str, np.ndarray], float]:
    cfg = sim.config
    f, m = cfg.building.floor_count, len(sim.elevators)
    now = sim.now / 1e6

    def norm(x):
        return (x - 1) / (f - 1)

    obs: dict[str, np.ndarray] = {
        k: np.zeros(v.shape, dtype=np.float32) for k, v in FEATURE_REGISTRY.items()
    }
    obs.update(
        elevator_mask=np.arange(8) < m,
        floor_mask=np.arange(30) < f,
        action_mask=np.zeros(13, dtype=bool),
    )
    d = sim.current
    request = None
    if d is not None:
        obs["action_mask"][:] = d.action_mask
        obs["decision_kind"][0 if d.kind == "dispatch" else 1] = 1
        if d.passenger_id is not None:
            request = sim.passengers[d.passenger_id]
            obs["request"][:] = [
                norm(request.origin),
                norm(request.destination),
                np.sign(request.destination - request.origin),
                (sim.now - request.arrival_us) / 300e6,
                1,
            ]
    arrived = [sim.passengers[p] for p in sim.arrived]
    recent = [p for p in arrived if sim.now - p.arrival_us <= 60000000]
    past = [p for p in arrived if sim.now - p.arrival_us <= 300000000]
    waiting = [sim.passengers[p] for p in sorted(sim.waiting)]
    for i, e in enumerate(sim.elevators):
        assigned = [p for p in waiting if p.assigned_elevator == i]
        target = e.route[0].floor if e.route else e.reposition_target
        moving = e.segment is not None
        direction = np.sign(e.segment.to_floor - e.segment.from_floor) if e.segment else 0
        idle = sim._idle(e)
        eta = (sim.proposal(i).pickup_us - sim.now) / 300e6 if request else 0
        obs["elevators"][i] = [
            norm(sim.position(e)),
            direction,
            len(e.onboard_ids) / e.capacity,
            e.capacity / 20,
            cfg.physics.seconds_per_floor / 10,
            max(0, e.operation_end_us - sim.now) / 60e6,
            idle,
            e.reposition_target is not None
            or bool(e.segment and e.segment.purpose == "REPOSITION"),
            e.phase == Phase.OPENING,
            e.phase == Phase.CLOSING,
            e.phase in (Phase.ALIGHTING, Phase.BOARDING),
            moving,
            count(len(assigned)),
            len(e.onboard_ids) / 20,
            count(len(e.route)),
            norm(target) if target is not None else 0,
            target is not None,
            norm(e.reposition_target) if e.reposition_target is not None else 0,
            e.reposition_target is not None,
            eta,
            request is not None,
            (sim.now - e.idle_since_us) / 300e6 if idle else 0,
            max(0, e.next_reposition_allowed_us - sim.now) / 30e6,
            bool(d and d.subject_elevator_id == i),
        ]
        prediction = predict(e, e.route, sim.now, sim.passengers, cfg.physics)
        if prediction is None:
            raise RuntimeError("infeasible observation route")
        for floor in range(1, f + 1):
            visits = [(j, s) for j, s in enumerate(e.route) if s.floor == floor]
            pickups = [sim.passengers[p] for _, s in visits for p in s.pickup_ids]
            obs["elevator_routes"][i, floor - 1] = [
                norm(floor),
                bool(visits),
                count(sum(p.destination > p.origin for p in pickups)),
                count(sum(p.destination < p.origin for p in pickups)),
                count(sum(len(s.dropoff_ids) for _, s in visits)),
                (prediction.stop_arrival_us[visits[0][0]] - sim.now) / 300e6 if visits else 0,
                count(visits[0][0] + 1) if visits else 0,
                count(len(visits)),
            ]
    for floor in range(1, f + 1):
        up = [p for p in waiting if p.origin == floor and p.destination > floor]
        down = [p for p in waiting if p.origin == floor and p.destination < floor]

        def oldest(ps):
            return max(((sim.now - p.arrival_us) / 300e6 for p in ps), default=0)

        obs["floors"][floor - 1] = [
            norm(floor),
            count(len(up)),
            count(len(down)),
            oldest(up),
            oldest(down),
            count(sum(p.origin == floor for p in recent)),
            count(sum(p.destination == floor for p in recent)),
            sum(e.segment is None and e.floor == floor for e in sim.elevators) / 8,
            sum(e.reposition_target == floor for e in sim.elevators) / 8,
        ]
    ages = [(sim.now - p.arrival_us) / 300e6 for p in waiting]
    load = [len(e.onboard_ids) / e.capacity for e in sim.elevators]
    n = len(recent)

    def rate(ps, window):
        return np.log1p(len(ps) * 60 / max(1, min(now, window))) / np.log(61)

    time = cfg.simulation.start_time_of_day_s + now
    obs["global"][:] = [
        f / 30,
        m / 8,
        sum(e.capacity for e in sim.elevators) / 160,
        count(len(waiting)),
        max(ages, default=0),
        len(sim.onboard) / 160,
        sum(sim._idle(e) for e in sim.elevators) / m,
        np.mean(load),
        rate(recent, 60),
        rate(past, 300),
        sum(p.origin == 1 for p in recent) / n if n else 0,
        sum(p.destination == 1 for p in recent) / n if n else 0,
        sum(p.destination > p.origin for p in recent) / n if n else 0,
        np.sin(time * 2 * np.pi / 86400),
        np.cos(time * 2 * np.pi / 86400),
        max(0, (sim.horizon - sim.now) / sim.horizon),
        sim.now >= sim.horizon,
        np.mean(ages) if ages else 0,
        sum(
            e.phase in (Phase.OPENING, Phase.ALIGHTING, Phase.BOARDING, Phase.CLOSING)
            for e in sim.elevators
        )
        / m,
        sum(e.reposition_target is not None for e in sim.elevators) / m,
    ]
    clipped, total = 0, 0
    for key in FEATURE_REGISTRY:
        values = obs[key]
        clipped += int(np.count_nonzero((values < -10) | (values > 10)))
        total += values.size
        np.clip(values, -10, 10, out=values)
    return obs, clipped / total
