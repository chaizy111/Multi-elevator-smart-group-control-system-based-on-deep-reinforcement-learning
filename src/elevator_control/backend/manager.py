"""Single API coordinator: spawn workers, durable job index, queued resource limits."""

import multiprocessing as mp
import queue
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from elevator_control.backend.worker import experiment_worker, simulation_worker
from elevator_control.config.schema import canonical_hash
from elevator_control.storage.repository import Repository

TERMINAL = {"COMPLETED", "STOPPED", "FAILED"}


class ConflictError(ValueError):
    pass


class ResourceError(ValueError):
    pass


class JobManager:
    def __init__(self, root: Path, max_workers=2):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = Repository(root / "index.sqlite3")
        self.repo.repair()
        self.max_workers = max_workers
        self.context = mp.get_context("spawn")
        self.pending = deque()
        self.active = {}
        self.notifications = {}
        self.responses = {}
        self.lock = threading.RLock()
        self.stopping = False
        self.thread = threading.Thread(target=self._loop, daemon=True, name="elevator-coordinator")
        self.thread.start()

    def create(self, kind: str, payload: dict) -> str:
        with self.lock:
            if len(self.pending) + len(self.active) >= 32:
                raise ResourceError("job queue limit 32 exceeded")
            id = ("run-" if kind == "simulation" else "experiment-") + uuid.uuid4().hex[:16]
            self.repo.create(id, kind, payload)
            return id

    def command(self, id: str, command_id: str, kind: str, payload: dict) -> dict:
        signature = canonical_hash(dict(type=kind, payload=payload))
        with self.lock:
            cached = self.repo.command(id, command_id)
            if cached:
                if cached["signature"] != signature:
                    raise ConflictError("command_id reused with different payload")
                return cached["result"]
            job = self.repo.get(id)
            status = job["status"]
            if kind == "start":
                if status != "CREATED":
                    raise ConflictError(f"cannot start {status}")
                self.repo.update(id, status="QUEUED")
                self.pending.append(id)
            elif kind == "reset":
                if status in ("RUNNING", "PAUSED"):
                    self.active[id]["controls"].put(
                        dict(command_id=command_id, type="stop", payload={})
                    )
                elif status == "QUEUED":
                    self.pending.remove(id)
                    self.repo.update(id, status="STOPPED")
                new_id = self.create(job["kind"], job["config"])
                result = dict(
                    schema_version=1, accepted=True, command_id=command_id, new_run_id=new_id
                )
                self.repo.save_command(id, command_id, signature, result)
                return result
            elif kind == "stop" and status == "QUEUED":
                self.pending.remove(id)
                self.repo.update(id, status="STOPPED")
            else:
                allowed = {
                    "pause": {"RUNNING"},
                    "resume": {"PAUSED"},
                    "stop": {"RUNNING", "PAUSED"},
                    "speed": {"RUNNING", "PAUSED"},
                }
                if kind not in allowed or status not in allowed[kind]:
                    raise ConflictError(f"cannot {kind} {status}")
                if kind == "speed" and payload.get("speed_multiplier") not in (0, 1, 5, 20):
                    raise ValueError("speed_multiplier must be 0/1/5/20")
                self.active[id]["controls"].put(
                    dict(command_id=command_id, type=kind, payload=payload)
                )
            result = dict(schema_version=1, accepted=True, command_id=command_id)
            self.repo.save_command(id, command_id, signature, result)
            return result

    def _launch(self, id):
        job = self.repo.get(id)
        controls, updates, snapshots = (
            self.context.Queue(),
            self.context.Queue(),
            self.context.Queue(maxsize=2),
        )
        target = simulation_worker if job["kind"] == "simulation" else experiment_worker
        process = self.context.Process(
            target=target,
            args=(id, job["config"], str(self.root), controls, updates, snapshots),
            daemon=True,
        )
        process.start()
        self.active[id] = dict(
            process=process, controls=controls, updates=updates, snapshots=snapshots
        )
        self.repo.update(id, status="RUNNING")

    def _loop(self):
        while not self.stopping:
            with self.lock:
                while self.pending and len(self.active) < self.max_workers:
                    self._launch(self.pending.popleft())
                for id, state in list(self.active.items()):
                    try:
                        while True:
                            snap = state["snapshots"].get_nowait()
                            self.repo.update(id, snapshot=snap)
                    except queue.Empty:
                        pass
                    try:
                        while True:
                            message = state["updates"].get_nowait()
                            if message["type"] == "passengers_result":
                                response = self.responses.get(message["request_id"])
                                if response:
                                    response["result"] = message["result"]
                                    response["event"].set()
                                continue
                            notes = self.notifications.setdefault(id, deque(maxlen=128))
                            number = notes[-1]["notification_sequence"] + 1 if notes else 1
                            notes.append(
                                {
                                    k: v
                                    for k, v in dict(
                                        **message, notification_sequence=number, run_id=id
                                    ).items()
                                    if k != "snapshot"
                                }
                            )
                            self.repo.update(
                                id,
                                status=message.get("status"),
                                snapshot=message.get("snapshot"),
                                error=message.get("error"),
                            )
                    except queue.Empty:
                        pass
                    if not state["process"].is_alive():
                        state["process"].join(timeout=0)
                        job = self.repo.get(id)
                        if job["status"] not in TERMINAL:
                            self.repo.update(
                                id,
                                status="FAILED",
                                error=dict(
                                    code="worker_exit",
                                    message=f"Worker exited with code {state['process'].exitcode}",
                                ),
                            )
                        for name in ["controls", "updates", "snapshots"]:
                            state[name].close()
                        del self.active[id]
            time.sleep(0.02)

    def query_passengers(self, id: str, filters: dict) -> dict:
        request_id = uuid.uuid4().hex
        response: dict[str, Any] = dict(event=threading.Event(), result=None)
        with self.lock:
            if id not in self.active:
                return dict(items=[], cursor=filters["offset"], available=False)
            self.responses[request_id] = response
            self.active[id]["controls"].put(
                dict(type="passengers_query", command_id=request_id, payload=filters)
            )
        response["event"].wait(timeout=3)
        with self.lock:
            self.responses.pop(request_id, None)
        return response["result"] or dict(items=[], cursor=filters["offset"], available=False)

    def events_since(self, id: str, sequence: int) -> list[dict]:
        with self.lock:
            return [
                dict(n)
                for n in self.notifications.get(id, [])
                if n["notification_sequence"] > sequence
            ]

    def close(self):
        self.stopping = True
        self.thread.join(timeout=2)
        with self.lock:
            for state in self.active.values():
                state["controls"].put(dict(command_id="shutdown", type="stop", payload={}))
            for id, state in self.active.items():
                state["process"].join(timeout=5)
                if state["process"].is_alive():
                    state["process"].terminate()
                    state["process"].join(timeout=2)
                if self.repo.get(id)["status"] not in TERMINAL:
                    self.repo.update(
                        id,
                        status="FAILED",
                        error=dict(
                            code="shutdown",
                            message="Coordinator shut down; inspect preserved artifacts",
                        ),
                    )
            self.active.clear()
