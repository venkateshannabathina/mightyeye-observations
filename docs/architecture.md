# Architecture and data ownership

The full plan is organized in [BUILD_GUIDE.md](BUILD_GUIDE.md), with acceptance status in [BUILD_STATUS.md](BUILD_STATUS.md).

## Public boundary

`contract.Observation` remains the exact 12-field portable wire model. Only `deepstream/` reads SDK metadata. Both the synthetic producer and NVIDIA adapter emit the same JSON. The original Stage 4 reference replay remains available; `Service` is the full incident pipeline.

## Processing ownership

1. Producers assign stable camera/session identity and event time.
2. Service validates, deduplicates, and persists observations in insertion order.
3. Engine uses event time for track state and deterministic candidates.
4. Service atomically persists incident facts and current entity snapshots.
5. EvidenceRecorder preserves a source clip and records readiness after completion.
6. FastAPI exposes facts, reviews, evidence and fresh World State.
7. The dashboard consumes only API JSON and playable media.

Candidate `start_time`/`end_time` describe the supporting detection window, not a claim that the real-world incident has ended. Operator review is stored separately; candidates are not silently promoted to confirmed events. Confidence is the minimum available supporting detector confidence, explicitly not a calibrated event probability.

## Optional enrichment

Appearance vectors, ANPR outputs and VLM results use separate typed contracts. They do not extend the 12-field observation or overwrite it. Feature endpoints verify their source observation and local entity. Matching stores a proposed global association; local track identities remain intact. VLM text and verdict are recorded separately from deterministic reasons.

## Existing sibling prototype

The older sibling `MightyEye/` directory is untouched. It uses a different frame-based observation contract and a separate dashboard. This repository contains its own compatible full stack; migration into that older prototype is not required for this demo.

## Scale boundaries

This is one backend process with in-memory current state reconstructed from durable observations. It is not a distributed streaming platform. Long-running use needs checkpointing, retention, replay ordering policy, persistent recording jobs, provider timeouts, model evaluation and deployment access control.
