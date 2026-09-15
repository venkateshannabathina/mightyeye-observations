"""Version 1 public wire contract; contains no vendor types."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

Text = Annotated[str, Field(min_length=1, max_length=512)]

class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    observation_id: UUID
    camera_id: Text
    timestamp: datetime
    local_track_id: Text | None
    entity_type: Literal["person", "vehicle", "bicycle", "bag", "plate", "unknown"]
    bbox: tuple[float, float, float, float]
    confidence: Annotated[float, Field(ge=0, le=1)] | None
    zone: Text | None
    direction: Text | None
    line_crossing: tuple[Text, ...] | None
    model_version: Text
    evidence_pointer: Text | None

    @field_validator("timestamp")
    @classmethod
    def utc_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("bbox")
    @classmethod
    def valid_box(cls, box):
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("bbox must be normalized xyxy with positive area")
        return box
