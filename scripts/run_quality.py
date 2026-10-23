"""Run the final checks once and retain real exit codes/logs as acceptance evidence."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from elevator_control.storage.artifacts import atomic_json


def main():
    root = Path(__file__).resolve().parents[1]
    report = root / "reports" / "quality"
    report.mkdir(parents=True, exist_ok=True)
    python = (
        str(root / ".venv/bin/python") if (root / ".venv/bin/python").exists() else sys.executable
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(root / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLCONFIGDIR": str(root / ".cache/matplotlib"),
        "XDG_CACHE_HOME": str(root / ".cache"),
        "TMPDIR": str(root / ".cache/tmp"),
        "npm_config_cache": str(root / ".cache/npm"),
        "PLAYWRIGHT_BROWSERS_PATH": str(root / ".cache/playwright"),
        "ELEVATOR_PYTHON": python,
    }
    commands = [
        ("pytest", [python, "-m", "pytest", "-q", "--junitxml=reports/quality/pytest.xml"]),
        ("ruff", [python, "-m", "ruff", "check", "."]),
        ("format", [python, "-m", "ruff", "format", "--check", "."]),
        ("pyright", [python, "-m", "pyright", "--pythonpath", python]),
        ("frontend-format", ["npm", "--prefix", "frontend", "run", "format:check"]),
        ("frontend-types", ["npm", "--prefix", "frontend", "run", "typecheck"]),
        ("frontend-unit", ["npm", "--prefix", "frontend", "run", "test"]),
        ("frontend-build", ["npm", "--prefix", "frontend", "run", "build"]),
        ("real-chain", [python, "scripts/run_acceptance.py"]),
        ("browser-e2e", ["npm", "--prefix", "frontend", "run", "test:e2e"]),
    ]
    rows = []
    for name, command in commands:
        print(f"checking {name}", flush=True)
        start = time.perf_counter()
        with (report / f"{name}.log").open("w") as stream:
            result = subprocess.run(
                command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT
            )
        rows.append(
            dict(
                name=name,
                command=command,
                exit_code=result.returncode,
                wall_seconds=time.perf_counter() - start,
                log=str(report.relative_to(root) / f"{name}.log"),
            )
        )
        atomic_json(
            report / "checks.json",
            dict(status="FAILED" if result.returncode else "RUNNING", checks=rows),
        )
        if result.returncode:
            raise RuntimeError(f"{name} failed; inspect {report / name}.log")
    atomic_json(report / "checks.json", dict(status="PASSED", checks=rows))
    print(
        json.dumps(dict(status="PASSED", checks=len(rows), evidence="reports/quality/checks.json")),
        flush=True,
    )


if __name__ == "__main__":
    main()
