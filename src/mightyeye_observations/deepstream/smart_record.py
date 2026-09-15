"""Smart Record command boundary, driven by a configured DeepStream runtime."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RecordRequest:
    incident_id: str
    camera_id: str
    pre_seconds: int = 5
    post_seconds: int = 5


class SmartRecordBridge:
    def __init__(
        self, start: Callable[[str, int, int], int], *, cache_seconds: int = 15
    ):
        # start wraps NvDsSRStart using a per-camera NvDsSRContext configured by the pipeline.
        self.start = start
        self.cache_seconds = cache_seconds
        self.pending: dict[tuple[str, int], RecordRequest] = {}

    def trigger(self, request: RecordRequest):
        if (
            request.pre_seconds < 0
            or request.post_seconds <= 0
            or request.pre_seconds >= self.cache_seconds
        ):
            raise ValueError(
                "Smart Record cache must exceed pre-roll, with positive post-roll"
            )
        if any(r.incident_id == request.incident_id for r in self.pending.values()):
            raise ValueError("Recording already pending for this incident")
        if any(camera == request.camera_id for camera, _ in self.pending):
            raise ValueError("Recording already active for camera; queue this incident")
        session = self.start(
            request.camera_id, request.pre_seconds, request.post_seconds
        )
        self.pending[(request.camera_id, session)] = request
        return session

    def completed(self, camera_id, session_id, clip_path, register):
        key = (camera_id, session_id)
        request = self.pending[key]
        # Only a finished clip can become ready evidence. register is EvidenceRecorder.register.
        result = register(
            request.incident_id,
            clip_path,
            synthetic=False,
            extra={
                "capture_method": "deepstream-smart-record",
                "coverage": "unverified",
                "requested_pre_seconds": request.pre_seconds,
                "requested_post_seconds": request.post_seconds,
            },
        )
        del self.pending[key]
        return result
