# NVIDIA DeepStream 9.1 setup and acceptance

This is the hardware handoff. The runtime implementation in this repository is not hardware-qualified on the development Mac.

## 1. Select the supported platform

Use the platform-specific OS, driver, CUDA/TensorRT and Jetson requirements in NVIDIA's [9.1 release notes](https://docs.nvidia.com/metropolis/deepstream/9.1/text/DS_Release_notes.html). Do not mix a Jetson stack with an x86 dGPU installation. NVIDIA distributes 9.1 packages through its official release assets. Follow the [installation guide](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Installation.html), including matching Python bindings and sample validation.

Record the actual installed versions in `output/hardware-acceptance.md`. Do not copy expected versions into a report as if they were measured.

## 2. Run environment and official sample checks

```sh
./scripts/check_gpu.sh
# Run the official deepstream-app sample configuration for your installed platform.
# Sample locations and model files are provided by your NVIDIA SDK installation.
```

The script checks available plugins/bindings; it does not certify detection, accuracy or uptime. Save a short official-sample video and observed GPU utilization before continuing.

## 3. Configure a single camera

Copy `config/analytics.example.ini` and calibrate geometry to the post-mux coordinate space. Its example assumes 1920×1080 and a four-class detector whose class 2 is person and class 0 is vehicle. Replace these IDs to match your actual detector labels.

Choose a detector inference config and tracker config from your installed SDK. Use licensed weights and record their hash in the model version or a deployment manifest.

```sh
python -m mightyeye_observations.deepstream.runtime \
  --uri file:///absolute/path/staged-walking.mp4 \
  --camera-id CAM01 \
  --infer-config /absolute/path/config_infer_primary.txt \
  --tracker-config /absolute/path/config_tracker_NvDCF_perf.yml \
  --analytics-config config/analytics.example.ini \
  --model-version detector-revision-and-weights-hash \
  --api-url http://127.0.0.1:8000
```

Start a live-mode backend first. Repeat with your RTSP URL on the GPU host; avoid placing camera credentials in tracked files. One runtime handles one source; use a separate process/camera ID for CAM02.

### Runtime behavior and limits

- The pipeline is headless: decode → mux → detector → tracker → analytics → copied observation JSON.
- A bounded queue moves HTTP work outside the pad probe. Queue overflow drops the frame's observations and increments a counter; HTTP failures are logged. It does not provide durable offline spooling yet.
- Timestamps are mapped from PTS to first-frame arrival UTC. This is an approximate clock, not synchronized camera capture time. Replace this resolver with a validated source-clock mapping before calibrating cross-camera travel times.
- PTS/frame resets create a new tracker session. Validate your camera's exact reconnect behavior; no real RTSP recovery claim is made here.
- FPS is measured in the runtime; backend replay speed is not called GPU FPS. Integrate your GPU telemetry into `/cameras/{id}/health`.
- Real bag detection needs a detector that outputs bags. A standard person/vehicle model cannot support the abandoned-object acceptance gate by itself.

## 4. Wire native Smart Record

NVIDIA's [Smart Video Record documentation](https://docs.nvidia.com/metropolis/deepstream/9.1/text/DS_Smart_video.html) describes the per-source encoded-frame recording cache and `NvDsSRStart`. Pre-roll depends on cached keyframes and may be shorter than requested. Configure enough cache, connect the record bin to the encoded stream, and register the completion callback in the GPU pipeline.

`deepstream.smart_record.SmartRecordBridge` accepts a `start(camera_id, pre_seconds, post_seconds)` callable wrapping your initialized native recording context. Feed candidate recording requests to that bridge in the GPU process. On native completion, call `bridge.completed(..., recorder.register)`. The bridge prevents overlapping starts for a camera and marks a file ready only after completion.

**Still required on hardware:** native context creation, encoded-pad connection, candidate-message transport back to the GPU process, the `NvDsSRStart` wrapper, and completion callback wiring. The headless runtime does not silently pretend those pieces are active. If using recorded video, `EvidenceRecorder.record` already provides the tested offline evidence path.

## 5. Acceptance record

For each scenario save:

- Original source clip and its hash; source camera and capture-clock method.
- Model/config versions; post-mux dimensions; session ID.
- Saved canonical JSONL observations and expected event annotations.
- Incident/evidence output, measured pre/post coverage and playback result.
- FPS, dropped frames, ID switches, disconnect/reconnect behavior and processing latency.

Required scenarios: normal walk, intrusion, long/short dwell, bag placement and departure, bag occlusion without departure, forbidden/allowed direction, vehicle entry with legible plate, CAM01→CAM02 with a distractor.

Only sign off the real-camera milestone when the entire original-video-to-dashboard chain has been reviewed on this target system.
