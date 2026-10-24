"""Install immutable supplied models and genuine curves; never train implicitly."""

import hashlib
import json
import shutil
from pathlib import Path

from elevator_control.storage.paths import PROJECT_ROOT, artifact_root
from elevator_control.storage.repository import Repository

DEFAULT_MODEL_ID = "ppo-consequences-s801-n200000"


def prepare(root: Path | None = None) -> dict:
    """Check every payload before copying; reject changed files instead of overwriting."""
    destination = (root or artifact_root()).resolve()
    if not destination.is_relative_to(PROJECT_ROOT):
        raise ValueError("artifacts must remain within project directory")
    source = PROJECT_ROOT / "assets/release"
    manifest = json.loads((source / "manifest.json").read_text())
    pairs = []
    for row in manifest["files"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid release payload path")
        original, target = source / relative, destination / relative
        if hashlib.sha256(original.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"release checksum mismatch: {relative}")
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"existing runtime payload differs: {relative}")
        pairs.append((original, target))
    for original, target in pairs:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copyfile(original, temporary)
            temporary.replace(target)
    repository = Repository(destination / "index.sqlite3")
    for meta_path in (destination / "models").glob("*/metadata.json"):
        metadata = json.loads(meta_path.read_text())
        try:
            repository.get(metadata["model_id"])
        except KeyError:
            repository.create(metadata["model_id"], "model", metadata)
            repository.update(metadata["model_id"], status="COMPLETED")
    return dict(root=str(destination), default_model=DEFAULT_MODEL_ID, files=len(pairs))


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False))
