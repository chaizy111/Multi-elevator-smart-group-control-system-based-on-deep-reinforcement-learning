"""Immutable, content-addressed traffic records, independent of policy execution."""

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from elevator_control.config.schema import SimulationConfig, canonical_hash
from elevator_control.domain.models import Passenger, us

GENERATOR_VERSION = "poisson-od-v2-quantized-window"
COLUMNS = ["passenger_id", "arrival_time", "origin_floor", "destination_floor"]


@dataclass(frozen=True)
class Record:
    passenger_id: str
    arrival_us: int
    origin: int
    destination: int


@dataclass(frozen=True)
class TrafficTrace:
    records: tuple[Record, ...]
    seed: int = 0
    config_hash: str = "manual"
    generator_version: str = "manual-v1"

    def bytes(self) -> bytes:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(COLUMNS)
        for r in self.records:
            writer.writerow([r.passenger_id, f"{r.arrival_us / 1e6:.6f}", r.origin, r.destination])
        return stream.getvalue().encode()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.bytes()).hexdigest()

    def validate(self, config: SimulationConfig) -> None:
        ids = set()
        last = -1
        for r in self.records:
            if r.passenger_id in ids or not r.passenger_id:
                raise ValueError("duplicate or empty passenger ID")
            if r.arrival_us < last or not 0 <= r.arrival_us < us(
                config.simulation.arrival_horizon_s
            ):
                raise ValueError("trace must be sorted within [0,H)")
            if (
                not (
                    1 <= r.origin <= config.building.floor_count
                    and 1 <= r.destination <= config.building.floor_count
                )
                or r.origin == r.destination
            ):
                raise ValueError("invalid trace origin/destination")
            ids.add(r.passenger_id)
            last = r.arrival_us
        if len(ids) > config.simulation.max_passengers:
            raise ValueError("trace exceeds max_passengers")

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.bytes())
        path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generator_version": self.generator_version,
                    "seed": self.seed,
                    "config_hash": self.config_hash,
                    "sha256": self.sha256,
                    "count": len(self.records),
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, path: str | Path, config: SimulationConfig):
        path = Path(path)
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != COLUMNS:
                raise ValueError("trace schema must be " + ",".join(COLUMNS))
            records = tuple(
                Record(
                    r["passenger_id"],
                    us(float(r["arrival_time"])),
                    int(r["origin_floor"]),
                    int(r["destination_floor"]),
                )
                for r in reader
            )
        metadata = (
            json.loads(path.with_suffix(".json").read_text())
            if path.with_suffix(".json").exists()
            else {}
        )
        if metadata.get("schema_version", 1) != 1:
            raise ValueError("unsupported trace schema")
        result = cls(
            records,
            metadata.get("seed", 0),
            metadata.get("config_hash", "imported"),
            metadata.get("generator_version", "imported-v1"),
        )
        result.validate(config)
        if metadata.get("sha256", result.sha256) != result.sha256:
            raise ValueError("trace checksum mismatch")
        return result

    def passengers(self) -> dict[str, Passenger]:
        return {
            r.passenger_id: Passenger(r.passenger_id, r.arrival_us, r.origin, r.destination)
            for r in self.records
        }


def derived_seeds(seed: int) -> dict[str, int]:
    names = ["traffic", "environment", "policy", "training", "bootstrap"]
    return {
        n: int(s.generate_state(1)[0])
        for n, s in zip(names, np.random.SeedSequence(seed).spawn(5), strict=True)
    }


def generate(config: SimulationConfig) -> TrafficTrace:
    rng = np.random.default_rng(derived_seeds(config.seed)["traffic"])
    floors = config.building.floor_count
    raw: list[tuple[int, int, int, int, int]] = []

    def od(pattern):
        if pattern == "morning" and rng.random() < 0.8:
            return 1, int(rng.integers(2, floors + 1))
        if pattern == "evening" and rng.random() < 0.8:
            return int(rng.integers(2, floors + 1)), 1
        choices = np.arange(
            2 if pattern in ("morning", "evening", "interfloor") and floors > 2 else 1, floors + 1
        )
        o, d = rng.choice(choices, size=2, replace=False)
        return int(o), int(d)

    segments = [
        (s.start_s, s.end_s, s.pattern, s.arrival_rate_per_min) for s in config.traffic.segments
    ] or [
        (
            0,
            config.simulation.arrival_horizon_s,
            config.traffic.pattern,
            config.traffic.arrival_rate_per_min,
        )
    ]
    for source, (start, end, pattern, rate) in enumerate(segments):
        t = start
        ordinal = 0
        while rate:
            t += float(rng.exponential(60 / rate))
            if t >= end:
                break
            if us(t) >= us(end):
                continue
            o, d = od("normal" if pattern == "burst" else pattern)
            raw.append((us(t), source, ordinal, o, d))
            ordinal += 1
            if len(raw) > config.simulation.max_passengers:
                raise ValueError("generated trace exceeds max_passengers")
    bursts = list(config.traffic.bursts)
    if config.traffic.pattern == "burst" and not bursts:
        from elevator_control.config.schema import Burst

        bursts = [
            Burst(
                time_s=config.simulation.arrival_horizon_s * 0.5,
                window_s=min(60, config.simulation.arrival_horizon_s * 0.25),
                origin=floors,
            )
        ]
    for index, b in enumerate(bursts):
        for ordinal in range(b.count):
            t = min(
                us(b.time_s + float(rng.uniform(0, b.window_s))),
                us(config.simulation.arrival_horizon_s) - 1,
            )
            options = [f for f in range(1, floors + 1) if f != b.origin]
            d = (
                1
                if b.origin != 1 and rng.random() < b.lobby_probability
                else int(rng.choice(options))
            )
            raw.append((t, len(segments) + index, ordinal, b.origin, d))
    raw.sort()
    trace = TrafficTrace(
        tuple(Record(f"P{i + 1:07d}", t, o, d) for i, (t, _, __, o, d) in enumerate(raw)),
        config.seed,
        canonical_hash(config),
        GENERATOR_VERSION,
    )
    trace.validate(config)
    return trace
