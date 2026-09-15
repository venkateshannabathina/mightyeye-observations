# Build status

Status labels refer to actual acceptance, not just the presence of code.

| Step | Deliverable | Current status | Remaining acceptance |
| --- | --- | --- | --- |
| 1 | DeepStream 9.1 runtime | Runbook + environment check supplied | Execute on supported NVIDIA Linux/Jetson hardware |
| 2 | Decode, detect, track | Headless pipeline implementation supplied | Official sample, local video, RTSP, identity stability and reconnect tests |
| 3 | Zones, lines, direction | Analytics config + metadata extraction implemented | Calibrate geometry/class IDs and validate against real clips |
| 4 | Observation Adapter | Implemented and tested | Live SDK conversion verification on target runtime |
| 5 | World State | Implemented and tested | Field freshness and long-running load acceptance |
| 6 | Intrusion, loitering, abandoned object | Deterministic rules tested on controlled observations | Repeated annotated real-footage tests |
| 7 | Wrong direction, vehicle entry | Implemented and tested | Real detector/analytics output acceptance |
| 8 | Evidence | Source-video extraction, playback and registration tested; Smart Record bridge supplied | Attach bridge to native per-camera recording context and completion callback |
| 9 | PostgreSQL | Repository + Compose + real PostgreSQL CI test configured | Verify CI result and deployment backups before use |
| 10 | FastAPI | REST, ingest, review, features and WebSocket implemented | Deployment-specific access controls if exposed beyond local host |
| 11 | Dashboard | Three working screens | Judge/operator review using staged original video |
| 12 | CAM01 → CAM02 | Topology/time/direction/cosine logic, ambiguity rejection, provenance and one-to-one matching tested | Supply learned Re-ID embeddings and test staged handover |
| 13 | ANPR | Vehicle crop/provider pipeline, plate contract, provenance and incident attachment | Load actual plate detector/OCR and validate readable staged plate |
| 14 | Optional VLM | Disabled default, eligible incident selection and separate results tested | Select provider, enforce its timeout, measure evidence-grounded output |
| 15 | Monitoring/reviews | Processing latency, CPU/RAM, stream health inputs and review reasons implemented | GPU/stream counters from runtime; annotated missed-event ground truth |
| 16 | Repeatable dataset | Synthetic source clips, negative cases, five events and demo script implemented | Capture and label the real staged dataset |

## Demonstrated software acceptance

- 237 canonical observations generate exactly one of each requested event.
- Normal walking and short dwell negative scenarios produce no incidents.
- Incidents retain reasons, source observation IDs, versions and confidence semantics.
- Each synthetic incident receives a playable MP4 and trigger frame derived from its original synthetic source clip.
- Duplicate ingestion and backend restart preserve incident counts and operator reviews.
- VLM provider output can support/reject a candidate without changing the original facts.
- Cross-camera ambiguity returns UNKNOWN rather than forcing a match.

## Not measured here

Person/vehicle precision or recall; true tracking ID stability; real abandoned-object accuracy; genuine plate OCR accuracy; real Re-ID quality; GPU FPS; thermal behavior; RTSP reconnect reliability; Smart Record pre/post coverage; VLM latency on a real provider.

Keep the synthetic and real datasets in separate databases. Database configuration is bound to one rule configuration and ingest mode; a mismatch fails startup rather than silently rewriting historic events.
