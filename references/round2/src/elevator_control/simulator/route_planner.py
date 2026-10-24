"""Shared feasible pickup/dropoff insertion with an immutable execution prefix."""

from dataclasses import dataclass

from elevator_control.config.schema import Physics
from elevator_control.domain.models import Elevator, InvariantError, Passenger, Stop, us

ROUTE_VERSION = "insertion-16-v1"


@dataclass(frozen=True)
class Prediction:
    finish_us: int
    pickup_times: dict[str, int]
    stop_arrival_us: tuple[int, ...]
    distance: int


@dataclass(frozen=True)
class RouteProposal:
    route: tuple[Stop, ...]
    pickup_us: int
    finish_us: int
    distance_added: int
    base_route_version: int
    score: float


def prefix(e: Elevator, now: int) -> tuple[int, int, set[str]]:
    """Predict the state after the current indivisible movement or frozen stop."""
    floor, t, load = e.floor, now, set(e.onboard_ids)
    if e.segment:
        floor, t = e.segment.to_floor, e.segment.end_us
    elif e.active_stop:
        t = e.operation_end_us + sum(duration for _, _, duration in e.pending_operations)
        load.update(e.active_stop.pickup_ids)
        load.difference_update(e.active_stop.dropoff_ids)
    return floor, max(t, now), load


def predict(
    e: Elevator,
    route: list[Stop] | tuple[Stop, ...],
    now: int,
    passengers: dict[str, Passenger],
    ph: Physics,
) -> Prediction | None:
    floor, t, load = prefix(e, now)
    pickup_times: dict[str, int] = {}
    arrivals: list[int] = []
    distance = 0
    for stop in route:
        delta = abs(stop.floor - floor)
        distance += delta
        t += delta * us(ph.seconds_per_floor)
        arrivals.append(t)
        t += us(ph.door_open_s)
        for pid in stop.dropoff_ids:
            if pid not in load:
                return None
            load.remove(pid)
            t += us(ph.alight_s_per_person)
        for pid in sorted(stop.pickup_ids, key=lambda p: (passengers[p].arrival_us, p)):
            if pid in load or pid in pickup_times:
                return None
            load.add(pid)
            if len(load) > e.capacity:
                return None
            t += us(ph.board_s_per_person)
            pickup_times[pid] = t
        t += us(ph.door_close_s)
        floor = stop.floor
    if load:
        return None
    return Prediction(t, pickup_times, tuple(arrivals), distance)


def merge_stops(route: list[Stop]) -> list[Stop]:
    result: list[Stop] = []
    for s in route:
        if result and result[-1].floor == s.floor:
            old = result[-1]
            result[-1] = Stop(
                s.floor, old.pickup_ids + s.pickup_ids, old.dropoff_ids + s.dropoff_ids
            )
        else:
            result.append(s)
    return result


def slots(route: list[Stop], floor: int, start: int = 0, limit: int = 16) -> list[int]:
    candidates = list(range(start, len(route) + 1))
    if len(candidates) <= limit:
        return candidates

    def proximity(i):
        adjacent = [route[j].floor for j in (i - 1, i) if 0 <= j < len(route)]
        return min((abs(f - floor) for f in adjacent), default=0), i

    chosen = sorted((i for i in candidates if i != len(route)), key=proximity)[: limit - 1]
    return sorted(chosen + [len(route)])


def propose(
    e: Elevator,
    passenger: Passenger,
    now: int,
    passengers: dict[str, Passenger],
    ph: Physics,
    *,
    limit: int = 16,
) -> RouteProposal:
    base = predict(e, e.route, now, passengers, ph)
    if base is None:
        raise InvariantError("existing committed route is infeasible")
    best = None
    for i in slots(e.route, passenger.origin, limit=limit):
        pickup = Stop(passenger.origin, [passenger.id], [])
        with_pickup = e.route[:i] + [pickup] + e.route[i:]
        for j in slots(with_pickup, passenger.destination, start=i + 1, limit=limit):
            candidate = merge_stops(
                with_pickup[:j]
                + [Stop(passenger.destination, [], [passenger.id])]
                + with_pickup[j:]
            )
            prediction = predict(e, candidate, now, passengers, ph)
            if prediction is None:
                continue
            pickup_us = prediction.pickup_times[passenger.id]
            score = (pickup_us - now + 0.2 * (prediction.finish_us - base.finish_us)) / 1e6
            key = score, i, j
            if best is None or key < best[0]:
                best = (
                    key,
                    RouteProposal(
                        tuple(candidate),
                        pickup_us,
                        prediction.finish_us,
                        prediction.distance - base.distance,
                        e.route_version,
                        score,
                    ),
                )
    if best is None:
        raise InvariantError("no feasible insertion, including append fallback")
    return best[1]
