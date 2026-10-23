"""CLI/script coordinator indexing; deliberately never called by calculation workers."""

import json
import os
from pathlib import Path

from elevator_control.storage.repository import Repository


def index_experiment(output: Path, suite: dict, *, status: str):
    root = output.resolve().parent.parent
    if output.resolve().parent.name != "experiments":
        return
    repo = Repository(root / "index.sqlite3")
    try:
        repo.get(output.name)
    except KeyError:
        repo.create(output.name, "experiment", dict(suite=suite, model_ids=[]))
    value = repo.get(output.name)["config"]
    value["owner_pid"] = os.getpid()
    repo.update(output.name, status=status, config=value)


def index_run(path: Path):
    if path.resolve().parent.name != "runs":
        return
    root = path.resolve().parent.parent
    repo = Repository(root / "index.sqlite3")
    manifest = json.loads((path / "manifest.json").read_text())
    config = json.loads((path / "config.json").read_text())
    payload = dict(
        config=config,
        trace_id="trace-" + manifest["trace_hash"][:20],
        trace_path=str((path / "input_trace.csv").resolve()),
        speed_multiplier=0,
    )
    try:
        repo.get(path.name)
    except KeyError:
        repo.create(path.name, "simulation", payload)
    snapshot = dict(
        **json.loads((path / "snapshot.json").read_text()),
        run_id=path.name,
        sequence=1,
        status=manifest["status"],
        speed_multiplier=0,
        final_metrics=json.loads((path / "metrics.json").read_text()),
    )
    repo.update(path.name, status=manifest["status"], snapshot=snapshot)
