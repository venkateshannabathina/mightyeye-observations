import os

import pytest
from fastapi.testclient import TestClient

from mightyeye_observations.api import create_app
from mightyeye_observations.demo_pipeline import build_demo, observation, scenarios
from mightyeye_observations.domain import RuleConfig
from mightyeye_observations.engine import Engine
from mightyeye_observations.service import Service
from mightyeye_observations.storage import Repository


def test_all_five_rules_and_negative_scenarios():
    engine = Engine()
    events = []
    for item in scenarios():
        events.extend(engine.process(item))
    assert sorted(e.event_type for e in events) == sorted(
        [
            "restricted_intrusion",
            "loitering",
            "abandoned_object",
            "wrong_direction",
            "vehicle_entry",
        ]
    )
    assert not any(
        "CAM-NORMAL" in e.cameras or "CAM-NEGATIVE" in e.cameras for e in events
    )
    assert all(e.reasons and e.source_observation_ids for e in events)
    assert all(e.start_time <= e.end_time for e in events)


def test_tracking_gap_resets_loiter_timer():
    engine = Engine(RuleConfig(loiter_seconds=5))
    emitted = []
    for second in [0, 1, 2, 10, 11, 12, 13, 14]:
        emitted.extend(engine.process(observation("gap", second, zone="waiting")))
    assert not emitted
    assert (
        engine.process(observation("gap", 15, zone="waiting"))[0].event_type
        == "loitering"
    )


def test_missing_owner_is_not_abandonment():
    engine = Engine(RuleConfig(abandoned_seconds=2, stationary_seconds=1))
    engine.process(observation("bag", 0, x=0.3))
    events = []
    for second in range(12):
        events.extend(
            engine.process(observation("bag", second, track="bag", kind="bag", x=0.35))
        )
    assert not events


def test_late_data_and_expiry():
    engine = Engine()
    engine.process(observation("cam", 20))
    assert engine.process(observation("cam", 1, zone="restricted")) == []
    assert engine.late_count == 1
    assert engine.world(observation("cam", 40).timestamp) == []


def test_persistence_duplicate_and_restart(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    service = Service(Repository(url), mode="synthetic")
    obs = observation("cam", 0, zone="restricted")
    assert len(service.ingest(obs)) == 1
    assert service.ingest(obs) == []
    restarted = Service(Repository(url), mode="synthetic")
    assert len(restarted.repo.list_incidents()) == 1
    assert restarted.world() == service.world()
    assert restarted.ingest(obs) == []
    with pytest.raises(ValueError, match="different rule"):
        Service(Repository(url), RuleConfig(loiter_seconds=10), mode="synthetic")


def test_api_websocket_review_and_errors(tmp_path):
    service = Service(Repository(f"sqlite:///{tmp_path}/api.db"), mode="synthetic")
    with TestClient(create_app(service, evidence_root=tmp_path / "evidence")) as client:
        assert client.get("/").status_code == 200
        assert client.get("/world").json() == []
        with client.websocket_connect("/live") as ws:
            assert ws.receive_json()["type"] == "world"
            assert ws.receive_json()["type"] == "health"
            response = client.post(
                "/observations",
                json=observation("cam", 0, zone="restricted").model_dump(mode="json"),
            )
            assert response.status_code == 200
            incident = response.json()["incidents"][0]
            assert ws.receive_json()["type"] == "world"
            assert ws.receive_json()["type"] == "incident"
        assert client.get("/incidents?camera_id=other").json() == []
        assert client.get("/incidents/missing").status_code == 404
        assert client.get("/evidence/missing").status_code == 404
        assert client.post("/observations", json={}).status_code == 422
        response = client.post(
            f"/incidents/{incident['incident_id']}/reviews",
            json={
                "decision": "FALSE",
                "failure_reason": "rule",
                "note": "Controlled test",
            },
        )
        assert response.status_code == 200
        assert (
            client.get(f"/incidents/{incident['incident_id']}").json()["reviews"][0][
                "decision"
            ]
            == "FALSE"
        )
        assert client.get("/health").json()["metrics"]["false_reviews"] == 1
        assert (
            client.post(
                "/cameras/cam/health", json={"status": "disconnected", "disconnects": 1}
            ).status_code
            == 200
        )
        assert client.get("/cameras").json()[0]["status"] == "disconnected"


def test_demo_repeatable(tmp_path):
    first = build_demo(tmp_path, videos=False)
    second = build_demo(tmp_path, videos=False)
    assert first == second
    assert sum(first["incidents"].values()) == 5


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="PostgreSQL integration runs in CI service",
)
def test_postgresql_roundtrip():
    from uuid import uuid4

    service = Service(Repository(os.environ["TEST_DATABASE_URL"]), mode="synthetic")
    camera = "postgres-" + str(uuid4())
    obs = observation(camera, 0, zone="restricted")
    record = service.ingest(obs)[0]
    assert service.ingest(obs) == []
    restarted = Service(Repository(os.environ["TEST_DATABASE_URL"]), mode="synthetic")
    assert restarted.detail(record["incident_id"])["type"] == "restricted_intrusion"


def test_incidents_sorted_by_trigger_not_window_start(tmp_path):
    service = Service(Repository(f"sqlite:///{tmp_path}/db"), mode="synthetic")
    for item in scenarios():
        service.ingest(item)
    records = service.repo.list_incidents()
    assert records[0]["type"] == "abandoned_object"
    assert records[1]["type"] == "loitering"
    assert records[-1]["type"] == "restricted_intrusion"


def test_v1_migration_backfills_trigger_order(tmp_path):
    import json
    import sqlite3

    path = tmp_path / "v1.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_settings (key VARCHAR PRIMARY KEY, value JSON NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_settings VALUES (?,?)", ("schema_version", "1")
        )
        connection.execute(
            "CREATE TABLE incidents (incident_id VARCHAR PRIMARY KEY, event_type VARCHAR, camera_id VARCHAR, start_time VARCHAR, payload JSON)"
        )
        payload = {
            "incident_id": "old",
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-01T00:01:00Z",
        }
        connection.execute(
            "INSERT INTO incidents VALUES (?,?,?,?,?)",
            ("old", "loitering", "cam", payload["start_time"], json.dumps(payload)),
        )
    repository = Repository(f"sqlite:///{path}")
    assert repository.list_incidents()[0]["incident_id"] == "old"
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT trigger_time_us FROM incidents").fetchone()[0]
            > 0
        )
        assert (
            int(
                connection.execute(
                    "SELECT value FROM schema_settings WHERE key=?", ("schema_version",)
                ).fetchone()[0]
            )
            == 2
        )
