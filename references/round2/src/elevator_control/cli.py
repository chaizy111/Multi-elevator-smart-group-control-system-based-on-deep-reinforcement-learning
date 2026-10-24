"""Installed command entry point; all services share the same simulation modules."""

from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Serve HTTP API and production frontend with one coordinator."""
    import uvicorn

    uvicorn.run("elevator_control.backend.app:create_app", factory=True, host=host, port=port)


trace_app = typer.Typer(no_args_is_help=True)
app.add_typer(trace_app, name="trace")


@trace_app.command("generate")
def trace_generate(config: str = typer.Option(...), output: str = typer.Option(...)):
    """Generate an immutable input trace and checksum metadata."""
    from elevator_control.config.schema import load_config
    from elevator_control.traffic.trace import generate

    trace = generate(load_config(config))
    trace.save(output)
    typer.echo(f"{len(trace.records)} passengers sha256={trace.sha256}")


@app.command()
def simulate(
    config: str = typer.Option(...),
    trace: str | None = None,
    controller: str = "eta",
    model_id: str | None = None,
):
    """Run a deterministic simulation using a common physical kernel."""
    import json

    from elevator_control.config.schema import load_config
    from elevator_control.controllers.baselines import Baseline, run_simulation
    from elevator_control.traffic.trace import TrafficTrace, generate

    cfg = load_config(config)
    from elevator_control.config.schema import ControllerConfig

    cfg.controller = ControllerConfig.model_validate(dict(name=controller, model_id=model_id))
    inputs = TrafficTrace.load(trace, cfg) if trace else generate(cfg)
    if controller == "ppo":
        from elevator_control.controllers.rl_controller import RLController

        if not model_id:
            raise typer.BadParameter("--model-id required for PPO")
        policy = RLController(model_id)
    else:
        policy = Baseline(controller)
    result = run_simulation(cfg, inputs, policy)
    from elevator_control.storage.artifacts import archive

    path = archive(
        result, controller_name=controller, model_hash=getattr(policy, "model_hash", None)
    )
    from elevator_control.storage.indexing import index_run

    index_run(path)
    typer.echo(
        json.dumps(dict(path=str(path), metrics=result.summary()), ensure_ascii=False, indent=2)
    )


@app.command()
def evaluate(
    suite: str = typer.Option(...),
    output: str = typer.Option(...),
    model_id: Annotated[list[str] | None, typer.Option()] = None,
    resume: bool = False,
):
    """Evaluate a reproducible paired experiment matrix."""
    from pathlib import Path

    import yaml

    from elevator_control.evaluation.suite import evaluate_suite
    from elevator_control.storage.indexing import index_experiment

    suite_value = yaml.safe_load(Path(suite).read_text())
    destination = Path(output)
    index_experiment(destination, suite_value, status="RUNNING")
    try:
        result = evaluate_suite(suite_value, destination, model_ids=model_id, resume=resume)
        index_experiment(destination, suite_value, status="COMPLETED")
        typer.echo(str(result))
    except Exception:
        index_experiment(destination, suite_value, status="FAILED")
        raise


@app.command("report")
def build_report(experiment: str = typer.Option(...)):
    from elevator_control.evaluation.suite import report

    typer.echo(str(report(experiment)))


@app.command()
def train(
    config: str | None = None,
    output: str | None = None,
    resume: str | None = None,
    initialize: str | None = None,
):
    """Train a real dual-head PPO; budgets are explicit in the configuration."""
    from pathlib import Path

    import torch
    import yaml

    from elevator_control.rl.trainer import TrainingConfig
    from elevator_control.rl.trainer import train as run_training

    if resume:
        saved = torch.load(resume, map_location="cpu", weights_only=False)
        cfg = TrainingConfig.model_validate(saved["config"])
        destination = output or str(Path(resume).parent.parent)
    elif config:
        cfg = TrainingConfig.model_validate(yaml.safe_load(Path(config).read_text()))
        destination = output or "artifacts/training/" + Path(config).stem
    else:
        raise typer.BadParameter("--config or --resume required")
    typer.echo(str(run_training(cfg, destination, resume=resume, initialize=initialize)))


model_app = typer.Typer(no_args_is_help=True)
app.add_typer(model_app, name="model")


@model_app.command("register")
def register_model(checkpoint: str = typer.Option(...), model_id: str = typer.Option(...)):
    from elevator_control.rl.checkpoint import register

    typer.echo(str(register(checkpoint, model_id)))


@app.command("benchmark")
def run_benchmark(
    config: str = typer.Option(...),
    requests: int | None = None,
    output: str = "reports/benchmark.json",
):
    """Measure actual performance; optional fixed-count long-run stability scenario."""
    import json

    from elevator_control.config.schema import load_config
    from elevator_control.evaluation.benchmark import benchmark

    typer.echo(
        json.dumps(
            benchmark(load_config(config), requests=requests, output=output),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
