# Observation contract v1

All 12 keys are required. Unknown keys are rejected. Unavailable information is explicit `null`; no vendor metadata is carried through. JSON Schema is checked into `schemas/observation-v1.schema.json`; versioning lives in the schema filename to preserve the exact requested fields.

| Field | Meaning |
| --- | --- |
| observation_id | UUID, deterministic for a camera/session/frame/object index/model version |
| camera_id | Stable configured camera name, never an SDK batch index |
| timestamp | Timezone-aware ISO 8601 capture/event time, normalized to UTC |
| local_track_id | Session-qualified local tracker ID; null for untracked objects |
| entity_type | person, vehicle, bicycle, bag, plate, or unknown; configured class mapping |
| bbox | Normalized `[left, top, right, bottom]`, 0–1, positive area |
| confidence | Detector confidence 0–1; null when unavailable |
| zone | Configured primary zone identifier; null when unavailable |
| direction | Producer-defined direction label; null when unavailable |
| line_crossing | Array of crossed line IDs for this observation; empty means none, null means unavailable |
| model_version | Explicit detector/model revision; fake data uses synthetic-v1 |
| evidence_pointer | Opaque media reference or null; consumers must resolve it separately |

Frame dimensions must describe the coordinate space containing the detector/tracker rectangle. Adapter clips boxes to the frame, rejects nonfinite values and boxes with no visible area, maps the untracked sentinel to null, and preserves unavailable confidence as null.

A tracker ID is local to `(camera_id, local_track_id)`. Start a new session ID on tracker restart or camera reconnect; session prefixes prevent old track IDs from colliding. Adapter IDs support retries of the same ordered metadata frame; preserve object order on retries, particularly for untracked objects. They are not a global person identity. Cross-camera association is a later stage.

Readers accept a JSON array (`.json`) or stream one object per line (all other extensions, conventionally `.jsonl`). Errors include file and record/line position. Files are strict: a malformed record stops processing. JSONL readers stream; the fixture writer buffers data and is intended for bounded recordings. For continuous recording, write each returned observation's `model_dump_json()` plus a newline to your managed sink.

World State ignores duplicate observation IDs and does not rewind a track for older timestamps. It counts but does not merge untracked objects. Input should be ordered by event time per camera; late observations are retained in the seen count but do not produce events. A production service needs track expiry, bounded deduplication, watermark policy, and durable storage; this reference keeps state in memory for one replay.
