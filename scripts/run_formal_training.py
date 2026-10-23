"""Independent training with explicit resource override; only parent registers models."""

import argparse
import json
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml

from elevator_control.rl.checkpoint import register
from elevator_control.rl.trainer import TrainingConfig, train
from elevator_control.storage.artifacts import atomic_json


def train_task(name: str) -> str:
    cfg = TrainingConfig.model_validate(
        yaml.safe_load(Path(f"configs/training/{name}.yaml").read_text())
    )
    output = Path("artifacts/training") / name
    progress = output / "progress.json"
    if not progress.exists() or json.loads(progress.read_text())["status"] != "COMPLETED":
        checkpoint = output / "checkpoints/last.pt"
        train(cfg, output, resume=str(checkpoint) if checkpoint.exists() else None)
    return str(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, choices=[1, 2, 3], default=1)
    args = parser.parse_args()
    tasks = [(f"formal-{seed}", f"ppo-seed{seed}") for seed in [101, 202, 303]]
    tasks += [(name, f"ppo-{name}") for name in ["dispatch-only", "no-attention", "no-fairness"]]
    atomic_json(
        Path("artifacts/training/execution.json"),
        dict(
            training_workers=args.workers,
            torch_threads_per_worker=1,
            seeds=[101, 202, 303],
            budgets={name: 60000 for name, _ in tasks},
            note="explicit override; default remains one training process; coordinator alone registers models",
        ),
    )

    def publish(output, model_id):
        if not (Path("artifacts/models") / model_id).exists():
            register(Path(output) / "checkpoints/best.pt", model_id)

    if args.workers == 1:
        for name, model_id in tasks:
            publish(train_task(name), model_id)
    else:
        with ProcessPoolExecutor(
            max_workers=args.workers, mp_context=mp.get_context("spawn")
        ) as pool:
            futures = {pool.submit(train_task, name): model_id for name, model_id in tasks}
            for future in as_completed(futures):
                publish(future.result(), futures[future])


if __name__ == "__main__":
    main()
