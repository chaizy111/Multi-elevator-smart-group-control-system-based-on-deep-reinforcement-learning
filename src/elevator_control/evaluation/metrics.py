"""Cohort statistics with explicit censoring and horizon/final separation."""

import numpy as np

from elevator_control.domain.models import Passenger
from elevator_control.simulator.engine import Simulator

METRICS_VERSION = "cohort-v2-all-floors"


def _time(value: int | None) -> int:
    if value is None:
        raise ValueError("timestamp unavailable for selected metric cohort")
    return value


def cohort_metrics(
    passengers: list[Passenger],
    end_us: int,
    horizon_us: int,
    threshold_s: float = 60,
    floor_count: int | None = None,
) -> dict:
    picked = [p for p in passengers if p.pickup_us is not None and p.pickup_us <= end_us]
    finished = [p for p in picked if p.finish_us is not None and p.finish_us <= end_us]
    waits = [(_time(p.pickup_us) - p.arrival_us) / 1e6 for p in picked]
    rides = [(_time(p.finish_us) - _time(p.pickup_us)) / 1e6 for p in finished]
    systems = [(_time(p.finish_us) - p.arrival_us) / 1e6 for p in finished]
    unpicked = [p for p in passengers if p.pickup_us is None or p.pickup_us > end_us]
    # Only passengers already arrived contribute observed ages at an intermediate snapshot.
    lower = sum(waits) + sum(max(0, end_us - p.arrival_us) / 1e6 for p in unpicked)
    confirmed_long = sum(w > threshold_s for w in waits) + sum(
        (end_us - p.arrival_us) / 1e6 > threshold_s for p in unpicked
    )
    n = len(passengers)
    floor_fairness = {}
    floors = (
        range(1, floor_count + 1)
        if floor_count is not None
        else sorted({p.origin for p in passengers})
    )
    for floor in floors:
        values = [(_time(p.pickup_us) - p.arrival_us) / 1e6 for p in picked if p.origin == floor]
        floor_fairness[str(floor)] = dict(
            count=len(values),
            mean_wait_s=float(np.mean(values)) if values else None,
            p95_wait_s=float(np.percentile(values, 95, method="linear")) if values else None,
        )
    floor_means = [
        x["mean_wait_s"] for x in floor_fairness.values() if x["mean_wait_s"] is not None
    ]
    return dict(
        sample_count=n,
        picked_count=len(picked),
        completed_count=len(finished),
        unpicked=n - len(picked),
        unfinished=n - len(finished),
        mean_wait_s=float(np.mean(waits)) if waits else None,
        p95_wait_s=float(np.percentile(waits, 95, method="linear")) if waits else None,
        max_wait_s=max(waits) if waits else None,
        mean_travel_s=float(np.mean(rides)) if rides else None,
        mean_system_time_s=float(np.mean(systems)) if systems else None,
        long_wait_ratio=float(np.mean(np.array(waits) > threshold_s)) if waits else None,
        throughput_per_min=sum(
            p.finish_us is not None and p.finish_us <= horizon_us for p in passengers
        )
        / (horizon_us / 60000000),
        completion_ratio=len(finished) / n if n else 1.0,
        conditional_wait=bool(unpicked),
        censored_mean_wait_lower_bound_s=lower / n if n else None,
        long_wait_cohort_lower_bound=confirmed_long / n if n else None,
        long_wait_unknown_count=sum((end_us - p.arrival_us) / 1e6 <= threshold_s for p in unpicked),
        eligible_for_ranking=bool(n and len(finished) == n),
        floor_fairness=floor_fairness,
        worst_floor_mean_wait_s=max(floor_means) if floor_means else None,
    )


def calculate(sim: Simulator) -> dict:
    ps = list(sim.passengers.values())
    final = cohort_metrics(
        ps,
        sim.now,
        sim.horizon,
        sim.config.metrics.long_wait_threshold_s,
        sim.config.building.floor_count,
    )
    at_horizon = cohort_metrics(
        ps,
        min(sim.now, sim.horizon),
        sim.horizon,
        sim.config.metrics.long_wait_threshold_s,
        sim.config.building.floor_count,
    )
    h = sim.horizon_state or sim.summary()
    at_horizon.update(distance_floors=h["distance_floors"], energy_proxy=h["energy_proxy"])
    final.update(
        distance_floors=sum(e.distance_floors for e in sim.elevators),
        distance_m=sum(e.distance_floors for e in sim.elevators)
        * sim.config.building.floor_height_m,
        reposition_distance_floors=sim.reposition_distance,
        empty_distance_floors=sim.empty_distance,
        loaded_distance_floors=sim.loaded_distance,
        energy_proxy=sim.costs["energy"],
        door_cycles=sim.door_cycles,
        starts=sim.starts,
        drain_time_s=max(0, (sim.now - sim.horizon) / 1e6),
        drain_timeout=sim.reason == "drain_timeout",
        costs=sim.costs.copy(),
        utilization={
            e.id: dict(
                busy=e.busy_s / (sim.now / 1e6) if sim.now else 0,
                service=e.service_s / (sim.now / 1e6) if sim.now else 0,
                reposition=e.reposition_s / (sim.now / 1e6) if sim.now else 0,
                door=e.door_s / (sim.now / 1e6) if sim.now else 0,
            )
            for e in sim.elevators
        },
    )
    return dict(
        schema_version=1,
        metrics_version=METRICS_VERSION,
        termination_reason=sim.reason,
        at_horizon=at_horizon,
        final=final,
    )


def reward_from_costs(costs: dict, config) -> float:
    r = config.reward
    return -(
        r.wait_weight * costs["wait"] / (r.passenger_scale * r.time_scale_s)
        + r.ride_weight * costs["ride"] / (r.passenger_scale * r.time_scale_s)
        + r.energy_weight * costs["energy"] / r.distance_scale_floors
        + r.fairness_weight * costs["fairness"] / r.passenger_scale
    )
