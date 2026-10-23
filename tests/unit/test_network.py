import numpy as np
import pytest
import torch

from elevator_control.config.schema import SimulationConfig
from elevator_control.env.environment import ElevatorEnv
from elevator_control.rl.buffer import generalized_advantages
from elevator_control.rl.checkpoint import VERSIONS, check_versions
from elevator_control.rl.network import ActorCritic, tensor_observations


def observation(f=12, e=4):
    env = ElevatorEnv(
        SimulationConfig.model_validate({"building": {"floor_count": f, "elevator_count": e}})
    )
    obs, _ = env.reset(seed=1)
    return obs


@pytest.mark.parametrize("f,e", [(5, 2), (12, 4), (30, 8)])
def test_forward_backward_dual_heads(f, e):
    torch.set_num_threads(1)
    obs = observation(f, e)
    dispatch = {k: v.copy() for k, v in obs.items()}
    dispatch["decision_kind"][:] = [1, 0]
    dispatch["action_mask"][:] = False
    dispatch["action_mask"][:e] = True
    dispatch["request"][:] = [0, 1, 1, 0, 1]
    model = ActorCritic()
    batch = tensor_observations([obs, dispatch])
    dist, value = model.distribution(batch)
    assert not dist.probs[~batch["action_mask"]].any()
    loss = -dist.log_prob(torch.tensor([12, 0])).mean() + value.square().mean()
    loss.backward()
    for module in [model.dispatch, model.reposition, model.blocks, model.elevator_encoder]:
        gradients = [p.grad for p in module.parameters() if p.grad is not None]
        assert gradients and all(torch.isfinite(g).all() for g in gradients)
        assert sum(float(g.abs().sum()) for g in gradients) > 0


def test_permutation_padding_and_attention():
    torch.manual_seed(5)
    model = ActorCritic().eval()
    obs = observation()
    obs["elevators"][:4, 0] = [0.1, 0.3, 0.6, 0.9]
    obs["decision_kind"][:] = [1, 0]
    obs["action_mask"][:] = False
    obs["action_mask"][:4] = True
    obs["request"][:] = [0, 1, 1, 0, 1]
    base = tensor_observations(obs)
    perm = torch.tensor([3, 1, 0, 2, 4, 5, 6, 7])
    x = {k: v.clone() for k, v in base.items()}
    for k in ["elevators", "elevator_routes", "elevator_mask"]:
        x[k] = x[k][:, perm]
    x["action_mask"][:, :8] = x["action_mask"][:, :8][:, perm]
    with torch.no_grad():
        a, va = model(base)
        b, vb = model(x)
    torch.testing.assert_close(a[:, :8][:, perm], b[:, :8])
    torch.testing.assert_close(a[:, 8:], b[:, 8:])
    torch.testing.assert_close(va, vb)
    x = {k: v.clone() for k, v in base.items()}
    x["elevators"][:, 4:] = 99
    x["elevator_routes"][:, 4:] = 99
    x["floors"][:, 12:] = 99
    x["elevator_routes"][:, :, 12:] = 99
    with torch.no_grad():
        b, vb = model(x)
    torch.testing.assert_close(a, b)
    torch.testing.assert_close(va, vb)
    with pytest.raises(ValueError):
        check_versions({**VERSIONS, "route": "wrong"})


def test_time_gae_boundaries():
    # Zero dt, then one reference interval with natural termination.
    a, r = generalized_advantages(
        [1, 2], [0.5, 0.8], [0.8, 7], [0, 10], [False, True], [False, True], gamma=0.9, lam=0.8
    )
    np.testing.assert_allclose(a, [2.5, 1.2])
    np.testing.assert_allclose(r, [3.0, 2.0])
    # Truncation bootstraps final value but cannot carry advantage across reset.
    a, _ = generalized_advantages(
        [1, 9], [2, 0], [5, 0], [20, 0], [False, True], [True, True], gamma=0.9, lam=0.8
    )
    np.testing.assert_allclose(a, [3.05, 9], rtol=1e-6)


def test_attention_connects_other_real_elevator_to_dispatch_score():
    torch.set_num_threads(1)
    torch.manual_seed(123)
    model = ActorCritic().eval()
    obs = observation()
    obs["decision_kind"][:] = [1, 0]
    obs["action_mask"][:] = False
    obs["action_mask"][:4] = True
    obs["request"][:] = [0, 1, 1, 0, 1]
    changed = {k: v.copy() for k, v in obs.items()}
    changed["elevators"][1, 0] = 0.9
    with torch.no_grad():
        old, _ = model(tensor_observations(obs))
        new, _ = model(tensor_observations(changed))
    assert abs(float(new[0, 0] - old[0, 0])) > 1e-6
