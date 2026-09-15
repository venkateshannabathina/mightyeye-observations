"""Deterministic event-time state machines. No GPU, wall-clock, or network dependency."""

from dataclasses import dataclass, field
from datetime import datetime
from math import hypot
from uuid import NAMESPACE_URL, uuid5

from .contract import Observation
from .domain import Candidate, RuleConfig


def entity_key(o: Observation) -> str:
    # JSON encoding prevents collisions when camera/session names contain punctuation.
    import json

    return json.dumps([o.camera_id, o.local_track_id], separators=(",", ":"))


def center(o):
    a, b, c, d = o.bbox
    return ((a + c) / 2, (b + d) / 2)


def distance(a, b):
    return hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class Track:
    first: Observation
    last: Observation
    zone_start: Observation
    stationary_start: Observation
    movement_state: str = "unknown"
    fired: set = field(default_factory=set)
    owner: str | None = None
    owner_observation: Observation | None = None
    alone_start: Observation | None = None


class Engine:
    def __init__(self, config: RuleConfig | None = None):
        self.config = config or RuleConfig()
        self.tracks: dict[str, Track] = {}
        self.watermarks: dict[str, datetime] = {}
        self.late_count = 0

    def process(self, o: Observation) -> list[Candidate]:
        cfg = self.config
        watermark = self.watermarks.get(o.camera_id)
        if watermark and o.timestamp < watermark:
            self.late_count += 1
            return []
        self.watermarks[o.camera_id] = o.timestamp
        for key, track in list(self.tracks.items()):
            if (
                track.last.camera_id == o.camera_id
                and (o.timestamp - track.last.timestamp).total_seconds()
                > cfg.track_ttl_seconds
            ):
                del self.tracks[key]
        if o.local_track_id is None:
            return []
        key = entity_key(o)
        track = self.tracks.get(key)
        continuous = (
            track is not None
            and (o.timestamp - track.last.timestamp).total_seconds()
            <= cfg.max_gap_seconds
        )
        prior = track.last if track else None
        if not continuous:
            track = Track(o, o, o, o)
            self.tracks[key] = track
        elif track.last.zone != o.zone:
            track.zone_start = o
            track.fired.clear()
        if prior and continuous:
            track.movement_state = (
                "stationary"
                if distance(center(prior), center(o)) <= cfg.stationary_distance
                else "moving"
            )
            if (
                distance(center(track.stationary_start), center(o))
                > cfg.stationary_distance
            ):
                track.stationary_start = o
                track.alone_start = None
                track.fired.discard("abandoned_object")
        track.last = o
        candidates = []

        def emit(kind, reason, start, supporting, entities=None, once=True):
            if once and kind in track.fired:
                return
            track.fired.add(kind)
            sources = list(dict.fromkeys(x.observation_id for x in supporting + [o]))
            scores = [
                x.confidence for x in supporting + [o] if x.confidence is not None
            ]
            identity = f"{cfg.rule_version}:{kind}:{key}:{start.observation_id}:{o.observation_id}"
            candidates.append(
                Candidate(
                    candidate_id=uuid5(NAMESPACE_URL, identity),
                    event_type=kind,
                    involved_entities=entities or [key],
                    cameras=[o.camera_id],
                    start_time=start.timestamp,
                    end_time=o.timestamp,
                    confidence=min(scores) if scores else None,
                    reasons=[
                        reason,
                        "Confidence is supporting detector confidence, not a calibrated incident probability.",
                    ],
                    source_observation_ids=sources,
                )
            )

        if o.entity_type == "person":
            if o.zone in cfg.restricted_zones:
                emit(
                    "restricted_intrusion",
                    f"Person observed inside restricted zone {o.zone}.",
                    track.zone_start,
                    [track.zone_start],
                )
            dwell = (o.timestamp - track.zone_start.timestamp).total_seconds()
            if o.zone in cfg.loiter_zones and dwell >= cfg.loiter_seconds:
                emit(
                    "loitering",
                    f"Continuous presence in {o.zone} for {dwell:.1f}s (threshold {cfg.loiter_seconds:g}s).",
                    track.zone_start,
                    [track.zone_start],
                )
        for line in o.line_crossing or ():
            if (
                cfg.forbidden_directions.get(line) == o.direction
                and o.direction is not None
            ):
                emit(
                    "wrong_direction",
                    f"Crossed {line} in forbidden direction {o.direction}.",
                    o,
                    [],
                    once=False,
                )
            if o.entity_type == "vehicle" and line in cfg.vehicle_lines:
                emit(
                    "vehicle_entry",
                    f"Vehicle crossed configured entry line {line}.",
                    o,
                    [],
                    once=False,
                )
        if o.entity_type == "bag":
            people = {
                k: t
                for k, t in self.tracks.items()
                if t.last.entity_type == "person"
                and t.last.camera_id == o.camera_id
                and 0
                <= (o.timestamp - t.last.timestamp).total_seconds()
                <= cfg.max_gap_seconds
            }
            nearby = [
                (distance(center(o), center(t.last)), k, t) for k, t in people.items()
            ]
            nearby.sort(key=lambda x: x[0])
            if track.owner is None and nearby and nearby[0][0] <= cfg.owner_distance:
                track.owner, track.owner_observation = nearby[0][1], nearby[0][2].last
            owner = people.get(track.owner)
            owner_away = (
                owner is not None
                and distance(center(o), center(owner.last)) >= cfg.owner_away_distance
            )
            alone = all(d > cfg.owner_distance for d, _, _ in nearby)
            stationary = (
                o.timestamp - track.stationary_start.timestamp
            ).total_seconds() >= cfg.stationary_seconds
            # Absence/occlusion is not proof that an owner moved away.
            if owner_away and alone and stationary:
                if track.alone_start is None:
                    track.alone_start = o
                elapsed = (o.timestamp - track.alone_start.timestamp).total_seconds()
                if elapsed >= cfg.abandoned_seconds:
                    emit(
                        "abandoned_object",
                        f"Possible owner was nearby, moved away, and bag remained stationary and alone for {elapsed:.1f}s. Spatial association is heuristic.",
                        track.alone_start,
                        [
                            track.owner_observation,
                            track.stationary_start,
                            track.alone_start,
                            owner.last,
                        ],
                        [key, track.owner],
                    )
            else:
                track.alone_start = None
        return candidates

    def world(self, now: datetime | None = None):
        result = []
        for key, t in self.tracks.items():
            watermark = now or self.watermarks[t.last.camera_id]
            if (
                watermark - t.last.timestamp
            ).total_seconds() > self.config.track_ttl_seconds:
                continue
            result.append(
                {
                    "entity_id": key,
                    "camera_id": t.last.camera_id,
                    "local_track_id": t.last.local_track_id,
                    "entity_type": t.last.entity_type,
                    "zone": t.last.zone,
                    "first_seen": t.first.timestamp.isoformat(),
                    "last_seen": t.last.timestamp.isoformat(),
                    "dwell_time": (
                        t.last.timestamp - t.zone_start.timestamp
                    ).total_seconds(),
                    "direction": t.last.direction,
                    "movement_state": t.movement_state,
                    "confidence": t.last.confidence,
                    "bbox": list(t.last.bbox),
                }
            )
        return sorted(result, key=lambda x: x["entity_id"])
