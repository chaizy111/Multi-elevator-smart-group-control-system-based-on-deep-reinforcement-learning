"""Core entities. Integer microseconds avoid floating point event ordering drift."""

import math
from dataclasses import dataclass, field
from enum import StrEnum


class InvariantError(RuntimeError):
    """A violated physical or lifecycle invariant; never a recoverable policy action."""


def us(seconds: float) -> int:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("time in seconds must be finite and nonnegative")
    return max(1, round(seconds * 1_000_000)) if seconds > 0 else 0


class Status(StrEnum):
    NOT_ARRIVED = "NOT_ARRIVED"
    WAITING_UNASSIGNED = "WAITING_UNASSIGNED"
    WAITING_ASSIGNED = "WAITING_ASSIGNED"
    ONBOARD = "ONBOARD"
    COMPLETED = "COMPLETED"


class Phase(StrEnum):
    IDLE = "IDLE_CLOSED"
    MOVING = "MOVING"
    OPENING = "OPENING"
    ALIGHTING = "ALIGHTING"
    BOARDING = "BOARDING"
    CLOSING = "CLOSING"


@dataclass
class Passenger:
    id: str
    arrival_us: int
    origin: int
    destination: int
    status: Status = Status.NOT_ARRIVED
    assigned_elevator: int | None = None
    assigned_us: int | None = None
    pickup_us: int | None = None
    finish_us: int | None = None


@dataclass
class Stop:
    floor: int
    pickup_ids: list[str] = field(default_factory=list)
    dropoff_ids: list[str] = field(default_factory=list)


@dataclass
class MotionSegment:
    from_floor: int
    to_floor: int
    start_us: int
    end_us: int
    purpose: str
    generation: int


@dataclass
class Elevator:
    id: str
    capacity: int
    floor: int
    phase: Phase = Phase.IDLE
    onboard_ids: list[str] = field(default_factory=list)
    route: list[Stop] = field(default_factory=list)
    active_stop: Stop | None = None
    segment: MotionSegment | None = None
    reposition_target: int | None = None
    next_reposition_allowed_us: int = 0
    route_version: int = 0
    idle_since_us: int = 0
    operation_end_us: int = 0
    pending_operations: list[tuple[str, str | None, int]] = field(default_factory=list)
    distance_floors: float = 0
    busy_s: float = 0
    service_s: float = 0
    reposition_s: float = 0
    door_s: float = 0


@dataclass(frozen=True)
class DecisionRequest:
    decision_id: int
    time_us: int
    kind: str
    action_mask: tuple[bool, ...]
    passenger_id: str | None = None
    subject_elevator_id: int | None = None
