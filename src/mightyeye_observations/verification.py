"""Optional VLM inference is separate from observations and deterministic facts."""

import time
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from . import storage as db
from .domain import StrictModel


class Verification(StrictModel):
    verdict: Literal["supports", "rejects", "uncertain"]
    summary: str = Field(min_length=1, max_length=4000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_version: str


class Verifier(Protocol):
    def verify(self, *, incident: dict, evidence_files: list[Path]) -> Verification: ...


def verify_incident(service, recorder, incident_id: str, provider: Verifier | None):
    incident = service.detail(incident_id)
    if incident is None:
        raise LookupError("Incident not found")
    if provider is None:
        return {"status": "disabled"}
    if incident.get("verification") is not None:
        return {"status": "already_verified", "result": incident["verification"]}
    if (
        incident["severity"] != "high"
        and incident["confidence"] is not None
        and incident["confidence"] >= 0.8
    ):
        return {"status": "not_eligible"}
    files = [recorder.resolve(e) for e in incident["evidence"] if e["state"] == "ready"]
    if not files:
        return {"status": "awaiting_evidence"}
    started = time.perf_counter()
    service.metrics["vlm_calls"] += 1
    try:
        result = Verification.model_validate(
            provider.verify(incident=incident, evidence_files=files)
        )
    except Exception as exc:
        service.metrics["vlm_latency_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        # Facts and rule status survive provider errors unchanged.
        return {"status": "failed", "error_type": type(exc).__name__}
    service.metrics["vlm_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    with service.lock, service.repo.engine.begin() as conn:
        from sqlalchemy import select

        item = conn.execute(
            select(db.incidents.c.payload).where(
                db.incidents.c.incident_id == incident_id
            )
        ).scalar_one()
        item["verification"] = result.model_dump()
        item["verification_status"] = result.verdict
        service.repo.put(conn, db.incidents, incident_id, item)
    return {"status": "completed", "result": result.model_dump()}
