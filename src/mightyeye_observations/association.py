"""Conservative CAM01 -> CAM02 association from supplied Re-ID features."""

from datetime import datetime
from math import sqrt
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, field_validator

from .domain import StrictModel


class Appearance(StrictModel):
    entity_id: str
    camera_id: str
    timestamp: datetime
    direction: str
    embedding: list[float] = Field(min_length=2, max_length=8192)
    model_version: str
    source_observation_id: str

    @field_validator("timestamp")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("Timezone required")
        return v


class PairConfig(StrictModel):
    source: str = "CAM01"
    destination: str = "CAM02"
    exit_direction: str = "OUT"
    entry_direction: str = "IN"
    min_seconds: float = Field(default=2, ge=0)
    max_seconds: float = Field(default=30, gt=0)
    minimum_similarity: float = Field(default=0.85, ge=0, le=1)
    ambiguity_margin: float = Field(default=0.05, ge=0, le=1)


def cosine(a, b):
    if len(a) != len(b):
        return None
    norm = sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else None


def associate(
    entry: Appearance, exits: list[Appearance], config: PairConfig | None = None
):
    cfg = config or PairConfig()
    unknown = {
        "global_entity_id": None,
        "association_confidence": None,
        "status": "UNKNOWN",
    }
    if entry.camera_id != cfg.destination or entry.direction != cfg.entry_direction:
        return {**unknown, "reason": "Destination or direction does not match topology"}
    matches = []
    for exit in exits:
        elapsed = (entry.timestamp - exit.timestamp).total_seconds()
        if (
            exit.camera_id != cfg.source
            or exit.direction != cfg.exit_direction
            or exit.model_version != entry.model_version
        ):
            continue
        if not cfg.min_seconds <= elapsed <= cfg.max_seconds:
            continue
        similarity = cosine(entry.embedding, exit.embedding)
        if similarity is not None and similarity >= cfg.minimum_similarity:
            matches.append((similarity, exit))
    matches.sort(key=lambda x: x[0], reverse=True)
    if not matches:
        return {**unknown, "reason": "No appearance match within travel window"}
    if len(matches) > 1 and matches[0][0] - matches[1][0] < cfg.ambiguity_margin:
        return {**unknown, "reason": "Multiple plausible source tracks"}
    similarity, exit = matches[0]
    return {
        "global_entity_id": str(uuid5(NAMESPACE_URL, "global:" + exit.entity_id)),
        "association_confidence": round(similarity, 6),
        "status": "ASSOCIATED",
        "source_entity_id": exit.entity_id,
        "destination_entity_id": entry.entity_id,
        "source_observation_ids": [
            exit.source_observation_id,
            entry.source_observation_id,
        ],
        "reason": "Topology, travel time, directions and appearance agree",
        "score_kind": "cosine_similarity_not_calibrated_probability",
        "model_version": entry.model_version,
    }
