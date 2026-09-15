"""Vendor-neutral application contracts, separate from the 12-field wire format."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RuleConfig(StrictModel):
    restricted_zones: list[str] = ["restricted"]
    loiter_zones: list[str] = ["waiting"]
    loiter_seconds: float = Field(default=30, gt=0)
    abandoned_seconds: float = Field(default=45, gt=0)
    stationary_seconds: float = Field(default=3, gt=0)
    max_gap_seconds: float = Field(default=2, gt=0)
    track_ttl_seconds: float = Field(default=10, gt=0)
    stationary_distance: float = Field(default=0.015, gt=0)
    owner_distance: float = Field(default=0.2, gt=0)
    owner_away_distance: float = Field(default=0.35, gt=0)
    forbidden_directions: dict[str, str] = {"exit": "IN"}
    vehicle_lines: list[str] = ["entry"]
    rule_version: str = "rules-v1"


class Candidate(StrictModel):
    candidate_id: UUID
    event_type: Literal[
        "restricted_intrusion",
        "loitering",
        "abandoned_object",
        "wrong_direction",
        "vehicle_entry",
    ]
    involved_entities: list[str]
    cameras: list[str]
    start_time: datetime
    end_time: datetime | None
    confidence: float | None = Field(ge=0, le=1)
    reasons: list[str]
    source_observation_ids: list[UUID]


class Review(StrictModel):
    decision: Literal["CONFIRMED", "FALSE", "UNCERTAIN"]
    failure_reason: (
        Literal[
            "detector",
            "tracker",
            "cross-camera",
            "rule",
            "occlusion",
            "low light",
            "bad camera/input",
            "overload",
        ]
        | None
    ) = None
    note: str = Field(default="", max_length=2000)


class StreamHealth(StrictModel):
    status: Literal["online", "disconnected", "reconnecting", "offline"]
    fps: float | None = Field(default=None, ge=0)
    dropped_frames: int = Field(default=0, ge=0)
    disconnects: int = Field(default=0, ge=0)
    reconnects: int = Field(default=0, ge=0)
    tracker_resets: int = Field(default=0, ge=0)
    gpu_percent: float | None = Field(default=None, ge=0, le=100)
