"""Local single-user HTTP/WS application; simulation lives in independent workers."""

import asyncio
import csv
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from elevator_control.backend.manager import ConflictError, JobManager, ResourceError
from elevator_control.config.schema import (
    ControllerConfig,
    Schema,
    SimulationConfig,
    canonical_hash,
)
from elevator_control.domain.models import us
from elevator_control.storage.artifacts import atomic_json
from elevator_control.traffic.trace import Record, TrafficTrace, generate

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class TraceBody(Schema):
    config: dict = Field(default_factory=dict)
    csv_text: str | None = None


class SimulationBody(Schema):
    config: dict = Field(default_factory=dict)
    trace_id: str | None = None
    controller: ControllerConfig | None = None
    speed_multiplier: Literal[0, 1, 5, 20] = 0


class CommandBody(Schema):
    command_id: str = Field(min_length=1, max_length=120)
    type: Literal["start", "pause", "resume", "reset", "stop", "speed"]
    payload: dict = Field(default_factory=dict)


class ExperimentBody(Schema):
    suite: dict
    model_ids: list[str] = Field(default_factory=list)


def public_config(value: dict) -> SimulationConfig:
    cfg = SimulationConfig.model_validate(value)
    b = cfg.building
    for name, boundary_value, lower, upper in [
        ("floor_count", b.floor_count, 5, 30),
        ("elevator_count", b.elevator_count, 2, 8),
        ("capacity", b.capacity, 6, 20),
    ]:
        if not lower <= boundary_value <= upper:
            raise ValueError(f"building.{name} must be {lower}..{upper}")
    return cfg


def _id(value: str) -> str:
    if not value or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value
    ):
        raise ValueError("invalid ID")
    return value


def trace_signature(cfg: SimulationConfig) -> str:
    return canonical_hash(
        dict(
            floors=cfg.building.floor_count,
            horizon=cfg.simulation.arrival_horizon_s,
            seed=cfg.seed,
            traffic=cfg.traffic.model_dump(mode="json"),
        )
    )


