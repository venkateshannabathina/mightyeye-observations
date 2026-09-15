# MightyEye — professional step-by-step build guide

## Working rules

- Preserve the exact observation boundary. Downstream code must not read SDK metadata.
- Complete and demonstrate one vertical slice before adding live advanced models.
- Keep rules deterministic. Keep observations, heuristic interpretation, optional model inference, and human review separate.
- Use original evidence and identify synthetic demonstrations explicitly.
- Mark acceptance only with a command result, saved report, or staged-video review.

The supplied plan is preserved in [original-build-plan.txt](original-build-plan.txt). Current acceptance is in [BUILD_STATUS.md](BUILD_STATUS.md).

## M1 — NVIDIA ingest and observation boundary

### 1. Install and verify DeepStream 9.1

On the GPU machine, follow [NVIDIA_SETUP.md](NVIDIA_SETUP.md), select the supported platform-specific stack, run `scripts/check_gpu.sh`, and run the official NVIDIA sample. Record GPU, driver, OS, SDK, bindings, model/config revisions and sample output.

**Gate:** local video and RTSP process reliably with GPU inference. This cannot be signed off from a Mac software demo.

### 2. Run decode → detector → tracker

Use `deepstream/runtime.py` with a licensed configured detector, NVIDIA tracker config, a stable camera ID, and an explicit model version. Start with one video. Then switch to one RTSP source. Retain the tracker session ID boundary across observations and generate a new session on restart.

**Gate:** a staged person and vehicle receive sensible boxes/classes and maintain stable local IDs. Record dropped frames, ID switches and reconnect resets.

### 3. Configure ROI / lines / direction

Copy and edit `config/analytics.example.ini` for the actual image dimensions. Select the detector's correct class IDs. Stage entrance/exit and wrong-direction movement. The adapter reads `roiStatus`, `lcStatus`, and `dirStatus`; configured primary-zone priority resolves overlapping ROIs. Conflicting direction labels become unknown.

**Gate:** manually reviewed geometry and direction labels agree with the saved metadata.

### 4. Save canonical observations

Use the adapter's copied scalar outputs. Capture a JSONL recording, validate it, and replay it with no SDK available. Unknown metadata remains null. Normalize bbox coordinates using the actual metadata coordinate space; do not assume original camera dimensions after scaling.

**Gate:** downstream processing runs entirely from the saved file. Automated checks cover this.

## M2 — live state and temporal events

### 5. World State

`engine.py` maintains camera-local, session-qualified entities, first/last seen, zone dwell, direction, movement and confidence. Live API state expires against current UTC; synthetic state is shown at the replay endpoint's event time. Persistence keeps historical entities while `/world` exposes the active state.

**Gate:** `/world` answers who/what is where, without merging local IDs from different cameras. Tests cover late data, gap reset and expiry.

### 6. First three events

1. **Intrusion:** observe a person inside a configured restricted zone. First sight inside the zone also triggers, so reasons say “observed inside” rather than inventing an unseen crossing.
2. **Loitering:** accumulate continuous presence in a configured waiting zone. A tracking gap resets the timer.
3. **Possible abandoned object:** associate a nearby person to a bag, check stationary position, then require that person to be observed away and no nearby person to remain. Missing/occluded ownership is not proof of abandonment.

Tune `config/rules.json` on annotated footage. Candidate IDs are deterministic for the rule version and triggering observations. Every candidate includes the requested fields: ID, type, entities, cameras, start/end, confidence, reasons and supporting observation IDs.

**Gate:** repeated saved input yields the same candidates. Synthetic coverage passes; real-footage accuracy remains a separate acceptance gate.

### 7. Wrong direction and vehicle entry

Require a current line-crossing label. Wrong direction also requires the configured forbidden direction label; vehicle entry requires a vehicle crossing an entry line. Nothing triggers from direction alone.

**Gate:** positive crossings fire; no crossing or allowed direction stays negative.

## M3 — incident, evidence and operator workflow

### 8. Preserve evidence

For recorded input, `EvidenceRecorder.record` cuts configurable pre/post video and a trigger frame from the original source. It records SHA-256 hashes, actual offsets, duration and partial coverage. For live RTSP, wire `SmartRecordBridge` to the NVIDIA context and its completion callback; only a completed file becomes ready evidence.

