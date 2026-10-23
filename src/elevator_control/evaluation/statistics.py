"""Seed/trace hierarchical intervals, preserving trace as the paired sampling unit."""

import numpy as np


def hierarchical_interval(differences: np.ndarray, *, seed=42, iterations=2000) -> dict:
    matrix = np.asarray(differences, dtype=float)
    if matrix.ndim != 2 or not matrix.size or not np.isfinite(matrix).all():
        raise ValueError("expected finite [model_seed, paired_trace] matrix")
    k, n = matrix.shape
    rng = np.random.default_rng(seed)
    models = rng.integers(k, size=(iterations, k))
    traces = rng.integers(n, size=(iterations, k, n))
    sampled = matrix[models[:, :, None], traces].mean(axis=(1, 2))
    per_seed = matrix.mean(axis=1)
    return dict(
        model_seeds=k,
        paired_traces=n,
        mean=float(matrix.mean()),
        seed_mean_min=float(per_seed.min()),
        seed_mean_max=float(per_seed.max()),
        ci_low=float(np.percentile(sampled, 2.5)),
        ci_high=float(np.percentile(sampled, 97.5)),
        method="2000 hierarchical bootstrap: sample model seeds then paired traces",
    )
