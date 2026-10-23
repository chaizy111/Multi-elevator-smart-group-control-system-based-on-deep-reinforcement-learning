"""Run the explicitly bounded CPU curriculum; each stage has its own optimizer budget."""

import json
from pathlib import Path

import yaml

from elevator_control.rl.checkpoint import register
from elevator_control.rl.trainer import TrainingConfig, train


def main():
    previous = "artifacts/training/smoke/checkpoints/best.pt"
    for name, stage in [("t1", "T1"), ("t2", "T2"), ("curriculum", "T3")]:
        output = Path("artifacts/training") / stage.lower()
        cfg = TrainingConfig.model_validate(
            yaml.safe_load(Path(f"configs/training/{name}.yaml").read_text())
        )
        progress = output / "progress.json"
        if not progress.exists() or json.loads(progress.read_text()).get("status") != "COMPLETED":
            last = output / "checkpoints/last.pt"
            train(
                cfg,
                output,
                resume=str(last) if last.exists() else None,
                initialize=previous if not last.exists() else None,
            )
        previous = str(output / "checkpoints/best.pt")
    if not Path("artifacts/models/ppo-curriculum").exists():
        register(previous, "ppo-curriculum")


if __name__ == "__main__":
    main()
