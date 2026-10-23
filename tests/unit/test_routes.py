import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from elevator_control.config.schema import SimulationConfig
from elevator_control.controllers.baselines import Baseline, decision_view, run_simulation
from elevator_control.simulator.engine import Simulator
from elevator_control.simulator.route_planner import propose
from elevator_control.traffic.trace import Record, TrafficTrace, generate


def cfg(f=5, e=2, c=2, h=60, drain=600, **kwargs):
    return SimulationConfig.model_validate(
        dict(
            building=dict(floor_count=f, elevator_count=e, capacity=c),
            simulation=dict(arrival_horizon_s=h, max_drain_s=drain),
            **kwargs,
        )
    )


def test_s02_s03_capacity_eta_and_s04_order():
    config = cfg(e=1, c=2)
    trace = TrafficTrace(tuple(Record(f"P{i}", 0, 1, 5) for i in range(5)))
    sim = Simulator(config, trace)
    assert sim.advance_until_decision_or_end().kind == "dispatch"
    predicted = {}
    while d := sim.advance_until_decision_or_end():
        if d.kind == "dispatch":
            proposal = sim.proposal(0)
            full = propose(
                sim.elevators[0],
                sim.passengers[d.passenger_id],
                sim.now,
                sim.passengers,
                config.physics,
                limit=10000,
            )
            assert proposal == full
            if d.passenger_id == "P4":
                predicted[d.passenger_id] = proposal.pickup_us
        sim.apply_action(d.decision_id, 0 if d.kind == "dispatch" else 8)
        sim.assert_invariants()
    assert sim.reason == "completed"
    assert sim.passengers["P4"].pickup_us == predicted["P4"]
    assert all(p.finish_us is not None for p in sim.passengers.values())


def test_eta_during_frozen_stop_and_move():
    config = cfg(e=1)
    trace = TrafficTrace(
        (Record("A", 0, 1, 5), Record("B", 1000000, 1, 3), Record("C", 7000000, 2, 4))
    )
    sim = Simulator(config, trace)
    last_prediction = None
    while d := sim.advance_until_decision_or_end():
        if d.kind == "dispatch":
            last_prediction = sim.proposal(0).pickup_us
        sim.apply_action(d.decision_id, 0 if d.kind == "dispatch" else 8)
    assert sim.passengers["B"].pickup_us > sim.passengers["A"].pickup_us
    assert sim.passengers["C"].pickup_us == last_prediction


def test_s05_reposition_preemption():
    config = cfg(e=1)
    sim = Simulator(config, TrafficTrace((Record("P", 1000000, 1, 2),)))
    d = sim.advance_until_decision_or_end()
    sim.apply_action(d.decision_id, 12)
    d = sim.advance_until_decision_or_end()
    assert d.kind == "dispatch"
    assert sim.position(sim.elevators[0]) == 1.5
    expected = sim.proposal(0).pickup_us
    sim.apply_action(d.decision_id, 0)
    while d := sim.advance_until_decision_or_end():
        sim.apply_action(d.decision_id, 8)
    assert sim.passengers["P"].pickup_us == expected
    assert sim.reposition_distance == pytest.approx(1)


def test_stale_and_mask():
    sim = Simulator(cfg(), TrafficTrace(()))
    d = sim.advance_until_decision_or_end()
    assert d.action_mask[8] and not d.action_mask[9]
    with pytest.raises(ValueError):
        sim.apply_action(d.decision_id, 0)
    sim.apply_action(d.decision_id, 8)
    with pytest.raises(ValueError):
        sim.apply_action(d.decision_id, 8)


@pytest.mark.parametrize("f,e", [(5, 2), (12, 4), (30, 8)])
@pytest.mark.parametrize("name", ["round_robin", "eta", "eta_zone"])
def test_building_baselines(f, e, name):
    config = cfg(f, e, 6, traffic=dict(arrival_rate_per_min=6))
    sim = run_simulation(config, generate(config), Baseline(name))
    assert sim.reason == "completed"
    assert all(p.finish_us is not None for p in sim.passengers.values())


