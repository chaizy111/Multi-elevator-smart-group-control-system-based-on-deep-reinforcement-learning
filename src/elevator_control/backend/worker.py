"""Spawn-safe worker entry points, bounded snapshots and reliable control acknowledgments."""

import json
import queue
import time
import traceback
from pathlib import Path

from elevator_control.config.schema import SimulationConfig
from elevator_control.controllers.baselines import Baseline, apply_controller_action
from elevator_control.evaluation.metrics import calculate
from elevator_control.simulator.engine import Simulator
from elevator_control.storage.artifacts import archive, atomic_json, passenger_rows
from elevator_control.traffic.trace import TrafficTrace


def _snapshot_put(channel, value):
    try:
        channel.put_nowait(value)
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        try:
            channel.put_nowait(value)
        except queue.Full:
            pass


def simulation_worker(job_id: str, payload: dict, root: str, controls, updates, snapshots):
    path = Path(root) / "runs" / job_id
    sim = None
    try:
        cfg = SimulationConfig.model_validate(payload["config"])
        trace = TrafficTrace.load(payload["trace_path"], cfg)
        if cfg.controller.name == "ppo":
            from elevator_control.controllers.rl_controller import RLController

            controller = RLController(str(cfg.controller.model_id), root=str(Path(root) / "models"))
        else:
            controller = Baseline(cfg.controller.name)
        controller.reset(cfg, cfg.seed)
        sim = Simulator(cfg, trace)
        speed = float(payload.get("speed_multiplier", 0))
        paused = False
        stopped = False
        sequence = 0
        last_send = 0.0
        wall_anchor = time.monotonic()
        sim_anchor = sim.now / 1e6
        updates.put(dict(type="status_changed", status="RUNNING"))
        while not sim.done and not stopped:
            while True:
                try:
                    command = controls.get_nowait()
                except queue.Empty:
                    break
                kind = command["type"]
                if kind == "passengers_query":
                    filters = command["payload"]
                    rows = [p for p in passenger_rows(sim) if p["arrival_time"] <= sim.now / 1e6]
                    if filters.get("status"):
                        rows = [p for p in rows if p["status"] == filters["status"]]
                    if filters.get("floor"):
                        rows = [p for p in rows if p["origin_floor"] == filters["floor"]]
                    offset, limit = filters["offset"], filters["limit"]
                    updates.put(
                        dict(
                            type="passengers_result",
                            request_id=command["command_id"],
                            result=dict(
                                items=rows[offset : offset + limit],
                                cursor=offset + limit,
                                available=True,
                            ),
                        )
                    )
                    continue
                if kind == "pause":
                    paused = True
                elif kind == "resume":
                    paused = False
                    wall_anchor, sim_anchor = time.monotonic(), sim.now / 1e6
                elif kind == "stop":
                    stopped = True
                elif kind == "speed":
                    speed = float(command["payload"]["speed_multiplier"])
                    wall_anchor, sim_anchor = time.monotonic(), sim.now / 1e6
                updates.put(
                    dict(
                        type="command_applied",
                        command_id=command["command_id"],
                        command=kind,
                        status="PAUSED" if paused else "RUNNING",
                    )
                )
            wall = time.monotonic()
            if wall - last_send >= 0.1 or paused or stopped:
                sequence += 1
                value = dict(
                    **sim.snapshot(),
                    run_id=job_id,
                    status="PAUSED" if paused else "RUNNING",
                    sequence=sequence,
                    type="snapshot",
                    speed_multiplier=speed,
                )
                _snapshot_put(snapshots, value)
                last_send = wall
            if stopped:
                break
            if paused:
                time.sleep(0.01)
                continue
            # Pace the next event boundary; wall-clock speed never enters physics.
            next_sim = (
                sim.events[0][0] / 1e6 if sim.current is None and sim.events else sim.now / 1e6
            )
            if speed and wall - wall_anchor < (next_sim - sim_anchor) / speed:
                time.sleep(0.005)
                continue
            d = sim.advance_until_decision_or_end(max_timestamps=1)
            if d:
                apply_controller_action(sim, controller)
        if stopped:
            sim.done, sim.reason = True, "stopped"
        controller.close()
        archive(
            sim,
            Path(root) / "runs",
            run_id=job_id,
            controller_name=cfg.controller.name,
            model_hash=getattr(controller, "model_hash", None),
        )
        status = "STOPPED" if stopped else "COMPLETED"
        final = dict(
            **sim.snapshot(),
            run_id=job_id,
            status=status,
            sequence=sequence + 1,
            type="completed",
            speed_multiplier=speed,
            final_metrics=calculate(sim),
        )
        updates.put(dict(type="completed", status=status, snapshot=final))
    except Exception as error:
        path.mkdir(parents=True, exist_ok=True)
        details = dict(
            code=type(error).__name__,
            message=str(error),
            traceback=traceback.format_exc(),
            recent_events=sim.event_log[-50:] if sim else [],
        )
        atomic_json(path / "failure.json", details)
        if sim is not None:
            try:
                sim.done, sim.reason = True, "failed"
                archive(sim, Path(root) / "runs", run_id=job_id)
            except Exception:
                pass
        manifest = path / "manifest.json"
        value = json.loads(manifest.read_text()) if manifest.exists() else dict(run_id=job_id)
        value.update(status="FAILED")
        atomic_json(manifest, value)
        updates.put(
            dict(
                type="error",
                status="FAILED",
                error=dict(code=details["code"], message=details["message"]),
            )
        )


def experiment_worker(job_id: str, payload: dict, root: str, controls, updates, snapshots):
    try:
        from elevator_control.evaluation.suite import evaluate_suite

        evaluate_suite(
            payload["suite"],
            Path(root) / "experiments" / job_id,
            model_ids=payload.get("model_ids"),
            model_root=Path(root) / "models",
        )
        updates.put(dict(type="completed", status="COMPLETED"))
    except Exception as error:
        path = Path(root) / "experiments" / job_id
        atomic_json(
            path / "failure.json", dict(message=str(error), traceback=traceback.format_exc())
        )
        updates.put(
            dict(
                type="error",
                status="FAILED",
                error=dict(code=type(error).__name__, message=str(error)),
            )
        )
