import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from elevator_control.config.schema import SimulationConfig
from elevator_control.env.environment import CheckerDiscrete, ElevatorEnv
from elevator_control.env.observation import build_observation
from elevator_control.traffic.trace import Record, TrafficTrace


@pytest.mark.parametrize("f,e", [(5, 2), (12, 4), (30, 8)])
def test_random_legal_rollout(f, e):
    cfg = SimulationConfig.model_validate(
        {
            "building": {"floor_count": f, "elevator_count": e},
            "simulation": {"arrival_horizon_s": 60},
            "traffic": {"arrival_rate_per_min": 6},
        }
    )
    env = ElevatorEnv(cfg)
    obs, _ = env.reset(seed=123)
    rng = np.random.default_rng(5)
    total = dict(wait=0, ride=0, energy=0, fairness=0)
    while True:
        assert env.observation_space.contains(obs)
        action = int(rng.choice(np.flatnonzero(obs["action_mask"])))
        obs, r, terminated, truncated, info = env.step(action)
        assert np.isfinite(r)
        for k, v in info["reward_components"].items():
            total[k] += v
        if terminated or truncated:
            break
    assert total == pytest.approx(env.sim.costs)
    assert not obs["action_mask"].any()
    assert "final_observation" in info


def test_checker_and_illegal():
    env = ElevatorEnv(SimulationConfig.model_validate({"simulation": {"arrival_horizon_s": 60}}))
    env.action_space = CheckerDiscrete(env)
    check_env(env, skip_render_check=True)
    obs, _ = env.reset(seed=42)
    invalid = np.flatnonzero(~obs["action_mask"])[0]
    with pytest.raises(ValueError):
        env.step(invalid)


def test_future_isolation_and_padding():
    cfg = SimulationConfig()
    a, b = (
        ElevatorEnv(cfg, TrafficTrace((Record("A", 10000000, 1, 2),))),
        ElevatorEnv(cfg, TrafficTrace((Record("B", 20000000, 5, 6),))),
    )
    x, _ = a.reset(seed=1)
    y, _ = b.reset(seed=1)
    for k in x:
        np.testing.assert_array_equal(x[k], y[k])
    assert not x["elevators"][4:].any()
    assert not x["floors"][12:].any()


def test_fairness_threshold_and_split_invariance():
    cfg = SimulationConfig.model_validate(
        {
            "simulation": {"arrival_horizon_s": 100, "max_drain_s": 0},
            "physics": {"seconds_per_floor": 100},
        }
    )
    trace = TrafficTrace((Record("P", 0, 12, 1),))
    env = ElevatorEnv(cfg, trace)
    obs, _ = env.reset()
    while True:
        action = int(np.flatnonzero(obs["action_mask"])[0])
        obs, _, term, trunc, _ = env.step(action)
        if term or trunc:
            break
    assert env.sim.costs["fairness"] == pytest.approx(((100 - 60) / 60) ** 2)
    assert env.sim.costs["wait"] == 100
    assert trunc and not term
    final, _ = build_observation(env.sim)
    assert final["global"][3] > 0
