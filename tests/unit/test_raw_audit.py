from elevator_control.config.schema import SimulationConfig
from elevator_control.controllers.baselines import run_simulation
from elevator_control.storage.artifacts import archive
from elevator_control.traffic.trace import Record, TrafficTrace
from scripts.audit_experiments import audit


def test_raw_csv_threshold_recomputation_uses_integer_microseconds(tmp_path):
    config = SimulationConfig.model_validate(
        {
            "building": {"floor_count": 2, "elevator_count": 1, "capacity": 1},
            "physics": {"seconds_per_floor": 57.2},
            "simulation": {"arrival_horizon_s": 200, "max_drain_s": 100},
        }
    )
    sim = run_simulation(config, TrafficTrace((Record("P", 117123456, 2, 1),)))
    assert sim.passengers["P"].pickup_us - sim.passengers["P"].arrival_us == 60000000
    path = archive(sim, tmp_path)
    assert audit(path) == 1
