"""Deterministic fake observations. No camera, media, or SDK required."""
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from .contract import Observation


def generate(*, frames: int = 30, seed: int = 42, scenario: str = "line-crossing"):
    if frames < 1:
        raise ValueError("frames must be positive")
    if scenario not in {"line-crossing", "zone-entry", "multi-camera"}:
        raise ValueError("unknown scenario")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cameras = ["cam-01", "cam-02"] if scenario == "multi-camera" else ["cam-01"]
    for frame in range(frames):
        x = 0.1 + 0.7 * frame / max(1, frames - 1)
        prior_x = 0.1 + 0.7 * (frame - 1) / max(1, frames - 1)
        for camera in cameras:
            identity = f"synthetic:{seed}:{scenario}:{frames}:{camera}:{frame}"
            yield Observation(observation_id=uuid5(NAMESPACE_URL, identity), camera_id=camera,
                timestamp=start + timedelta(milliseconds=frame * 100),
                local_track_id=f"synthetic-{seed}:1", entity_type="person",
                bbox=(x, 0.2, x + 0.1, 0.7), confidence=0.95,
                zone="restricted" if scenario == "zone-entry" and x >= 0.5 else "walkway",
                direction="right", line_crossing=("gate",) if scenario == "line-crossing"
                    and frame > 0 and prior_x + 0.05 < 0.5 <= x + 0.05 else (),
                model_version="synthetic-v1", evidence_pointer=None)
