"""Integer-time discrete-event kernel with explicit decision barriers.

Physics is policy-independent: events complete before arrivals; dispatches precede
local starts; idle reposition decisions are last. An active stop's manifest freezes
at opening start, and an adjacent-floor motion cannot be cancelled.
"""

import heapq
from collections import deque
from dataclasses import asdict

from elevator_control.config.schema import SimulationConfig
from elevator_control.domain.models import (
    DecisionRequest,
    Elevator,
    InvariantError,
    MotionSegment,
    Phase,
    Status,
    us,
)
from elevator_control.simulator.audit import AuditLog
from elevator_control.simulator.route_planner import RouteProposal, propose
from elevator_control.traffic.trace import TrafficTrace

SIMULATOR_VERSION = "event-v3-arrival-cooldown"


def region_targets(floors: int) -> list[int]:
    # Same quotient/remainder partition as numpy.array_split; lower median.
    values = list(range(2, floors + 1))
    q, r = divmod(len(values), 3)
    result = [1]
    cursor = 0
    for i in range(3):
        n = q + (i < r)
        zone = values[cursor : cursor + n]
        result.append(zone[(n - 1) // 2] if zone else 1)
        cursor += n
    return result


def region_index(floor: int, floors: int) -> int:
    """Lobby=0; exact array_split membership for the non-lobby three zones."""
    if floor == 1:
        return 0
    q, r = divmod(floors - 1, 3)
    end = 1
    for index in range(3):
        end += q + (index < r)
        if floor <= end:
            return index + 1
    raise ValueError("floor outside building")


class Simulator:
    def __init__(self, config: SimulationConfig, trace: TrafficTrace, *, audit: bool = True):
        trace.validate(config)
        self.config = config.model_copy(deep=True)
        self.trace = trace
        self.passengers = trace.passengers()
        b = config.building
        self.elevators = [
            Elevator(f"E{i + 1}", b.capacity, (b.initial_floors or [1] * b.elevator_count)[i])
            for i in range(b.elevator_count)
        ]
        self.now = 0
        self.horizon = us(config.simulation.arrival_horizon_s)
        self.deadline = self.horizon + us(config.simulation.max_drain_s)
        self.events: list[tuple[int, int, int, str, object]] = []
        self.sequence = 0
        self.decision_sequence = 0
        self.current: DecisionRequest | None = None
        self.unassigned: deque[str] = deque()
        self.waiting: set[str] = set()
        self.onboard: set[str] = set()
        self.arrived: list[str] = []
        self.reviewed: set[int] = set()
        self.done = False
        self.reason: str | None = None
        self.costs = dict(wait=0.0, ride=0.0, energy=0.0, fairness=0.0)
        self.empty_distance = 0.0
        self.loaded_distance = 0.0
        self.reposition_distance = 0.0
        self.door_cycles = 0
        self.starts = 0
        self.audit = audit
        self.event_log = AuditLog()
        self.decisions = AuditLog()
        self.snapshots = AuditLog()
        self.horizon_state: dict | None = None
        self.processed_events = 0
        for record in sorted(
            trace.records, key=lambda record: (record.arrival_us, record.passenger_id)
        ):
            self._schedule(record.arrival_us, 1, "arrival", record.passenger_id)
        self._schedule(self.horizon, 2, "horizon", None)
        self._schedule(self.deadline, 3, "deadline", None)
        if audit:
            self._schedule(0, 4, "sample", None)
        self._proposals: dict[int, RouteProposal] = {}
        self._initial_processed = False
        self._continuing: set[int] = set()

    def _schedule(self, t: int, priority: int, kind: str, payload):
        if t < self.now:
            raise InvariantError("event scheduled in the past")
        self.sequence += 1
        heapq.heappush(self.events, (t, priority, self.sequence, kind, payload))

    def _log(self, kind: str, **payload):
        if self.audit:
            self.event_log.append(dict(time_us=self.now, type=kind, **payload))

    def position(self, e: Elevator) -> float:
        s = e.segment
        if s is None:
            return float(e.floor)
        f = (self.now - s.start_us) / (s.end_us - s.start_us)
        return s.from_floor + f * (s.to_floor - s.from_floor)

    def _integrate(self, t: int):
        dt = (t - self.now) / 1e6
        if dt < 0:
            raise InvariantError("clock reversal")
        self.costs["wait"] += dt * len(self.waiting)
        self.costs["ride"] += dt * len(self.onboard)
        r = self.config.reward
        for pid in sorted(self.waiting):
            age = (self.now - self.passengers[pid].arrival_us) / 1e6
            q0 = max(0.0, (age - r.long_wait_threshold_s) / r.time_scale_s) ** 2
            q1 = max(0.0, (age + dt - r.long_wait_threshold_s) / r.time_scale_s) ** 2
            self.costs["fairness"] += q1 - q0
        ph = self.config.physics
        for e in self.elevators:
            if e.phase != Phase.IDLE:
                e.busy_s += dt
                if e.segment and e.segment.purpose == "REPOSITION":
                    e.reposition_s += dt
                else:
                    e.service_s += dt
                if e.phase in (Phase.OPENING, Phase.ALIGHTING, Phase.BOARDING, Phase.CLOSING):
                    e.door_s += dt
            if e.segment:
                distance = dt * 1e6 / (e.segment.end_us - e.segment.start_us)
                e.distance_floors += distance
                if e.onboard_ids:
                    self.loaded_distance += distance
                    self.costs["energy"] += distance * ph.loaded_distance_weight
                else:
                    self.empty_distance += distance
                    self.costs["energy"] += distance * ph.empty_distance_weight
                if e.segment.purpose == "REPOSITION":
                    self.reposition_distance += distance
        self.now = t

    def _idle(self, e: Elevator) -> bool:
        return (
            e.phase == Phase.IDLE
            and not e.route
            and not e.onboard_ids
            and e.segment is None
            and e.active_stop is None
        )

    def _start_local(self, i: int):
        e = self.elevators[i]
        if e.phase != Phase.IDLE or self.now >= self.deadline:
            return
        if e.route:
            e.reposition_target = None
            target = e.route[0].floor
        elif e.reposition_target is not None and self.now < self.horizon:
            target = e.reposition_target
        else:
            e.reposition_target = None
            self._continuing.discard(i)
            return
        if target != e.floor:
            self._move(i, target, i in self._continuing)
            self._continuing.discard(i)
        elif e.route:
            self._open(i)
        else:
            e.reposition_target = None

    def _move(self, i: int, target: int, continuing: bool):
        e = self.elevators[i]
        next_floor = e.floor + (1 if target > e.floor else -1)
        duration = us(self.config.physics.seconds_per_floor)
        purpose = "SERVICE" if e.route else "REPOSITION"
        e.segment = MotionSegment(
            e.floor, next_floor, self.now, self.now + duration, purpose, e.route_version
        )
        e.phase = Phase.MOVING
        e.operation_end_us = self.now + duration
        if not continuing:
            self.starts += 1
            self.costs["energy"] += self.config.physics.start_weight
        self._schedule(self.now + duration, 0, "move", i)
        self._log("move_start", elevator=e.id, segment=asdict(e.segment))

    def _open(self, i: int):
        e = self.elevators[i]
        self._continuing.discard(i)
        e.active_stop = e.route.pop(0)
        e.route_version += 1
        ph = self.config.physics
        e.active_stop.pickup_ids.sort(key=lambda pid: (self.passengers[pid].arrival_us, pid))
        operations: list[tuple[str, str | None, int]] = []
        operations.extend(
            ("alight", p, us(ph.alight_s_per_person)) for p in e.active_stop.dropoff_ids
        )
        operations.extend(("board", p, us(ph.board_s_per_person)) for p in e.active_stop.pickup_ids)
        operations.append(("close", None, us(ph.door_close_s)))
        e.pending_operations = operations
        e.phase = Phase.OPENING
        e.operation_end_us = self.now + us(ph.door_open_s)
        self.door_cycles += 1
        self.costs["energy"] += ph.door_cycle_weight
        self._schedule(e.operation_end_us, 0, "open", (i, None))
        self._log("open_start", elevator=e.id, stop=asdict(e.active_stop))

    def _next_operation(self, i: int):
        e = self.elevators[i]
        kind, pid, duration = e.pending_operations.pop(0)
        e.phase = {"alight": Phase.ALIGHTING, "board": Phase.BOARDING, "close": Phase.CLOSING}[kind]
        e.operation_end_us = self.now + duration
        self._schedule(e.operation_end_us, 0, kind, (i, pid))

    def _physical(self, kind: str, payload):
        if kind == "move":
            i = int(payload)
            e = self.elevators[i]
            assert e.segment is not None
            self._continuing.add(i)
            completed_purpose = e.segment.purpose
            prior_reposition_target = e.reposition_target
            e.floor = e.segment.to_floor
            e.segment = None
            e.phase = Phase.IDLE
            target = e.route[0].floor if e.route else e.reposition_target
            if self.now >= self.horizon and not e.route:
                target = None
            # Defer continuation until dispatches at this timestamp have been committed.
            e.operation_end_us = self.now
            e.idle_since_us = self.now
            self._log("move_end", elevator=e.id, floor=e.floor)
            if target == e.floor:
                e.reposition_target = None
                if (
                    completed_purpose == "REPOSITION"
                    and prior_reposition_target == e.floor
                    and not e.route
                ):
                    e.next_reposition_allowed_us = max(
                        e.next_reposition_allowed_us,
                        self.now + us(self.config.reposition.cooldown_s),
                        self.now + us(self.config.reposition.idle_review_s),
                    )
                    if e.next_reposition_allowed_us < self.horizon:
                        self._schedule(e.next_reposition_allowed_us, 2, "review", i)
        else:
            i, pid = payload
            e = self.elevators[i]
            if kind == "close":
                e.active_stop = None
                e.phase = Phase.IDLE
                e.idle_since_us = self.now
                e.route_version += 1
                return
            if kind == "board":
                p = self.passengers[pid]
                if (
                    p.status != Status.WAITING_ASSIGNED
                    or p.assigned_elevator != i
                    or p.origin != e.floor
                    or len(e.onboard_ids) >= e.capacity
                ):
                    raise InvariantError("invalid boarding or capacity reservation")
                p.status = Status.ONBOARD
                p.pickup_us = self.now
                e.onboard_ids.append(pid)
                self.waiting.remove(pid)
                self.onboard.add(pid)
            elif kind == "alight":
                p = self.passengers[pid]
                if (
                    p.status != Status.ONBOARD
                    or p.destination != e.floor
                    or pid not in e.onboard_ids
                ):
                    raise InvariantError("invalid alighting")
                p.status = Status.COMPLETED
                p.finish_us = self.now
                e.onboard_ids.remove(pid)
                self.onboard.remove(pid)
            self._log(kind, elevator=e.id, passenger_id=pid)
            self._next_operation(i)

    def _process_timestamp(self):
        t = self.events[0][0]
        self._integrate(t)
        self.reviewed.clear()
        while self.events and self.events[0][0] == t:
            _, _, _, kind, payload = heapq.heappop(self.events)
            self.processed_events += 1
            if self.processed_events > self.config.simulation.max_events:
                raise InvariantError("max_events resource limit exceeded")
            if kind == "arrival":
                p = self.passengers[str(payload)]
                p.status = Status.WAITING_UNASSIGNED
                self.arrived.append(p.id)
                self.waiting.add(p.id)
                self.unassigned.append(p.id)
                self._log("arrival", passenger_id=p.id)
            elif kind == "horizon":
                self.horizon_state = self.summary()
                for e in self.elevators:
                    e.reposition_target = None
            elif kind == "deadline":
                pass
            elif kind == "review":
                pass
            elif kind == "sample":
                next_t = self.now + us(self.config.simulation.snapshot_interval_s)
                if next_t <= self.deadline:
                    self._schedule(next_t, 4, "sample", None)
            else:
                self._physical(kind, payload)

    def advance_until_decision_or_end(
        self, *, max_timestamps: int | None = None
    ) -> DecisionRequest | None:
        if self.current is not None or self.done:
            return self.current
        processed = 0
        if not self._initial_processed:
            self._initial_processed = True
            if self.events and self.events[0][0] == 0:
                self._process_timestamp()
        while True:
            if self.unassigned:
                pid = self.unassigned.popleft()
                self.decision_sequence += 1
                self.current = DecisionRequest(
                    self.decision_sequence,
                    self.now,
                    "dispatch",
                    tuple(i < len(self.elevators) for i in range(13)),
                    passenger_id=pid,
                )
                self._proposals.clear()
                return self.current
            for i in range(len(self.elevators)):
                self._start_local(i)
            if self.now < self.horizon and self.config.reposition.enabled:
                for i, e in enumerate(self.elevators):
                    if (
                        self._idle(e)
                        and i not in self.reviewed
                        and self.now >= e.next_reposition_allowed_us
                    ):
                        self.reviewed.add(i)
                        self.decision_sequence += 1
                        targets = [e.floor] + region_targets(self.config.building.floor_count)
                        seen = set()
                        mask = [False] * 8
                        for target in targets:
                            mask.append(target not in seen)
                            seen.add(target)
                        self.current = DecisionRequest(
                            self.decision_sequence,
                            self.now,
                            "reposition",
                            tuple(mask),
                            subject_elevator_id=i,
                        )
                        return self.current
            if self.audit:
                snap = self.snapshot()
                if not self.snapshots or self.snapshots[-1] != snap:
                    self.snapshots.append(snap)
            clean = (
                not self.waiting and not self.onboard and all(self._idle(e) for e in self.elevators)
            )
            if self.now >= self.horizon and clean:
                self.done, self.reason = True, "completed"
                return None
            if self.now >= self.deadline:
                self.done, self.reason = True, "drain_timeout"
                return None
            if not self.events:
                raise InvariantError("nonterminal empty event queue")
            if max_timestamps is not None and processed >= max_timestamps:
                return None
            self._process_timestamp()
            processed += 1

    def apply_action(self, decision_id: int, action: int):
        d = self.current
        if d is None or d.decision_id != decision_id:
            raise ValueError("stale or duplicate decision")
        if not 0 <= action < 13 or not d.action_mask[action]:
            raise ValueError("illegal action")
        if d.kind == "dispatch":
            assert d.passenger_id is not None
            p = self.passengers[d.passenger_id]
            e = self.elevators[action]
            proposal = self.proposal(action)
            if proposal.base_route_version != e.route_version:
                self._proposals.pop(action, None)
                proposal = self.proposal(action)
            e.route = list(proposal.route)
            e.reposition_target = None
            e.route_version += 1
            p.assigned_elevator = action
            p.assigned_us = self.now
            p.status = Status.WAITING_ASSIGNED
        else:
            i = d.subject_elevator_id
            assert i is not None
            e = self.elevators[i]
            if not self._idle(e):
                raise InvariantError("reposition subject is no longer idle")
            cooldown = max(
                us(self.config.reposition.cooldown_s), us(self.config.reposition.idle_review_s)
            )
            e.next_reposition_allowed_us = self.now + cooldown
            if e.next_reposition_allowed_us < self.horizon:
                self._schedule(e.next_reposition_allowed_us, 2, "review", i)
            if action > 8:
                e.reposition_target = region_targets(self.config.building.floor_count)[action - 9]
                e.route_version += 1
                self._start_local(i)
        if self.audit:
            self.decisions.append(
                dict(
                    decision_id=d.decision_id,
                    time_us=self.now,
                    kind=d.kind,
                    action=action,
                    passenger_id=d.passenger_id,
                    origin_floor=self.passengers[d.passenger_id].origin if d.passenger_id else None,
                    destination_floor=self.passengers[d.passenger_id].destination
                    if d.passenger_id
                    else None,
                    eta_s={
                        self.elevators[i].id: (proposal.pickup_us - self.now) / 1e6
                        for i, proposal in self._proposals.items()
                    }
                    if d.kind == "dispatch"
                    else {},
                    subject_elevator_id=d.subject_elevator_id,
                    action_mask=d.action_mask,
                )
            )
        self.current = None

    def proposal(self, index: int) -> RouteProposal:
        d = self.current
        if d is None or d.kind != "dispatch" or d.passenger_id is None:
            raise ValueError("ETA requires a dispatch decision")
        e = self.elevators[index]
        cached = self._proposals.get(index)
        if cached is None or cached.base_route_version != e.route_version:
            cached = propose(
                e, self.passengers[d.passenger_id], self.now, self.passengers, self.config.physics
            )
            self._proposals[index] = cached
        return cached

    def summary(self) -> dict:
        picked = [p for p in self.passengers.values() if p.pickup_us is not None]
        completed = [p for p in self.passengers.values() if p.finish_us is not None]
        waits = [(p.pickup_us - p.arrival_us) / 1e6 for p in picked if p.pickup_us is not None]
        ordered = sorted(waits)
        rank = 0.95 * (len(ordered) - 1) if ordered else 0
        low = int(rank)
        p95 = (
            ordered[low] + (rank - low) * (ordered[min(low + 1, len(ordered) - 1)] - ordered[low])
            if ordered
            else None
        )
        return dict(
            time_s=self.now / 1e6,
            arrived_count=len(self.arrived),
            waiting_count=len(self.waiting),
            onboard_count=len(self.onboard),
            picked_count=len(picked),
            completed_count=len(completed),
            mean_wait_picked_s=sum(waits) / len(waits) if waits else None,
            p95_wait_picked_s=p95,
            max_wait_picked_s=max(waits) if waits else None,
            long_wait_ratio=sum(w > self.config.metrics.long_wait_threshold_s for w in waits)
            / len(waits)
            if waits
            else None,
            throughput_per_min=sum(
                p.finish_us is not None and p.finish_us <= self.horizon for p in completed
            )
            / (self.horizon / 60e6),
            longest_current_wait_s=max(
                ((self.now - self.passengers[p].arrival_us) / 1e6 for p in self.waiting), default=0
            ),
            distance_floors=sum(e.distance_floors for e in self.elevators),
            energy_proxy=self.costs["energy"],
            costs=self.costs.copy(),
        )

    def snapshot(self) -> dict:
        floors = []
        for floor in range(1, self.config.building.floor_count + 1):
            ps = [
                self.passengers[p]
                for p in sorted(self.waiting)
                if self.passengers[p].origin == floor
            ]
            floors.append(
                dict(
                    floor=floor,
                    up_count=sum(p.destination > p.origin for p in ps),
                    down_count=sum(p.destination < p.origin for p in ps),
                    max_wait_s=max(((self.now - p.arrival_us) / 1e6 for p in ps), default=0),
                )
            )
        elevators = []
        for e in self.elevators:
            target = e.route[0].floor if e.route else e.reposition_target
            elevators.append(
                dict(
                    id=e.id,
                    position_floor=self.position(e),
                    at_floor=e.floor if e.segment is None else None,
                    direction="UP"
                    if e.segment and e.segment.to_floor > e.segment.from_floor
                    else "DOWN"
                    if e.segment
                    else "IDLE",
                    load=len(e.onboard_ids),
                    capacity=e.capacity,
                    has_service=bool(e.route or e.active_stop or e.onboard_ids),
                    target_floor=target,
                    phase=e.phase.value,
                    purpose=e.segment.purpose
                    if e.segment
                    else "SERVICE"
                    if e.active_stop or e.route
                    else None,
                    distance_floors=e.distance_floors,
                    segment=asdict(e.segment) if e.segment else None,
                )
            )
        return dict(
            schema_version=1,
            sim_time_s=self.now / 1e6,
            elevators=elevators,
            floor_queues=floors,
            metrics=self.summary(),
            decision=asdict(self.current) if self.current else None,
            recent_decisions=self.decisions[-20:],
        )

    def assert_invariants(self):
        arrived = set(self.arrived)
        completed = {p.id for p in self.passengers.values() if p.status == Status.COMPLETED}
        if (
            self.waiting & self.onboard
            or self.waiting & completed
            or self.onboard & completed
            or arrived != self.waiting | self.onboard | completed
        ):
            raise InvariantError("passenger conservation")
        ids = [p for e in self.elevators for p in e.onboard_ids]
        if len(ids) != len(set(ids)) or set(ids) != self.onboard:
            raise InvariantError("onboard conservation")
        for e in self.elevators:
            if len(e.onboard_ids) > e.capacity:
                raise InvariantError("capacity exceeded")
            if e.segment and (e.phase != Phase.MOVING or e.active_stop is not None):
                raise InvariantError("door/motion conflict")