**Gate:** play each clip, verify the trigger occurs inside it, check pre/post coverage and source provenance. Synthetic clip decoding and HTTP Range playback are tested.

### 9. Persist PostgreSQL metadata

Use Compose or an existing PostgreSQL service. Tables include cameras, observations, entities, incidents, evidence and reviews. Store media on disk/object storage, never as database blobs. The schema is versioned, with an explicit v1→v2 alert-ordering migration; future structural changes require further reviewed migrations.

**Gate:** restart the application; incidents, evidence references and reviews remain searchable. CI exercises a real PostgreSQL service; local demo uses SQLite through the same repository.

### 10. Serve the backend

Required GET routes: `/cameras`, `/world`, `/incidents`, `/incidents/{id}`, `/evidence/{id}`, `/health`. `/live` provides initial state and world/incident/health updates. `POST /observations` is the producer boundary. `mightyeye-observations ingest file.jsonl` sends a saved recording into the full backend.

**Gate:** the frontend obtains all information from the API, without SDK imports. Test not-found responses, invalid observations, duplicate sends and restart replay.

### 11. Review in the three-screen dashboard

Open Live Operations, select Incidents, and open an incident. Verify WHAT, WHERE, WHEN, involved local entities, WHY, confidence semantics and EVIDENCE. Submit Confirmed / False / Uncertain with a failure reason where appropriate. Reload to verify persistence.

**Gate:** someone who did not build the system can explain an alert using that screen alone. The demo labels synthetic video and saved replay clearly.

## M4 — one camera pair and ANPR

### 12. Add CAM01 → CAM02 association

Provide person appearance embeddings through `/appearances` with the exact source observation reference and model version. The matcher requires topology, travel time, consistent directions, a strong cosine score and separation from competing matches. It prevents one source track from being consumed by multiple destination identities.

**Gate:** staged same-person handover succeeds, distractors/weak/ambiguous matches remain UNKNOWN. Supplied synthetic vectors demonstrate only the matching logic; deployment must supply real Re-ID output.

### 13. Add vehicle plates

`anpr.recognize` crops a detected vehicle, calls a supplied plate detector and OCR provider, normalizes valid text, applies a confidence threshold, and returns unknown for ambiguous readings. Submit the result through `/plates`; the backend verifies the source vehicle observation and attaches metadata to matching entry incidents.

**Gate:** an actual staged vehicle entry has readable crop evidence and correct plate metadata. Synthetic `PB10AB1234` in the demo is explicitly marked synthetic.

## M5 — optional intelligence and hackathon readiness

### 14. Optional VLM

Inject a provider implementing `Verifier.verify` into the API factory. `/incidents/{id}/verify` does nothing if disabled, skips ineligible low-priority confident candidates, and requires ready evidence. It stores supports/rejects/uncertain separately. Configure a strict timeout in the provider; the core never requires a network model call.

**Gate:** timeout/error leaves the original incident intact; supported/rejected output is visible without modifying observations or deterministic reasons. Controlled-provider tests pass; a real provider is not configured.

### 15. Monitoring and failure review

Monitor processing latency, CPU/RAM, ingest counts, duplicate/late observations, camera FPS/drop/reconnect/reset counters and VLM calls/latency. Camera/GPU metrics must come from the actual runtime. Missed incidents need labeled ground truth, so the metric remains unknown until evaluated. Operator failures use the plan's eight categories.

**Gate:** intentionally disconnect a stream, restart its tracker and mislabel a test event; verify health/review reporting. Synthetic observations per second are not reported as GPU FPS.

### 16. Build and rehearse the dataset

Run `scripts/run_demo.sh`. It creates controlled positives, negative clips, a handover scenario, a synthetic vehicle/plate record, evidence and `acceptance.json`. For real acceptance, film the same scenarios and create reviewed labels in a manifest. Repeat the demo from a clean database, rehearse restart recovery, and inspect every incident clip before judging.

**Final gate:** real camera → person track → event → incident → playable original video evidence → dashboard. The synthetic software chain is verified here; sign the real-camera gate only on the target system.
