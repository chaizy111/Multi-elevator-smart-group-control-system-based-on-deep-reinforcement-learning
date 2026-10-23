import numpy as np

from elevator_control.config.schema import canonical_hash
from elevator_control.rl.trainer import HELD_OUT, TrainingConfig, sample_config


def test_domain_sampler_holds_out_and_reproducible():
    cfg = TrainingConfig(domain_randomization=True)
    a, b = np.random.default_rng(42), np.random.default_rng(42)
    configurations = []
    for _ in range(200):
        x, y = sample_config(cfg, a), sample_config(cfg, b)
        assert canonical_hash(x) == canonical_hash(y)
        assert (x.building.floor_count, x.building.elevator_count) not in HELD_OUT
        assert 5 <= x.building.floor_count <= 20
        assert 2 <= x.building.elevator_count <= 6
        configurations.append(
            (x.building.floor_count, x.building.elevator_count, x.traffic.pattern)
        )
    assert len(set(configurations)) > 100
