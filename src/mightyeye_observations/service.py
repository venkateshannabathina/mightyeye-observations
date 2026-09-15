"""Single-writer orchestration; transaction commits before publishing state."""

import copy
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

import psutil
from sqlalchemy import insert, select

from . import storage as db
from .contract import Observation
from .domain import Review, RuleConfig
from .engine import Engine


class Service:
    def __init__(
        self,
        repository: db.Repository,
        config: RuleConfig | None = None,
        *,
        mode="live",
    ):
        self.repo = repository
        self.config = config or RuleConfig()
        if mode not in {"live", "synthetic"}:
            raise ValueError("Unknown ingest mode")
        self.mode = mode
        self.engine = Engine(self.config)
        self.lock = threading.RLock()
        self.metrics = {
            "processed": 0,
            "duplicates": 0,
            "last_processing_ms": None,
            "vlm_calls": 0,
            "vlm_latency_ms": None,
            "missed_incidents": None,
        }
        signature = {"rules": self.config.model_dump(mode="json"), "mode": mode}
        with self.repo.engine.begin() as conn:
            saved = conn.execute(
                select(db.settings.c.value).where(db.settings.c.key == "pipeline")
            ).scalar_one_or_none()
            if saved is not None and saved != signature:
                raise ValueError(
                    "Database belongs to a different rule configuration or mode; use a new database"
                )
            if saved is None:
                conn.execute(
                    insert(db.settings).values(key="pipeline", value=signature)
                )
        for payload in self.repo.observation_stream():
            self.engine.process(Observation.model_validate(payload))
            self.metrics["processed"] += 1

    def ingest(self, observation: Observation):
        started = time.perf_counter()
        with self.lock:
            with self.repo.engine.begin() as conn:
                exists = conn.execute(
                    select(db.observations.c.observation_id).where(
                        db.observations.c.observation_id
                        == str(observation.observation_id)
                    )
                ).first()
                if exists:
                    self.metrics["duplicates"] += 1
                    return []
                next_engine = copy.deepcopy(self.engine)
                candidates = next_engine.process(observation)
                conn.execute(
                    insert(db.observations).values(
                        observation_id=str(observation.observation_id),
                        camera_id=observation.camera_id,
                        payload=observation.model_dump(mode="json"),
                    )
                )
                camera = (
                    conn.execute(
                        select(db.cameras.c.payload).where(
                            db.cameras.c.camera_id == observation.camera_id
                        )
                    ).scalar_one_or_none()
                    or {}
                )
                camera.update(
                    {
                        "camera_id": observation.camera_id,
                        "mode": self.mode,
                        "last_observation_time": max(
                            camera.get("last_observation_time", ""),
                            observation.timestamp.isoformat(),
                        ),
                    }
                )
                camera.setdefault(
                    "status", "replay" if self.mode == "synthetic" else "unknown"
                )
                self.repo.put(conn, db.cameras, observation.camera_id, camera)
                for entity in next_engine.world():
                    old = (
                        conn.execute(
                            select(db.entities.c.payload).where(
                                db.entities.c.entity_id == entity["entity_id"]
                            )
                        ).scalar_one_or_none()
                        or {}
                    )
                    self.repo.put(
                        conn, db.entities, entity["entity_id"], {**old, **entity}
                    )
                records = []
                for candidate in candidates:
                    item = candidate.model_dump(mode="json")
                    item.update(
                        {
                            "incident_id": str(candidate.candidate_id),
                            "type": candidate.event_type,
                            "status": "candidate",
                            "severity": "high"
                            if candidate.event_type
                            in ("restricted_intrusion", "abandoned_object")
                            else "medium",
                            "verification_status": "not_requested",
                            "verification": None,
                            "evidence_status": "pending",
                            "rule_version": self.config.rule_version,
                            "model_version": observation.model_version,
                            "synthetic": self.mode == "synthetic",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    self.repo.put(
                        conn,
                        db.incidents,
                        item["incident_id"],
                        item,
                        event_type=item["type"],
                        camera_id=observation.camera_id,
                        start_time=item["start_time"],
                        trigger_time_us=int(
                            (candidate.end_time or candidate.start_time).timestamp()
                            * 1_000_000
                        ),
                    )
                    records.append(item)
            self.engine = next_engine
            self.metrics["processed"] += 1
            self.metrics["last_processing_ms"] = round(
                (time.perf_counter() - started) * 1000, 3
            )
            return records

    def world(self):
        with self.lock:
            return self.engine.world(
                None if self.mode == "synthetic" else datetime.now(timezone.utc)
            )

    def detail(self, incident_id):
        incident = self.repo.get(db.incidents, incident_id)
        if incident is None:
            return None
        return {
            **incident,
            "evidence": [
                x for x in self.repo.all(db.evidence) if x["incident_id"] == incident_id
            ],
            "reviews": [
                x for x in self.repo.all(db.reviews) if x["incident_id"] == incident_id
            ],
        }

    def review(self, incident_id: str, review: Review):
        with self.lock, self.repo.engine.begin() as conn:
            item = conn.execute(
                select(db.incidents.c.payload).where(
                    db.incidents.c.incident_id == incident_id
                )
            ).scalar_one_or_none()
            if item is None:
                raise LookupError("Incident not found")
            record = {
                "review_id": str(uuid4()),
                "incident_id": incident_id,
                **review.model_dump(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.repo.put(
                conn, db.reviews, record["review_id"], record, incident_id=incident_id
            )
            item["review_decision"] = review.decision
            item["status"] = {
                "CONFIRMED": "confirmed",
                "FALSE": "dismissed",
                "UNCERTAIN": "candidate",
            }[review.decision]
            self.repo.put(conn, db.incidents, incident_id, item)
            return record

    def health(self):
        # GPU/FPS must be supplied by the ingest runtime, never inferred from replay speed.
        reviews = self.repo.all(db.reviews)
        return {
            "status": "ok",
            "mode": self.mode,
            "database": self.repo.dialect,
            "incidents": self.repo.incident_count(),
            "metrics": {
                **self.metrics,
                "late_observations": self.engine.late_count,
                "cpu_percent": psutil.cpu_percent(),
                "ram_percent": psutil.virtual_memory().percent,
                "false_reviews": sum(r["decision"] == "FALSE" for r in reviews),
            },
            "streams": self.repo.all(db.cameras),
        }

    def attach_appearance(self, feature):
        from .association import Appearance, associate
        from .engine import entity_key

        with self.lock, self.repo.engine.begin() as conn:
            raw = conn.execute(
                select(db.observations.c.payload).where(
                    db.observations.c.observation_id == feature.source_observation_id
                )
            ).scalar_one_or_none()
            if raw is None:
                raise LookupError("Source observation not found")
            obs = Observation.model_validate(raw)
            if (
                obs.entity_type != "person"
                or entity_key(obs) != feature.entity_id
                or obs.camera_id != feature.camera_id
                or obs.timestamp != feature.timestamp
                or obs.direction != feature.direction
            ):
                raise ValueError(
                    "Appearance provenance does not match source person observation"
                )
            payloads = list(conn.execute(select(db.entities.c.payload)).scalars())
            entity = next(
                (e for e in payloads if e["entity_id"] == feature.entity_id), None
            )
            if entity is None:
                raise LookupError("Entity not found")
            if entity.get("association", {}).get("status") == "ASSOCIATED":
                return entity["association"]
            consumed = {
                e["association"]["source_entity_id"]
                for e in payloads
                if e.get("association", {}).get("status") == "ASSOCIATED"
            }
            exits = [
                Appearance.model_validate(e["appearance"])
                for e in payloads
                if "appearance" in e and e["entity_id"] not in consumed
            ]
            result = associate(feature, exits)
            prior = entity.get("appearance")
            if prior and Appearance.model_validate(prior).timestamp > feature.timestamp:
                raise ValueError("Appearance update is older than saved feature")
            entity["appearance"] = feature.model_dump(mode="json")
            entity["association"] = result
            self.repo.put(conn, db.entities, feature.entity_id, entity)
            return result

    def attach_plate(self, plate):
        from .engine import entity_key

        with self.lock, self.repo.engine.begin() as conn:
            raw = conn.execute(
                select(db.observations.c.payload).where(
                    db.observations.c.observation_id == plate.source_observation_id
                )
            ).scalar_one_or_none()
            if raw is None:
                raise LookupError("Source observation not found")
            obs = Observation.model_validate(raw)
            if obs.entity_type != "vehicle":
                raise ValueError("Plate source must be a vehicle")
            if plate.synthetic and self.mode != "synthetic":
                raise ValueError(
                    "Synthetic plate cannot be attached to live observations"
                )
            key = entity_key(obs)
            entity = conn.execute(
                select(db.entities.c.payload).where(db.entities.c.entity_id == key)
            ).scalar_one_or_none()
            if entity is None:
                raise LookupError("Vehicle entity not found")
            entity["plate"] = plate.model_dump()
            self.repo.put(conn, db.entities, key, entity)
            attached = []
            for incident in conn.execute(
                select(db.incidents.c.payload).where(
                    db.incidents.c.event_type == "vehicle_entry"
                )
            ).scalars():
                if (
                    key in incident["involved_entities"]
                    and obs.camera_id in incident["cameras"]
                ):
                    incident["plate"] = plate.model_dump()
                    self.repo.put(conn, db.incidents, incident["incident_id"], incident)
                    attached.append(incident["incident_id"])
            return {"plate": plate.model_dump(), "incident_ids": attached}
