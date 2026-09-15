# DeepStream integration

Only `mightyeye_observations.deepstream` may access SDK structures or import `pyds`. Ordinary installation deliberately excludes the NVIDIA bindings; install them in your compatible DeepStream runtime.

NVIDIA documents `rect_params`, `object_id`, `class_id`, and the unavailable detector confidence sentinel in [NvDsObjectMeta](https://docs.nvidia.com/metropolis/deepstream/dev-guide/python-api/PYTHON_API/NvDsMeta/NvDsObjectMeta.html). Conversion follows those fields. Tracker confidence is not substituted for detector confidence.

Inside the DeepStream module / pad probe:

```python
from mightyeye_observations.deepstream.adapter import DeepStreamAdapter

adapter = DeepStreamAdapter(
    camera_id="entrance-01",
    session_id="unique-session-created-on-pipeline-start",
    model_version="your-detector-weights-revision",
    class_map={0: "vehicle", 1: "bicycle", 2: "person", 3: "unknown"},
)
# These IDs are an example only. Supply the actual labels of your model.

# While the GstBuffer and its frame metadata are alive:
observations = adapter.convert_frame(
    frame_meta,
    timestamp=resolved_capture_time_utc,
    frame_width=metadata_coordinate_width,
    frame_height=metadata_coordinate_height,
)
for observation in observations:
    downstream_queue.put(observation.model_dump_json())
```

The queue, lifecycle, and capture clock resolver belong to your live pipeline. Resolve `frame_meta.source_id` to a stable camera configuration and adapter instance. Create a fresh session on restart. Never assume `buf_pts` is Unix epoch time; supply a resolved aware UTC datetime. Choose the metadata coordinate dimensions after mux/scaling, rather than blindly using original camera dimensions.

`convert_frame` traverses the SDK linked object list and copies scalar data immediately; SDK objects never escape. It extracts nvdsanalytics user metadata for ROI, direction, and crossing labels when present. Configure `zone_priority` for overlapping zones; otherwise the first sorted zone is selected. Conflicting direction labels become unknown. Evidence remains null until a real media reference is available. You can also call `convert_object` inside the module with explicit translated analytics and evidence values. Unsupported detector classes become `unknown`.

Conversion is fail-fast. Catch validation errors at your pipeline boundary and report/quarantine them; do not silently publish malformed observations. Do not perform blocking disk or network work in a real-time pad probe; use a bounded queue and explicit backpressure policy.

Tests use SDK-shaped objects and a binding double for linked-list traversal. Validate camera mapping, timestamps, scaled coordinates, analytics labels, reconnect sessions, and throughput on the target GPU before calling live integration complete.