@given(st.integers(0, 10000), st.integers(2, 8), st.integers(1, 3), st.integers(1, 4))
@settings(max_examples=25, deadline=None)
def test_random_conservation(seed, f, e, c):
    config = cfg(f, e, c, h=30, seed=seed, traffic=dict(arrival_rate_per_min=20))
    trace = generate(config)
    a = run_simulation(config, trace, Baseline("eta"))
    b = run_simulation(config, trace, Baseline("eta"))
    assert a.event_log == b.event_log
    assert a.costs == b.costs
    assert a.reason == "completed"
    assert a.costs["wait"] == pytest.approx(
        sum((p.pickup_us - p.arrival_us) / 1e6 for p in a.passengers.values())
    )
    assert a.costs["ride"] == pytest.approx(
        sum((p.finish_us - p.pickup_us) / 1e6 for p in a.passengers.values())
    )


def test_decision_view_has_no_future():
    a = Simulator(cfg(), TrafficTrace((Record("A", 10000000, 1, 2),)))
    b = Simulator(cfg(), TrafficTrace((Record("B", 20000000, 3, 4),)))
    a.advance_until_decision_or_end()
    b.advance_until_decision_or_end()
    assert decision_view(a) == decision_view(b)


def test_reposition_stop_then_restart_counts_two_starts():
    config = cfg(e=1, h=90)
    sim = Simulator(config, TrafficTrace(()))
    moved = 0
    while d := sim.advance_until_decision_or_end():
        if moved < 2:
            action = 12 if moved == 0 else 9
            moved += 1
        else:
            action = 8
        sim.apply_action(d.decision_id, action)
    assert sim.starts == 2
    assert sim.door_cycles == 0
    assert sim.costs["energy"] == pytest.approx(
        sim.empty_distance + 2 * config.physics.start_weight
    )


def test_drain_cutoff_does_not_start_opening():
    # Travel reaches the pickup floor exactly at H, with no drain time remaining.
    config = cfg(e=1, h=2, drain=0)
    sim = run_simulation(config, TrafficTrace((Record("P", 0, 2, 3),)))
    assert sim.now == 2000000 and sim.reason == "drain_timeout"
    assert sim.door_cycles == 0
    assert sim.starts == 1


def test_imported_simultaneous_arrivals_use_id_tie_break():
    sim = Simulator(cfg(), TrafficTrace((Record("B", 0, 1, 2), Record("A", 0, 1, 3))))
    decision = sim.advance_until_decision_or_end()
    assert decision.passenger_id == "A"


def test_eta_zone_uses_partition_membership_instead_of_nearest_target():
    from elevator_control.controllers.baselines import DecisionView
    from elevator_control.domain.models import DecisionRequest
    from elevator_control.simulator.engine import region_index

    assert [region_index(f, 12) for f in range(1, 13)] == [0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3]
    config = cfg(f=12, e=2)
    sim = Simulator(config, TrafficTrace(()))
    d = sim.advance_until_decision_or_end()
    view = decision_view(sim)
    custom = DecisionView(
        DecisionRequest(
            d.decision_id, d.time_us, "reposition", d.action_mask, subject_elevator_id=0
        ),
        view.snapshot,
        (),
        ((0.0, 2, 12),),
    )
    assert Baseline("eta_zone").act(custom) == 10


def test_long_reposition_has_fresh_cooldown_after_arrival():
    config = cfg(f=30, e=1, h=120)
    sim = Simulator(config, TrafficTrace(()))
    decision = sim.advance_until_decision_or_end()
    sim.apply_action(decision.decision_id, 12)
    # High target=26, 50 seconds in motion; old start-based cooldown would already expire.
    next_decision = sim.advance_until_decision_or_end()
    assert sim.elevators[0].floor == 26
    assert next_decision.time_us == 80000000
    assert next_decision.kind == "reposition"
