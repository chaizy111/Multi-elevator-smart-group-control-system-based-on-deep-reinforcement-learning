"""Coordinator-owned SQLite WAL index. Workers only write isolated artifact files."""

import json
import os
import sqlite3
import time
from pathlib import Path


class Repository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                config TEXT NOT NULL, snapshot TEXT, error TEXT,
                created REAL NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS commands (
                job_id TEXT NOT NULL, command_id TEXT NOT NULL,
                signature TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(job_id,command_id)
            );
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def repair(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, config FROM jobs WHERE status IN ('QUEUED','RUNNING','PAUSED')"
            ).fetchall()
            for id, raw in rows:
                owner = json.loads(raw).get("owner_pid")
                if isinstance(owner, int) and owner > 0:
                    try:
                        os.kill(owner, 0)
                        continue
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        continue
                db.execute(
                    "UPDATE jobs SET status='FAILED',error=?,updated=? WHERE id=?",
                    (
                        json.dumps(
                            dict(
                                code="interrupted",
                                message="Coordinator restarted; original artifacts preserved",
                            )
                        ),
                        time.time(),
                        id,
                    ),
                )

    def create(self, id: str, kind: str, config: dict):
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,kind,status,config,created,updated) VALUES (?,?,?,?,?,?)",
                (id, kind, "CREATED", json.dumps(config), now, now),
            )

    def get(self, id: str) -> dict:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM jobs WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        value = dict(row)
        for key in ["config", "snapshot", "error"]:
            value[key] = json.loads(value[key]) if value[key] else None
        return value

    def list(self, kind: str, *, offset=0, limit=50):
        with self.connect() as db:
            ids = db.execute(
                "SELECT id FROM jobs WHERE kind=? ORDER BY created DESC LIMIT ? OFFSET ?",
                (kind, min(limit, 100), offset),
            ).fetchall()
        return [self.get(id) for (id,) in ids]

    def update(self, id: str, *, status=None, snapshot=None, error=None, config=None):
        fields: dict[str, object] = {"updated": time.time()}
        if config is not None:
            fields["config"] = json.dumps(config)
        if status is not None:
            fields["status"] = status
        if snapshot is not None:
            fields["snapshot"] = json.dumps(snapshot)
        if error is not None:
            fields["error"] = json.dumps(error)
        assignments = ",".join(f"{k}=?" for k in fields)
        with self.connect() as db:
            db.execute(f"UPDATE jobs SET {assignments} WHERE id=?", (*fields.values(), id))

    def command(self, id: str, command_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT signature,result FROM commands WHERE job_id=? AND command_id=?",
                (id, command_id),
            ).fetchone()
        return dict(signature=row[0], result=json.loads(row[1])) if row else None

    def save_command(self, id: str, command_id: str, signature: str, result: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO commands VALUES (?,?,?,?)",
                (id, command_id, signature, json.dumps(result)),
            )
