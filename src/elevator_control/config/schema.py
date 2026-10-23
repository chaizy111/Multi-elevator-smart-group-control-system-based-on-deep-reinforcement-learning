"""Versioned, strict configuration in seconds and public one-based floors."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Pattern = Literal["normal", "morning", "evening", "interfloor", "burst"]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, validate_default=True)


class Building(Schema):
    floor_count: Annotated[StrictInt, Field(ge=2, le=30)] = 12
    elevator_count: Annotated[StrictInt, Field(ge=1, le=8)] = 4
    capacity: Annotated[StrictInt, Field(ge=1, le=20)] = 12
    lobby_floor: Literal[1] = 1
    floor_height_m: Positive = 3.0
    initial_floors: list[StrictInt] | None = None

    @model_validator(mode="after")
    def validate_initial(self):
        if self.initial_floors is not None:
            if len(self.initial_floors) != self.elevator_count:
                raise ValueError("initial_floors length must equal elevator_count")
            if any(not 1 <= f <= self.floor_count for f in self.initial_floors):
                raise ValueError("initial_floors outside building")
        return self


class Physics(Schema):
    seconds_per_floor: Positive = 2.0
    door_open_s: Positive = 2.0
    door_close_s: Positive = 2.0
    board_s_per_person: Positive = 0.8
    alight_s_per_person: Positive = 0.8
    empty_distance_weight: Nonnegative = 1.0
    loaded_distance_weight: Nonnegative = 1.3
    door_cycle_weight: Nonnegative = 0.2
    start_weight: Nonnegative = 0.1


class Simulation(Schema):
    arrival_horizon_s: Positive = 1800
    max_drain_s: Nonnegative = 1800
    snapshot_interval_s: Positive = 1
    max_passengers: Annotated[StrictInt, Field(ge=0, le=100000)] = 100000
    start_time_of_day_s: Annotated[float, Field(ge=0, lt=86400)] = 28800
    max_events: Annotated[StrictInt, Field(gt=0)] = 10000000


class Segment(Schema):
    start_s: Nonnegative
    end_s: Positive
    pattern: Pattern = "normal"
    arrival_rate_per_min: Nonnegative = 12


class Burst(Schema):
    time_s: Nonnegative
    window_s: Nonnegative = 0
    count: Annotated[StrictInt, Field(ge=1, le=100000)] = 30
    origin: StrictInt
    lobby_probability: Annotated[float, Field(ge=0, le=1)] = 0.8


class Traffic(Schema):
    pattern: Pattern = "normal"
    arrival_rate_per_min: Nonnegative = 12
    segments: list[Segment] = Field(default_factory=list)
    bursts: list[Burst] = Field(default_factory=list)


class ControllerConfig(Schema):
    name: Literal["round_robin", "eta", "eta_zone", "ppo"] = "eta"
    model_id: str | None = None

    @model_validator(mode="after")
    def validate_model(self):
        if self.name == "ppo" and not self.model_id:
            raise ValueError("controller.model_id required for PPO")
        return self


class Reposition(Schema):
    idle_review_s: Positive = 30
    cooldown_s: Positive = 30
    enabled: bool = True


class MetricsConfig(Schema):
    long_wait_threshold_s: Positive = 60


class Reward(Schema):
    wait_weight: Nonnegative = 1
    ride_weight: Nonnegative = 0.2
    energy_weight: Nonnegative = 0.05
    fairness_weight: Nonnegative = 0.5
    passenger_scale: Positive = 10
    time_scale_s: Positive = 60
    distance_scale_floors: Positive = 10
    long_wait_threshold_s: Positive = 60


class SimulationConfig(Schema):
    schema_version: Literal[1] = 1
    seed: Annotated[StrictInt, Field(ge=0, le=4294967295)] = 42
    building: Building = Field(default_factory=Building)
    physics: Physics = Field(default_factory=Physics)
    simulation: Simulation = Field(default_factory=Simulation)
    traffic: Traffic = Field(default_factory=Traffic)
    controller: ControllerConfig = Field(default_factory=ControllerConfig)
    reposition: Reposition = Field(default_factory=Reposition)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    reward: Reward = Field(default_factory=Reward)

    @model_validator(mode="after")
    def validate_traffic(self):
        h = self.simulation.arrival_horizon_s
        if self.traffic.segments:
            cursor = 0.0
            for s in self.traffic.segments:
                if s.start_s != cursor or s.end_s <= s.start_s:
                    raise ValueError("traffic.segments must cover horizon without gaps/overlaps")
                cursor = s.end_s
            if cursor != h:
                raise ValueError("traffic.segments must end at arrival_horizon_s")
        for b in self.traffic.bursts:
            if not 0 <= b.time_s < h or b.time_s + b.window_s > h:
                raise ValueError("burst outside arrival window")
            if not 1 <= b.origin <= self.building.floor_count:
                raise ValueError("burst origin outside building")
        return self


def canonical_hash(value: BaseModel | dict | list) -> str:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_config(path: str | Path) -> SimulationConfig:
    return SimulationConfig.model_validate(yaml.safe_load(Path(path).read_text()))
