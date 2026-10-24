"""Public insertion consequences; predictions use only already arrived service tasks."""

import numpy as np

from elevator_control.domain.models import us
from elevator_control.simulator.engine import Simulator
from elevator_control.simulator.route_planner import predict

CANDIDATE_VERSION = "public-insertion6-v2"
CANDIDATE_OBSERVATION_VERSION = "public-insertion-input-24-8-9-20-6-v1"
CANDIDATE_FEATURES = (
    "pickup_minutes",
    "new_finish_minutes",
    "added_distance_tens",
    "existing_pickup_delay_minutes",
    "existing_finish_delay_minutes",
    "route_extension_minutes",
)


def finish_times(route, prediction, physics):
    result = {}
    for stop, arrival in zip(route, prediction.stop_arrival_us, strict=True):
        time = arrival + us(physics.door_open_s)
        for pid in stop.dropoff_ids:
            time += us(physics.alight_s_per_person)
            result[pid] = time
    return result


def candidate_features(sim: Simulator) -> np.ndarray:
    result = np.zeros((8, 6), dtype=np.float32)
    decision = sim.current
    if decision is None or decision.kind != "dispatch":
        return result
    for i, elevator in enumerate(sim.elevators):
        base = predict(elevator, elevator.route, sim.now, sim.passengers, sim.config.physics)
        proposal = sim.proposal(i)
        planned = predict(elevator, proposal.route, sim.now, sim.passengers, sim.config.physics)
        if base is None or planned is None:
            raise RuntimeError("infeasible committed/candidate route")
        base_finish = finish_times(elevator.route, base, sim.config.physics)
        new_finish = finish_times(proposal.route, planned, sim.config.physics)
        result[i] = [
            (proposal.pickup_us - sim.now) / 60e6,
            (new_finish[decision.passenger_id] - sim.now) / 60e6,
            proposal.distance_added / 10,
            sum(planned.pickup_times[p] - t for p, t in base.pickup_times.items()) / 60e6,
            sum(new_finish[p] - t for p, t in base_finish.items()) / 60e6,
            (planned.finish_us - base.finish_us) / 60e6,
        ]
    if not np.isfinite(result).all():
        raise ValueError("nonfinite public candidate consequences")
    return np.clip(result, -1000, 1000)
