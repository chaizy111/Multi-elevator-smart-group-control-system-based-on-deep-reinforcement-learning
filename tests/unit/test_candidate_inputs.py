"""Public consequence inputs are learned features, with strict legacy compatibility."""

import json

import numpy as np
import pytest
import torch

from elevator_control.config.schema import SimulationConfig
from elevator_control.domain.models import us
from elevator_control.env.candidates import candidate_features
from elevator_control.env.environment import ElevatorEnv
from elevator_control.rl.checkpoint import initialize_network, load_model, register, versions_for
from elevator_control.rl.network import ActorCritic, tensor_observations
from elevator_control.rl.trainer import TrainingConfig, train
from elevator_control.simulator.engine import Simulator
from elevator_control.traffic.trace import Record, TrafficTrace


def view(f=12, e=4):
    env = ElevatorEnv(
        SimulationConfig.model_validate({"building": {"floor_count": f, "elevator_count": e}}),
        candidate_inputs=True,
    )
    obs, _ = env.reset(seed=42)
    obs["decision_kind"][:] = [1, 0]
    obs["action_mask"][:] = False
    obs["action_mask"][:e] = True
    obs["request"][:] = [0, 1, 1, 0, 1]
    obs["candidates"][:e] = np.arange(e * 6).reshape(e, 6) / 10
    return obs


@pytest.mark.parametrize("f,e", [(5, 2), (12, 4), (30, 8)])
def test_migration_gradient_mask_and_permutation(f, e):
    torch.set_num_threads(1)
    torch.manual_seed(18)
    old = ActorCritic()
    new = ActorCritic(candidate_inputs=True)
    data = dict(config={}, versions=versions_for(), network=old.state_dict())
    with pytest.raises(ValueError, match="explicit"):
        initialize_network(new, data)
    initialize_network(new, data, migrate_candidate_inputs=True)
    assert sum(p.numel() for p in new.parameters()) == 427399
    obs = tensor_observations(view(f, e))
    a, va = old(obs)
    b, vb = new(obs)
    torch.testing.assert_close(a, b)
    torch.testing.assert_close(va, vb)
    dist, value = new.distribution(obs)
    assert not dist.probs[~obs["action_mask"]].any()
    (-dist.log_prob(torch.tensor([0])).mean() + value.square().mean()).backward()
    assert new.dispatch[0].weight.grad[:, 224:].abs().sum() > 0
    # Test permutation/padding with active learned-input weights, not zero migration columns.
    with torch.no_grad():
        new.dispatch[0].weight[:, 224:].normal_(std=0.05)
        b, vb = new(obs)
    perm = torch.arange(8)
    perm[:e] = torch.arange(e - 1, -1, -1)
    changed = {k: v.clone() for k, v in obs.items()}
    for k in ["elevators", "elevator_routes", "elevator_mask", "candidates"]:
        changed[k] = changed[k][:, perm]
    changed["action_mask"][:, :8] = changed["action_mask"][:, :8][:, perm]
    c, vc = new(changed)
    torch.testing.assert_close(b[:, :8][:, perm], c[:, :8])
    torch.testing.assert_close(vb, vc)
    padding = {k: v.clone() for k, v in obs.items()}
    padding["candidates"][:, e:] = 999
    d, vd = new(padding)
    torch.testing.assert_close(b, d)
    torch.testing.assert_close(vb, vd)


def test_candidates_ignore_unarrived_people_and_match_known_routes():
    cfg = SimulationConfig.model_validate(dict(building=dict(floor_count=5, elevator_count=2)))
    traces = [
        TrafficTrace((Record("known", 0, 1, 5), Record("future", us(50), 2, dest)))
        for dest in [3, 5]
    ]
    traces.append(
        TrafficTrace(
            (Record("known", 0, 1, 5), *(Record(f"future{i}", us(50 + i), 2, 3) for i in range(5)))
        )
    )
    observations = []
    for trace in traces:
        sim = Simulator(cfg, trace, audit=False)
        while sim.advance_until_decision_or_end() is not None:
            if sim.current.kind == "dispatch":
                break
            sim.apply_action(sim.current.decision_id, 8)
        result = candidate_features(sim)
        assert result.shape == (8, 6) and result.dtype == np.float32
        assert not result[2:].any()
        assert result[0, 0] == pytest.approx((sim.proposal(0).pickup_us - sim.now) / 60e6)
        observations.append(result)
    for other in observations[1:]:
        np.testing.assert_array_equal(observations[0], other)


