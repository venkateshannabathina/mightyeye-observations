# MightyEye Observations

Stage 4 of the MightyEye SIH build: a stable observation contract, NVIDIA DeepStream adapter, fake observation creator, and offline JSON replay. Python 3.11+. Offline usage needs no NVIDIA hardware, camera, DeepStream, or `pyds`.

## Run in five minutes

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
mightyeye-observations generate --scenario line-crossing --frames 30 --output output/demo.jsonl
mightyeye-observations validate output/demo.jsonl
mightyeye-observations replay output/demo.jsonl
pytest -q
```

Replay prints **30 observations, 1 track, 1 line-crossing candidate**. Try `zone-entry` for a zone-enter candidate, or `multi-camera` for two independent camera tracks. `--seed` selects a deterministic synthetic session identity; trajectories are deliberately scripted. Use a new output filename for each run; the generator refuses overwrites.

Saved fixtures work immediately:

```sh
mightyeye-observations replay examples/observations.jsonl
mightyeye-observations validate examples/observations.json
mightyeye-observations schema
```

## Architecture

```text
CCTV → DeepStream [Detection / Tracking / ANPR]
                  ↓
           Observation Adapter
                  ↓  public Observation JSON (boundary)
              World State
                  ↓
       Cross-Camera + Event Engine
                  ↓
          Candidate Incident
                  ↓
       Optional VLM Verification
                  ↓
                Incident
                  ↓
         Database + Evidence → Dashboard
```

| Directory | Responsibility |
| --- | --- |
| `src/mightyeye_observations/contract.py` | Strict, immutable public 12-field model |
| `src/mightyeye_observations/deepstream/` | Vendor metadata conversion and optional SDK import |
| `src/mightyeye_observations/synthetic.py` | Reproducible fake observations |
| `src/mightyeye_observations/io.py` | Validated JSON array and JSONL reading/writing |
| `src/mightyeye_observations/world_state.py` | Minimal reference consumer and candidate generation |
| `schemas/` | Versioned JSON Schema for other services/languages |
| `examples/` | Saved synthetic observations |
| `tests/` | Contract, conversion, replay, and dependency-boundary checks |
| `.github/workflows/` | Automated tests on Python 3.11–3.13 |

**Rule: nothing outside the DeepStream module depends on DeepStream metadata.** Every downstream component accepts `Observation` or its JSON representation. The World State reference consumer demonstrates this boundary with no SDK imports.

## Public format

```json
{
  "observation_id": "0b7e85bf-bbdd-5100-bbc8-8a62ffae78dd",
  "camera_id": "cam-01",
  "timestamp": "2026-01-01T00:00:00Z",
  "local_track_id": "session-01:7",
  "entity_type": "person",
  "bbox": [0.1, 0.2, 0.2, 0.7],
  "confidence": 0.95,
  "zone": "walkway",
  "direction": "right",
  "line_crossing": [],
  "model_version": "detector-v1",
  "evidence_pointer": null
}
```

See [contract semantics](docs/observation-contract.md), [DeepStream integration](docs/deepstream-integration.md), and [handoff / remaining stages](docs/architecture.md).

## Scope and acceptance

Implemented: requested contract, conversion of object/frame metadata, synthetic generator, file validation, replay, minimal World State and candidate consumer, schema, tests, CI.

The acceptance check is saved JSON → World State → candidate output without DeepStream. The existing sibling MightyEye dashboard prototype uses a different older contract; this repository is the standalone Stage 4 implementation and is not yet wired into that dashboard.

Live GPU integration has not been tested here. Full cross-camera identity association, ANPR text extraction, incident lifecycle, VLM verification, database/evidence storage and dashboard integration remain later stages. Synthetic evidence pointers are null; generated observations do not claim that a camera or media file exists.
