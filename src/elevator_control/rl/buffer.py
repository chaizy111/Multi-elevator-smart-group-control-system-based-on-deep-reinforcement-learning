"""Actual-time GAE with separate bootstrap and episode-continuation masks."""

import numpy as np


def generalized_advantages(
    rewards,
    values,
    next_values,
    delta_t,
    terminated,
    boundaries,
    *,
    gamma=0.99,
    lam=0.95,
    dt_ref=10.0,
):
    rewards, values, next_values, delta_t = [
        np.asarray(x, dtype=np.float64) for x in (rewards, values, next_values, delta_t)
    ]
    terminated, boundaries = [np.asarray(x, dtype=bool) for x in (terminated, boundaries)]
    advantages = np.zeros_like(rewards)
    carry = np.zeros(rewards.shape[1:] or ())
    for k in range(len(rewards) - 1, -1, -1):
        discount = gamma ** (delta_t[k] / dt_ref)
        trace = lam ** (delta_t[k] / dt_ref)
        delta = rewards[k] + discount * (~terminated[k]) * next_values[k] - values[k]
        carry = delta + discount * trace * (~boundaries[k]) * carry
        advantages[k] = carry
    return advantages.astype(np.float32), (advantages + values).astype(np.float32)
