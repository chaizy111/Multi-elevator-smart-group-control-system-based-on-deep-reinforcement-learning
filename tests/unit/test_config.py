import pytest
from pydantic import ValidationError

from elevator_control.config.schema import SimulationConfig, canonical_hash, load_config
from elevator_control.domain.models import us


@pytest.mark.parametrize("name", ["small", "demo", "large"])
def test_presets(name):
    cfg = load_config(f"configs/simulation/{name}.yaml")
    assert canonical_hash(cfg) == canonical_hash(cfg.model_dump())


@pytest.mark.parametrize(
    "patch",
    [
        {"building": {"floor_count": 31}},
        {"seed": 1.1},
        {"physics": {"seconds_per_floor": 0}},
        {"building": {"elevator_count": 9}},
        {"building": {"initial_floors": [1]}},
        {"controller": {"name": "ppo"}},
        {"traffic": {"segments": [{"start_s": 1, "end_s": 1800}]}},
    ],
)
def test_invalid(patch):
    with pytest.raises(ValidationError):
        SimulationConfig.model_validate(patch)


def test_units():
    assert us(0.00000001) == 1
    assert us(2) == 2000000


@pytest.mark.parametrize("seconds", [-1e-12, float("inf"), float("-inf"), float("nan")])
def test_invalid_microsecond_input(seconds):
    with pytest.raises(ValueError):
        us(seconds)