def test_real_candidate_training_register_and_loading(tmp_path):
    cfg = TrainingConfig.model_validate(
        dict(
            seed=8,
            total_decisions=64,
            rollout_steps=32,
            epochs=1,
            candidate_inputs=True,
            simulation=dict(
                building=dict(floor_count=5, elevator_count=2),
                traffic=dict(arrival_rate_per_min=30),
                simulation=dict(arrival_horizon_s=30),
            ),
        )
    )
    env = ElevatorEnv(cfg.simulation, candidate_inputs=True)
    obs, _ = env.reset(seed=8)
    assert env.observation_space.contains(obs)
    out = train(cfg, tmp_path / "train")
    path = register(out / "checkpoints/best.pt", "candidate", tmp_path / "models")
    model, meta = load_model("candidate", tmp_path / "models")
    assert model.candidate_inputs and meta["parameter_count"] == 427399
    meta["training_config"]["candidate_inputs"] = False
    (path / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="incompatible"):
        load_model("candidate", tmp_path / "models")


def test_existing_passenger_externality_matches_independent_timeline():
    cfg = SimulationConfig.model_validate(dict(building=dict(floor_count=5, elevator_count=2)))
    sim = Simulator(
        cfg, TrafficTrace((Record("existing", 0, 1, 5), Record("new", 0, 2, 3))), audit=False
    )
    while sim.advance_until_decision_or_end() is not None:
        request = sim.current
        if request.kind == "dispatch" and request.passenger_id == "new":
            break
        sim.apply_action(request.decision_id, 0 if request.kind == "dispatch" else 8)
    assert sim.current is not None and sim.current.passenger_id == "new"
    assert [stop.floor for stop in sim.proposal(0).route] == [2, 1, 3, 5]
    # At 2 s/floor, doors 2+2 s and boarding/alighting 0.8 s:
    # old task pickup/drop/end = 2.8/15.6/17.6 s;
    # after insertion new pickup/drop = 4.8/20.4 s,
    # old pickup/drop/end = 11.6/29.2/31.2 s; distance 4 -> 6 floors.
    expected = np.array([4.8 / 60, 20.4 / 60, 2 / 10, 8.8 / 60, 13.6 / 60, 13.6 / 60])
    np.testing.assert_allclose(candidate_features(sim)[0], expected, rtol=1e-6)
    # Sending the new passenger to the idle elevator delays nobody already assigned.
    np.testing.assert_array_equal(candidate_features(sim)[1, 3:5], [0, 0])


def test_validation_rejects_invalid_limits_and_empty_cohorts():
    from elevator_control.rl.validation import summarize_validation, validation_score

    with pytest.raises(ValueError, match="positive"):
        TrainingConfig(validation_limits={"distance_floors": 0})
    empty = summarize_validation([], {"distance_floors": 10})
    assert not empty["complete"] and not empty["feasible"]
    assert validation_score(empty)[0] == float("inf")


def test_interval_pairing_and_unfinished_runs_not_ranked():
    from elevator_control.research.verify_candidate import acceptance, intervals

    labels = ["learned1", "learned2"]
    rows = []
    for label in ["eta", "eta_zone", "round_robin", "fixed-rule", "ppo-curriculum"] + labels:
        for seed in [61_000_000, 61_000_001]:
            rows.append(
                dict(
                    controller=label,
                    scenario="8F3E-normal-low",
                    seed=seed,
                    eligible_for_ranking=True,
                    mean_wait_s=9 if label in labels else 10 if label == "fixed-rule" else 20,
                    p95_wait_s=20,
                    distance_floors=100,
                )
            )
    assert acceptance(rows, labels)["passed"]
    result = intervals(rows, labels, iterations=30)
    assert result["eta"]["one_sided_9875_upper"] == pytest.approx(0.45)
    assert result["fixed-rule"]["one_sided_9875_upper"] == pytest.approx(0.9)
    rows[-1]["eligible_for_ranking"] = False
    assert not acceptance(rows, labels)["passed"]
