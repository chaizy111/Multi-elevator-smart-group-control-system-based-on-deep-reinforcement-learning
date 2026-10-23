import json

import numpy as np
import pytest
import yaml

from elevator_control.evaluation.statistics import hierarchical_interval
from elevator_control.evaluation.suite import evaluate_suite


def test_frozen_matrix_dimensions():
    expected = {
        "standard": 5400,
        "mixed": 120,
        "generalization": 2400,
        "ablation": 1800,
        "pressure": 50,
    }
    for name, total in expected.items():
        suite = yaml.safe_load(open(f"configs/evaluation/{name}.yaml"))
        assert sum(len(s["seeds"]) * len(suite["controllers"]) for s in suite["scenarios"]) == total
        for s in suite["scenarios"]:
            assert len(s["seeds"]) == len(set(s["seeds"]))
            if name != "pressure":
                assert len(s["seeds"]) >= 20


def test_hierarchical_bootstrap():
    result = hierarchical_interval(np.full((3, 20), 2.0))
    assert result["mean"] == result["ci_low"] == result["ci_high"] == 2
    assert result["model_seeds"] == 3 and result["paired_traces"] == 20


def test_successful_cells_resume_without_rewriting(tmp_path):
    suite = {
        "controllers": ["round_robin", "eta"],
        "scenarios": [
            {
                "name": "test",
                "seeds": [9001],
                "config": {
                    "building": {"floor_count": 5, "elevator_count": 2},
                    "simulation": {"arrival_horizon_s": 20},
                },
            }
        ],
    }
    evaluate_suite(suite, tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["completed"] == manifest["total"] == 2
    path = next((tmp_path / "runs").glob("*/passengers.csv"))
    before = path.stat().st_mtime_ns
    evaluate_suite(suite, tmp_path, resume=True)
    assert path.stat().st_mtime_ns == before
    changed = {**suite, "controllers": ["eta"]}
    with pytest.raises(ValueError):
        evaluate_suite(changed, tmp_path, resume=True)
