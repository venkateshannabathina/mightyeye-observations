"""Copy metadata while its buffer is alive; never retain SDK objects."""
import json
import math
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5
from mightyeye_observations.contract import Observation

UNTRACKED_OBJECT_ID = (1 << 64) - 1

class DeepStreamAdapter:
    def __init__(self, *, camera_id: str, session_id: str, model_version: str,
                 class_map: dict[int, str]):
        if not camera_id or not session_id or not model_version:
            raise ValueError("camera, session and model version are required")
        self.camera_id = camera_id
        self.session_id = session_id
        self.model_version = model_version
        self.class_map = dict(class_map)

    def convert_object(self, obj_meta, *, frame_number: int, object_index: int,
                       timestamp: datetime, frame_width: int, frame_height: int,
                       zone: str | None = None, direction: str | None = None,
                       line_crossing: tuple[str, ...] | None = None,
                       evidence_pointer: str | None = None) -> Observation:
        # Dimensions must match the coordinate space of rect_params (post mux/scale).
        if frame_width <= 0 or frame_height <= 0 or frame_number < 0 or object_index < 0:
            raise ValueError("invalid frame dimensions or object/frame index")
        r = obj_meta.rect_params
        left, top, width, height = map(float, (r.left, r.top, r.width, r.height))
        if not all(math.isfinite(v) for v in (left, top, width, height)) or width <= 0 or height <= 0:
            raise ValueError("invalid source rectangle")
        clip = lambda v: max(0.0, min(1.0, v))
        box = (clip(left / frame_width), clip(top / frame_height),
               clip((left + width) / frame_width), clip((top + height) / frame_height))
        score = float(obj_meta.confidence)
        # NVIDIA uses -0.1 for unavailable detector confidence.
        confidence = None if score == -0.1 or math.isclose(score, -0.1, abs_tol=1e-7) else score
        raw_track = int(obj_meta.object_id)
        if raw_track < 0 or raw_track > UNTRACKED_OBJECT_ID:
            raise ValueError("invalid tracker ID")
        track = None if raw_track == UNTRACKED_OBJECT_ID else f"{self.session_id}:{raw_track}"
        identity = json.dumps([self.camera_id, self.session_id, frame_number, object_index,
                               self.model_version], separators=(",", ":"))
        return Observation(observation_id=uuid5(NAMESPACE_URL, identity), camera_id=self.camera_id,
            timestamp=timestamp, local_track_id=track,
            entity_type=self.class_map.get(int(obj_meta.class_id), "unknown"), bbox=box,
            confidence=confidence, zone=zone, direction=direction, line_crossing=line_crossing,
            model_version=self.model_version, evidence_pointer=evidence_pointer)

    def convert_frame(self, frame_meta, *, timestamp: datetime, frame_width: int,
                      frame_height: int) -> list[Observation]:
        """Live entry point. Caller maps source_id to adapter and resolves UTC time.

        timestamp is explicitly supplied: stream PTS is not Unix epoch time.
        Missing analytics/evidence remain null; enrich via convert_object when available.
        """
        import pyds
        result = []
        node = frame_meta.obj_meta_list
        index = 0
        while node is not None:
            obj = pyds.NvDsObjectMeta.cast(node.data)
            result.append(self.convert_object(obj, frame_number=int(frame_meta.frame_num),
                object_index=index, timestamp=timestamp,
                frame_width=frame_width, frame_height=frame_height))
            index += 1
            try:
                node = node.next
            except StopIteration:
                break
        return result
