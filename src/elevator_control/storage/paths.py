"""One runtime namespace keeps the submission independent of development archives."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def artifact_root() -> Path:
    root = Path(os.environ.get("ELEVATOR_ARTIFACTS", PROJECT_ROOT / "artifacts/submission"))
    root = root.resolve()
    if not root.is_relative_to(PROJECT_ROOT):
        raise ValueError("artifacts must remain within project directory")
    return root
