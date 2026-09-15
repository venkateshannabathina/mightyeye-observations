# MightyEye

**Evidence-backed visual intelligence for the SIH hackathon.**

A working software vertical slice: observations → World State → five deterministic event rules → incidents → playable evidence → persistent storage → FastAPI → an operator dashboard.

The original Stage 4 observation tools remain compatible. The project now includes the subsequent backend stages and explicit integration boundaries for NVIDIA DeepStream, cross-camera appearance matching, ANPR, and optional VLM verification.

> Start here: [16-step build guide](docs/BUILD_GUIDE.md) · [verified status](docs/BUILD_STATUS.md) · [NVIDIA runbook](docs/NVIDIA_SETUP.md)

## Run the full local demo

Use **Python 3.11 or newer**. On Macs where `python3` is the system Python 3.9, select your installed Python 3.12 executable instead.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e '.[dev]'
./scripts/run_demo.sh
```

Open **http://127.0.0.1:8000**. API documentation: **http://127.0.0.1:8000/docs**.

The script generates a controlled synthetic dataset, verifies expected events, saves original synthetic source clips, cuts incident evidence, and starts the dashboard. Re-running it does not duplicate observations or incidents. It writes only under `output/demo/` by default.

**Expected result:** 237 observations, exactly five incidents, five playable evidence clips, zero incidents from the two negative cameras. The plate and cross-camera feature examples are explicitly synthetic; no recognition accuracy is claimed.

### The three screens

1. **Live Operations:** observation sources, current local tracks, status, recent incidents.
2. **Incidents:** chronological feed with type and camera filters.
3. **Incident Detail:** video, supporting observations, trigger rationale, confidence, plate data when supplied, optional verification, operator reviews.

Synthetic mode shows state at the end of replay. Source previews are saved evidence clips, not live CCTV. Without configured video, a clearly labeled track map is displayed.

## Architecture

```text
CCTV / video
  ↓
DeepStream: decode → detection → tracking → analytics
  ↓
Observation Adapter ← synthetic observation creator
  ↓                       ↓
Public 12-field Observation JSON / JSONL
  ↓
World State → temporal event rules
  ↓
Candidate incident → optional VLM result (separate from facts)
  ↓
PostgreSQL metadata + filesystem evidence
  ↓
FastAPI / WebSocket → dashboard
```

**Dependency rule:** no module outside `deepstream/` imports vendor bindings or reads DeepStream metadata. SDK-free replay is tested with NVIDIA imports explicitly blocked.

## Repository layout

```text
src/mightyeye_observations/
  contract.py                 # exact 12-field observation contract
  deepstream/                 # adapter, analytics extraction, live runtime, recording bridge
  engine.py                   # current tracks and five temporal state machines
  domain.py                   # rule, candidate, review and health contracts
  service.py                  # transaction orchestration and provenance checks
  storage.py                  # PostgreSQL / SQLite repository
  evidence.py                 # original-source clip extraction and registration
  api.py                      # REST + WebSocket + dashboard delivery
  dashboard/                  # three screens; no frontend build required
  association.py              # conservative CAM01 → CAM02 matching
  anpr.py                     # vehicle crop → supplied detector/OCR → plate result
  verification.py             # optional provider, separate inference result
  demo_pipeline.py            # repeatable controlled synthetic dataset
config/                       # temporal rules and NVIDIA analytics example
schemas/                      # versioned public observation JSON Schema
scripts/                      # full demo and NVIDIA environment checks
examples/                     # original observation fixtures
tests/                       # unit, integration and PostgreSQL checks
docs/                        # build guide, status, architecture and deployment
```

## Five event rules

| Event | Trigger |
| --- | --- |
| Restricted intrusion | Person observed inside a configured restricted ROI |
| Loitering | Continuous observations in a configured area exceed the threshold |
| Possible abandoned object | Bag was near a person, becomes stationary, and remains alone while that person is observed away |
| Wrong direction | A configured line is crossed with its forbidden direction label |
| Vehicle entry | Vehicle crosses a configured entry line |

Rules are configured in `config/rules.json`. Gaps reset continuity. Old observations do not rewind state. Detector confidence is not a calibrated probability that an incident occurred. Candidates remain candidates until human review; optional VLM inference never rewrites facts.

## PostgreSQL deployment

```sh
cp .env.example .env
# Set POSTGRES_PASSWORD in .env.
docker compose up --build
```

This starts an empty live-mode backend and PostgreSQL. See [deployment](docs/DEPLOYMENT.md) for seeding synthetic mode, backup, migration constraints, and local-access boundaries.

## Original observation commands

```sh
.venv/bin/mightyeye-observations generate --output output/observations.jsonl
.venv/bin/mightyeye-observations validate output/observations.jsonl
.venv/bin/mightyeye-observations replay output/observations.jsonl
.venv/bin/mightyeye-observations schema
# Send saved observations into a running full backend:
.venv/bin/mightyeye-observations ingest output/observations.jsonl
```

The `replay` command retains its small Stage 4 reference-consumer behavior. `demo`, `serve`, and `ingest` exercise the full incident pipeline.

## Tests

```sh
.venv/bin/pytest -q
.venv/bin/mightyeye-observations demo --output output/acceptance
```

CI runs Python 3.11–3.13, a real PostgreSQL 16 service, evidence decoding, fixture replay, and the full generated demo. PostgreSQL tests are skipped locally unless `TEST_DATABASE_URL` is provided. The evidence generator uses the FFmpeg binary supplied by `imageio-ffmpeg`.

## Honest acceptance boundary

Working locally: complete synthetic software chain, persistent incidents/reviews, video extraction, analytics mapping tests, conservative association logic, provider contracts, and monitoring inputs.

Pending on target hardware: DeepStream 9.1 runtime acceptance, stable real-video tracking, calibrated ROI/line directions, native Smart Record pipeline wiring, learned Re-ID embeddings, real plate detector/OCR, selected VLM provider, and staged real CCTV footage. These are tracked step by step rather than reported as complete.
