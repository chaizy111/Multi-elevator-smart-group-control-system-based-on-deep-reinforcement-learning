import pytest

from elevator_control.config.schema import SimulationConfig
from elevator_control.simulator.engine import Simulator
from elevator_control.traffic.trace import Record, TrafficTrace, generate


def config(**kwargs):
    return SimulationConfig.model_validate(
        dict(
            building=dict(floor_count=3, elevator_count=1, capacity=2),
            physics=dict(board_s_per_person=1, alight_s_per_person=1),
            simulation=dict(arrival_horizon_s=10, max_drain_s=100),
            **kwargs,
        )
    )


def run(cfg, trace):
    sim = Simulator(cfg, trace)
    while d := sim.advance_until_decision_or_end():
        sim.apply_action(d.decision_id, 0 if d.kind == "dispatch" else 8)
        sim.assert_invariants()
    sim.assert_invariants()
    return sim


def test_s01_timeline():
    sim = run(config(), TrafficTrace((Record("P1", 0, 1, 3),)))
    p = sim.passengers["P1"]
    assert (p.pickup_us, p.finish_us, sim.now) == (3000000, 12000000, 14000000)
    assert sim.costs["wait"] == 3
    assert sim.costs["ride"] == 9
    assert sim.elevators[0].distance_floors == pytest.approx(2)


def test_s06_empty():
    sim = run(config(), TrafficTrace(()))
    assert sim.now == 10000000
    assert sim.summary()["mean_wait_picked_s"] is None


@pytest.mark.parametrize(
    "records",
    [
        (Record("P", 0, 1, 1),),
        (Record("P", 0, 1, 4),),
        (Record("P", 0, 1, 2), Record("P", 1, 2, 3)),
        (Record("P", -1, 1, 2),),
    ],
)
def test_s07_invalid(records):
    with pytest.raises(ValueError):
        Simulator(config(), TrafficTrace(records))


def test_same_seed_trace_and_save(tmp_path):
    cfg = config()
    a, b = generate(cfg), generate(cfg)
    assert a.bytes() == b.bytes()
    path = tmp_path / "trace.csv"
    a.save(path)
    assert TrafficTrace.load(path, cfg).sha256 == a.sha256


@pytest.mark.parametrize("pattern", ["normal", "morning", "evening", "interfloor", "burst"])
def test_patterns(pattern):
    cfg = config(traffic={"pattern": pattern, "arrival_rate_per_min": 120})
    trace = generate(cfg)
    assert len(trace.records) > 0
    if pattern == "interfloor":
        assert all(r.origin > 1 and r.destination > 1 for r in trace.records)
