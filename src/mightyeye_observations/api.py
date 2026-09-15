"""Local operations API. Deploy as one process while World State is in memory."""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import storage as db
from .anpr import PlateResult
from .association import Appearance
from .contract import Observation
from .domain import Review, RuleConfig, StreamHealth
from .evidence import EvidenceRecorder
from .service import Service
from .storage import Repository
from .verification import verify_incident


def create_app(service: Service | None = None, *, evidence_root=None, verifier=None):
    if service is None:
        rule_path = Path(os.getenv("MIGHTYEYE_RULES", "config/rules.json"))
        rules = (
            RuleConfig.model_validate_json(rule_path.read_text())
            if rule_path.exists()
            else RuleConfig()
        )
        service = Service(
            Repository(os.getenv("DATABASE_URL", "sqlite:///output/mightyeye.db")),
            rules,
            mode=os.getenv("MIGHTYEYE_MODE", "live"),
        )
    recorder = EvidenceRecorder(
        service, evidence_root or os.getenv("EVIDENCE_ROOT", "output/evidence")
    )
    app = FastAPI(title="MightyEye", version="0.2.0")
    app.state.service = service
    subscribers: set[asyncio.Queue] = set()

    async def publish(kind, data):
        message = {"type": kind, "data": data}
        for queue in tuple(subscribers):
            if queue.full():
                queue.get_nowait()
                # Each world payload is a full snapshot; incidents also persist in REST.
            queue.put_nowait(message)

    @app.get("/health")
    def health():
        return service.health()

    @app.get("/cameras")
    def cameras():
        return service.repo.all(db.cameras)

    @app.get("/world")
    def world():
        return service.world()

    @app.get("/incidents")
    def incidents(
        event_type: str | None = None,
        camera_id: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        return service.repo.list_incidents(
            event_type=event_type, camera_id=camera_id, limit=limit, offset=offset
        )

    @app.get("/incidents/{incident_id}")
    def detail(incident_id: str):
        item = service.detail(incident_id)
        if item is None:
            raise HTTPException(404, "Incident not found")
        return item

    @app.post("/observations")
    async def ingest(observation: Observation):
        records = await asyncio.to_thread(service.ingest, observation)
        await publish("world", service.world())
        for record in records:
            await publish("incident", record)
        return {"incidents": records}

    @app.post("/incidents/{incident_id}/reviews")
    async def review(incident_id: str, item: Review):
        try:
            result = service.review(incident_id, item)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        await publish("incident", service.detail(incident_id))
        return result

    @app.post("/cameras/{camera_id}/health")
    async def stream_health(camera_id: str, item: StreamHealth):
        with service.lock, service.repo.engine.begin() as conn:
            record = service.repo.get(db.cameras, camera_id) or {"camera_id": camera_id}
            record.update(item.model_dump())
            record["health_reported_at"] = datetime.now(timezone.utc).isoformat()
            service.repo.put(conn, db.cameras, camera_id, record)
        await publish("health", record)
        return record

    @app.post("/appearances")
    async def appearance(item: Appearance):
        try:
            result = service.attach_appearance(item)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        await publish("association", result)
        return result

    @app.post("/plates")
    async def plate(item: PlateResult):
        try:
            result = service.attach_plate(item)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        for incident_id in result["incident_ids"]:
            await publish("incident", service.detail(incident_id))
        return result

    @app.post("/incidents/{incident_id}/verify")
    async def verify(incident_id: str):
        try:
            result = await asyncio.to_thread(
                verify_incident, service, recorder, incident_id, verifier
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        await publish("incident", service.detail(incident_id))
        return result

    @app.get("/evidence/{evidence_id}")
    def evidence(evidence_id: str, frame: bool = False):
        item = service.repo.get(db.evidence, evidence_id)
        if item is None:
            raise HTTPException(404, "Evidence not found")
        try:
            path = recorder.resolve(item, frame=frame)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, "Evidence file unavailable") from exc
        return FileResponse(path, media_type="image/jpeg" if frame else "video/mp4")

    @app.websocket("/live")
    async def live(socket: WebSocket):
        await socket.accept()
        queue = asyncio.Queue(maxsize=100)
        subscribers.add(queue)
        try:
            await socket.send_json({"type": "world", "data": service.world()})
            await socket.send_json({"type": "health", "data": service.health()})
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=2)
                except asyncio.TimeoutError:
                    message = {"type": "world", "data": service.world()}
                await socket.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            subscribers.discard(queue)

    dashboard = Path(__file__).parent / "dashboard"
    app.mount("/assets", StaticFiles(directory=dashboard), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(dashboard / "index.html")

    return app
