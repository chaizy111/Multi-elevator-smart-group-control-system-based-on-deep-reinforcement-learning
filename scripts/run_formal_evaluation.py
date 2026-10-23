"""Execute every frozen cell with resumable version/model-aware caches."""

from pathlib import Path

import yaml

from elevator_control.evaluation.suite import evaluate_suite
from elevator_control.storage.indexing import index_experiment


def main():
    for name in ["standard", "mixed", "generalization", "ablation", "pressure"]:
        output = Path("artifacts/experiments") / name
        suite = yaml.safe_load(Path(f"configs/evaluation/{name}.yaml").read_text())
        index_experiment(output, suite, status="RUNNING")
        try:
            evaluate_suite(suite, output, resume=(output / "manifest.json").exists(), workers=2)
            index_experiment(output, suite, status="COMPLETED")
        except Exception:
            index_experiment(output, suite, status="FAILED")
            raise


if __name__ == "__main__":
    main()