def create_app(
    artifact_root: str | Path | None = None, *, max_workers: int | None = None
) -> FastAPI:
    root = Path(
        artifact_root or os.environ.get("ELEVATOR_ARTIFACTS", str(PROJECT_ROOT / "artifacts"))
    ).resolve()
    if not root.is_relative_to(PROJECT_ROOT):
        raise ValueError("artifacts must remain within project directory")

    @asynccontextmanager
    async def lifespan(app):
        app.state.manager = JobManager(
            root, max_workers=max_workers or int(os.environ.get("ELEVATOR_MAX_WORKERS", "2"))
        )
        yield
        app.state.manager.close()

    app = FastAPI(title="Elevator Group Control", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, error: ValueError):
        code = (
            409
            if isinstance(error, ConflictError)
            else 429
            if isinstance(error, ResourceError)
            else 422
        )
        return JSONResponse(
            status_code=code,
            content=dict(
                code=type(error).__name__,
                message=str(error),
                details=[],
                request_id=uuid.uuid4().hex,
            ),
        )

    @app.exception_handler(KeyError)
    async def missing(request: Request, error: KeyError):
        return JSONResponse(
            status_code=404,
            content=dict(
                code="not_found", message=str(error), details=[], request_id=uuid.uuid4().hex
            ),
        )

    @app.exception_handler(FileNotFoundError)
    async def missing_file(request: Request, error: FileNotFoundError):
        return JSONResponse(
            status_code=404,
            content=dict(
                code="not_found",
                message="Artifact or model not found",
                details=[],
                request_id=uuid.uuid4().hex,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=dict(
                code="validation_error",
                message="Invalid request fields",
                details=jsonable_encoder(error.errors(), custom_encoder={ValueError: str}),
                request_id=uuid.uuid4().hex,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        return JSONResponse(
            status_code=error.status_code,
            content=dict(
                code="http_error",
                message=str(error.detail),
                details=[],
                request_id=uuid.uuid4().hex,
            ),
        )

    def manager() -> JobManager:
        return app.state.manager

    @app.get("/api/v1/health")
    def health():
        return dict(
            schema_version=1,
            version="0.1.0",
            ready=True,
            workers=len(manager().active),
            queued=len(manager().pending),
        )

    @app.get("/api/v1/config/defaults")
    def defaults():
        return dict(
            schema_version=1,
            config=SimulationConfig().model_dump(mode="json"),
            schema=SimulationConfig.model_json_schema(),
            ranges=dict(floors=[5, 30], elevators=[2, 8], capacity=[6, 20]),
            controllers=["round_robin", "eta", "eta_zone", "ppo"],
        )

    @app.post("/api/v1/config/validate")
    def validate_config(value: dict):
        cfg = public_config(value)
        return dict(
            schema_version=1, normalized_config=cfg.model_dump(mode="json"), field_errors=[]
        )

    def save_trace(cfg: SimulationConfig, trace: TrafficTrace) -> dict:
        trace.validate(cfg)
        id = "trace-" + trace.sha256[:20]
        trace.save(root / "traces" / f"{id}.csv")
        metadata = dict(
            schema_version=1,
            trace_id=id,
            hash=trace.sha256,
            count=len(trace.records),
            seed=cfg.seed,
            signature=trace_signature(cfg),
            config=cfg.model_dump(mode="json"),
        )
        atomic_json(root / "traces" / f"{id}.metadata.json", metadata)
        return metadata

    @app.post("/api/v1/traces")
    def create_trace(body: TraceBody):
        cfg = public_config(body.config)
        if body.csv_text is not None:
            reader = csv.DictReader(io.StringIO(body.csv_text))
            if reader.fieldnames != [
                "passenger_id",
                "arrival_time",
                "origin_floor",
                "destination_floor",
            ]:
                raise ValueError("invalid CSV schema")
            trace = TrafficTrace(
                tuple(
                    Record(
                        r["passenger_id"],
                        us(float(r["arrival_time"])),
                        int(r["origin_floor"]),
                        int(r["destination_floor"]),
                    )
                    for r in reader
                ),
                cfg.seed,
            )
        else:
            trace = generate(cfg)
        return save_trace(cfg, trace)

    @app.get("/api/v1/traces/{id}")
    def get_trace(id: str):
        return json.loads((root / "traces" / f"{_id(id)}.metadata.json").read_text())

    @app.get("/api/v1/traces")
    def traces():
        return dict(
            items=[
                json.loads(p.read_text()) for p in sorted((root / "traces").glob("*.metadata.json"))
            ][-100:]
        )

    @app.post("/api/v1/simulations")
    def create_simulation(body: SimulationBody):
        cfg = public_config(body.config)
        if body.controller is not None:
            cfg.controller = body.controller
        if cfg.controller.name == "ppo":
            from elevator_control.rl.checkpoint import load_model

            try:
                _, metadata = load_model(str(cfg.controller.model_id), root / "models")
            except FileNotFoundError as error:
                raise ValueError("controller.model_id is not registered") from error
            if (
                cfg.building.floor_count > metadata["support"]["max_floors"]
                or cfg.building.elevator_count > metadata["support"]["max_elevators"]
            ):
                raise ValueError("model incompatible with building")
        if body.trace_id:
            metadata = get_trace(body.trace_id)
            if metadata["signature"] != trace_signature(cfg):
                raise ValueError(
                    "trace traffic/seed/horizon/floors mismatch; load trace config explicitly"
                )
        else:
            metadata = save_trace(cfg, generate(cfg))
        payload = dict(
            config=cfg.model_dump(mode="json"),
            trace_id=metadata["trace_id"],
            trace_path=str(root / "traces" / f"{metadata['trace_id']}.csv"),
            speed_multiplier=body.speed_multiplier,
        )
        id = manager().create("simulation", payload)
        return dict(
            schema_version=1,
            run_id=id,
            status="CREATED",
            trace_id=metadata["trace_id"],
            ws_url=f"/ws/v1/simulations/{id}",
        )

    @app.get("/api/v1/simulations")
    def simulations(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return dict(
            schema_version=1,
            items=manager().repo.list("simulation", offset=offset, limit=limit),
            cursor=offset + limit,
        )

    @app.get("/api/v1/simulations/{id}")
    def simulation(id: str):
        return manager().repo.get(_id(id))

    @app.get("/api/v1/simulations/{id}/snapshot")
    def snapshot(id: str):
        job = simulation(id)
        return job["snapshot"] or dict(
            schema_version=1,
            status=job["status"],
            run_id=id,
            sequence=0,
            elevators=[],
            floor_queues=[],
            metrics={},
        )

    @app.post("/api/v1/simulations/{id}/commands")
    def command(id: str, body: CommandBody):
        return manager().command(_id(id), body.command_id, body.type, body.payload)

    @app.get("/api/v1/simulations/{id}/metrics")
    def metrics(id: str):
        job = simulation(id)
        path = root / "runs" / _id(id) / "metrics.json"
        return (
            json.loads(path.read_text())
            if path.exists()
            else (job["snapshot"] or {}).get("metrics", {})
        )

    @app.get("/api/v1/simulations/{id}/timeseries")
    def timeseries(id: str, limit: int = Query(500, ge=2, le=1000)):
        """Sample archived snapshots with bounded memory, retaining actual endpoints."""
        simulation(id)
        path = root / "runs" / _id(id) / "metrics_timeseries.csv"
        if not path.exists():
            return dict(schema_version=1, available=False, total=0, items=[])
        with path.open(newline="") as stream:
            count = sum(1 for _ in csv.DictReader(stream))
        indices = (
            set(range(count))
            if count <= limit
            else {i * (count - 1) // (limit - 1) for i in range(limit)}
        )
        items = []
        with path.open(newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream)):
                if index in indices:
                    items.append(
                        dict(
                            time=float(row["timestamp"]),
                            wait=float(row["mean_wait_picked_s"])
                            if row["mean_wait_picked_s"]
                            else None,
                        )
                    )
        return dict(schema_version=1, available=True, total=count, items=items)

    @app.get("/api/v1/simulations/{id}/passengers")
    def passengers(
        id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        status: str | None = None,
        floor: int | None = None,
    ):
        simulation(id)
        path = root / "runs" / _id(id) / "passengers.csv"
        if not path.exists():
            return manager().query_passengers(
                id, dict(offset=offset, limit=limit, status=status, floor=floor)
            )
        frame = pd.read_csv(path).astype(object).where(pd.notnull(pd.read_csv(path)), None)
        if status:
            frame = pd.DataFrame(frame[frame.status == status])
        if floor:
            frame = pd.DataFrame(frame[frame.origin_floor == floor])
        return dict(
            items=frame.iloc[offset : offset + limit].to_dict(orient="records"),
            cursor=offset + limit,
            available=True,
        )

    @app.get("/api/v1/simulations/{id}/artifacts")
    def artifacts(id: str):
        simulation(id)
        folder = root / "runs" / _id(id)
        return dict(
            items=[
                dict(
                    id=f"{id}:{p.name}",
                    name=p.name,
                    size=p.stat().st_size,
                    url=f"/api/v1/artifacts/{id}:{p.name}",
                )
                for p in sorted(folder.glob("*"))
                if p.is_file() and not p.name.endswith(".tmp")
            ]
        )

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        id, sep, name = artifact_id.partition(":")
        if (
            not sep
            or Path(name).name != name
            or name.startswith(".")
            or "/" in name
            or "\\" in name
        ):
            raise ValueError("invalid artifact ID")
        job = manager().repo.get(_id(id))
        category = "runs" if job["kind"] == "simulation" else "experiments"
        folder = root / category / id
        if category == "experiments" and name.startswith("run~"):
            parts = name.split("~")
            if len(parts) != 3 or Path(parts[2]).name != parts[2]:
                raise ValueError("invalid run artifact ID")
            path = (folder / "runs" / _id(parts[1]) / parts[2]).resolve()
        elif category == "experiments" and name.startswith("figure~"):
            path = (folder / "figures" / name.removeprefix("figure~")).resolve()
        else:
            path = (folder / name).resolve()
        if not path.is_relative_to(root / category / id) or not path.is_file():
            raise KeyError(artifact_id)
        return FileResponse(path, filename=path.name)

    @app.post("/api/v1/experiments")
    def create_experiment(body: ExperimentBody):
        if not body.suite.get("scenarios") or len(body.suite["scenarios"]) > 200:
            raise ValueError("suite requires 1..200 scenarios")
        total = 0
        for scenario in body.suite["scenarios"]:
            public_config(scenario["config"])
            total += len(scenario.get("seeds", [9001, 9002]))
        if total > 2000:
            raise ResourceError("suite trace limit exceeded")
        id = manager().create("experiment", body.model_dump())
        manager().command(id, uuid.uuid4().hex, "start", {})
        return dict(schema_version=1, experiment_id=id, status="QUEUED")

    @app.get("/api/v1/experiments")
    def experiments():
        return dict(items=manager().repo.list("experiment"))

    @app.get("/api/v1/experiments/{id}")
    def experiment(id: str):
        value = manager().repo.get(_id(id))
        path = root / "experiments" / id / "manifest.json"
        if path.exists():
            value["progress"] = json.loads(path.read_text())
        return value

    @app.get("/api/v1/experiments/{id}/results")
    def experiment_results(id: str):
        experiment(id)
        folder = root / "experiments" / id
        tables = {}
        for name in ["runs", "confidence_intervals", "paired_differences"]:
            path = folder / f"{name}.csv"
            tables[name] = (
                pd.read_csv(path)
                .astype(object)
                .where(pd.notnull(pd.read_csv(path)), None)
                .to_dict(orient="records")
                if path.exists() and path.stat().st_size > 2
                else []
            )
        return dict(
            schema_version=1,
            tables=tables,
            distributions=json.loads((folder / "distributions.json").read_text())
            if (folder / "distributions.json").exists()
            else [],
            report_url=f"/api/v1/artifacts/{id}:report.md",
            warnings=["Only complete nonempty cohorts enter rankings. Energy is a proxy."],
        )

    @app.get("/api/v1/experiments/{id}/runs/{run_id}")
    def experiment_run(id: str, run_id: str):
        experiment(id)
        folder = root / "experiments" / _id(id) / "runs" / _id(run_id)
        return dict(
            manifest=json.loads((folder / "manifest.json").read_text()),
            config=json.loads((folder / "config.json").read_text()),
            metrics=json.loads((folder / "metrics.json").read_text()),
            snapshot=json.loads((folder / "snapshot.json").read_text()),
            artifacts=[
                dict(name=p.name, url=f"/api/v1/artifacts/{id}:run~{run_id}~{p.name}")
                for p in sorted(folder.glob("*"))
                if p.is_file() and not p.name.endswith(".tmp")
            ],
        )

    @app.get("/api/v1/models")
    def models():
        return dict(
            items=[
                json.loads(p.read_text()) for p in sorted((root / "models").glob("*/metadata.json"))
            ]
        )

    @app.get("/api/v1/training-runs")
    def training_runs():
        return dict(
            items=[
                dict(
                    id=p.parent.name,
                    progress=json.loads(p.read_text()),
                    config=json.loads((p.parent / "config.json").read_text()),
                )
                for p in sorted((root / "training").glob("*/progress.json"))
            ]
        )

    @app.get("/api/v1/training-runs/{id}/curves")
    def training_curves(id: str):
        folder = root / "training" / _id(id)
        if not folder.exists():
            raise KeyError(id)
        series = {}
        for name in ["updates", "validation"]:
            path = folder / f"{name}.csv"
            if path.exists():
                frame = pd.read_csv(path)
                if len(frame) > 1000:
                    frame = frame.iloc[[i * (len(frame) - 1) // 999 for i in range(1000)]]
                series[name] = (
                    frame.astype(object).where(pd.notnull(frame), None).to_dict(orient="records")
                )
            else:
                series[name] = []
        return dict(schema_version=1, series=series)

    @app.websocket("/ws/v1/simulations/{id}")
    async def websocket(socket: WebSocket, id: str):
        await socket.accept()
        try:
            sequence = -1
            notification_sequence = 0
            while True:
                job = simulation(id)
                value = snapshot(id)
                value = {
                    **value,
                    "status": job["status"],
                    "run_id": id,
                    "type": "error"
                    if job["status"] == "FAILED"
                    else "completed"
                    if job["status"] in ("COMPLETED", "STOPPED")
                    else "snapshot",
                }
                if value.get("sequence", 0) != sequence or job["status"] in (
                    "COMPLETED",
                    "STOPPED",
                    "FAILED",
                ):
                    await socket.send_json(value)
                    sequence = value.get("sequence", 0)
                else:
                    await socket.send_json(
                        dict(type="heartbeat", run_id=id, status=job["status"], sequence=sequence)
                    )
                for notification in manager().events_since(id, notification_sequence):
                    await socket.send_json(notification)
                    notification_sequence = notification["notification_sequence"]
                if job["status"] in ("COMPLETED", "STOPPED", "FAILED"):
                    break
                await asyncio.sleep(0.1)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except KeyError:
            await socket.send_json(dict(type="error", message="run not found"))
            await socket.close(code=1008)

    dist = PROJECT_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
