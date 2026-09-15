import subprocess
from types import SimpleNamespace as NS

import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient

from mightyeye_observations.anpr import PlateResult
from mightyeye_observations.api import create_app
from mightyeye_observations.association import Appearance, associate
from mightyeye_observations.deepstream.adapter import DeepStreamAdapter
from mightyeye_observations.deepstream.smart_record import (
    RecordRequest,
    SmartRecordBridge,
)
from mightyeye_observations.demo_pipeline import observation, render_source
from mightyeye_observations.engine import entity_key
from mightyeye_observations.evidence import EvidenceRecorder
from mightyeye_observations.service import Service
from mightyeye_observations.storage import Repository
from mightyeye_observations.verification import Verification, verify_incident


def appearance(camera, second, track="person-1", vector=None):
    obs = observation(
        camera, second, track=track, direction="OUT" if camera == "CAM01" else "IN"
    )
    return obs, Appearance(
        entity_id=entity_key(obs),
        camera_id=camera,
        timestamp=obs.timestamp,
        direction=obs.direction,
        embedding=vector or [1.0, 0.0],
        model_version="test-v1",
        source_observation_id=str(obs.observation_id),
    )


def test_association_rejects_weak_ambiguous_and_outside_window():
    _, exit = appearance("CAM01", 0)
    _, entry = appearance("CAM02", 10)
    assert associate(entry, [exit])["status"] == "ASSOCIATED"
    assert associate(appearance("CAM02", 100)[1], [exit])["status"] == "UNKNOWN"
    assert (
        associate(appearance("CAM02", 10, vector=[0.0, 1.0])[1], [exit])["status"]
        == "UNKNOWN"
    )
    competitor = appearance("CAM01", 1, track="person-2")[1]
    assert associate(entry, [exit, competitor])["status"] == "UNKNOWN"


def test_association_provenance_and_one_to_one(tmp_path):
    service = Service(Repository(f"sqlite:///{tmp_path}/db"), mode="synthetic")
    for camera, second, track in [
        ("CAM01", 0, "one"),
        ("CAM02", 10, "two"),
        ("CAM02", 11, "three"),
    ]:
        obs, feature = appearance(camera, second, track)
        service.ingest(obs)
        result = service.attach_appearance(feature)
        assert result["status"] == ("ASSOCIATED" if track == "two" else "UNKNOWN")
    obs, feature = appearance("CAM02", 12, "missing")
    with pytest.raises(LookupError):
        service.attach_appearance(feature)


def test_plate_provenance_and_incident_attachment(tmp_path):
    service = Service(Repository(f"sqlite:///{tmp_path}/db"), mode="synthetic")
    obs = observation("car", 0, kind="vehicle", lines=("entry",))
    incident = service.ingest(obs)[0]
    plate = PlateResult(
        text="PB10AB1234",
        confidence=0.91,
        source_observation_id=str(obs.observation_id),
        detector_version="test",
        ocr_version="test",
        synthetic=True,
    )
    result = service.attach_plate(plate)
    assert result["incident_ids"] == [incident["incident_id"]]
    assert service.detail(incident["incident_id"])["plate"]["text"] == "PB10AB1234"


def test_evidence_decode_api_range_and_optional_verification(tmp_path):
    service = Service(Repository(f"sqlite:///{tmp_path}/db"), mode="synthetic")
    items = [
        observation("cam", t, zone="restricted" if t >= 2 else "walkway")
        for t in range(5)
    ]
    for o in items:
        service.ingest(o)
    incident = service.repo.list_incidents()[0]
    source = tmp_path / "source.mp4"
    start, duration = render_source(source, items)
    recorder = EvidenceRecorder(service, tmp_path / "evidence")
    evidence = recorder.record(
        incident["incident_id"],
        source=source,
        source_start=start,
        source_duration=duration,
        synthetic=True,
    )
    path = recorder.resolve(evidence)
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    assert evidence["coverage"] == "partial"
    assert recorder.resolve(evidence, frame=True).stat().st_size > 0
    assert (
        verify_incident(service, recorder, incident["incident_id"], None)["status"]
        == "disabled"
    )

    class Reject:
        def verify(self, **kwargs):
            assert kwargs["evidence_files"]
            return Verification(
                verdict="rejects",
                summary="Controlled provider result",
                model_version="fake-vlm",
            )

    assert (
        verify_incident(service, recorder, incident["incident_id"], Reject())["status"]
        == "completed"
    )
    after = service.detail(incident["incident_id"])
    assert after["verification_status"] == "rejects"
    assert after["reasons"] == incident["reasons"]
    assert after["status"] == "candidate"
    assert (
        verify_incident(service, recorder, incident["incident_id"], Reject())["status"]
        == "already_verified"
    )
    with TestClient(create_app(service, evidence_root=tmp_path / "evidence")) as client:
        response = client.get(
            "/evidence/" + evidence["evidence_id"], headers={"Range": "bytes=0-127"}
        )
        assert response.status_code == 206
        assert len(response.content) == 128
        assert (
            client.get("/evidence/" + evidence["evidence_id"] + "?frame=true").headers[
                "content-type"
            ]
            == "image/jpeg"
        )
    with pytest.raises(ValueError):
        recorder.register(incident["incident_id"], source)
    with pytest.raises(ValueError):
        recorder.resolve({"path": "../source.mp4"})


def test_analytics_extraction_prioritizes_zone_and_preserves_lines():
    info = NS(roiStatus=["waiting", "restricted"], lcStatus=["entry"], dirStatus="OUT")
    user = NS(base_meta=NS(meta_type=7), user_meta_data=info)
    bindings = NS(
        NvDsUserMeta=NS(cast=lambda x: x),
        NvDsAnalyticsObjInfo=NS(cast=lambda x: x),
        nvds_get_user_meta_type=lambda _: 7,
    )
    adapter = DeepStreamAdapter(
        camera_id="cam",
        session_id="s",
        model_version="m",
        class_map={},
        zone_priority=("restricted",),
    )
    assert adapter.analytics(
        NS(obj_user_meta_list=NS(data=user, next=None)), bindings
    ) == {"zone": "restricted", "direction": "OUT", "line_crossing": ("entry",)}
    assert adapter.analytics(NS(), bindings)["line_crossing"] is None


def test_smart_record_registers_only_on_completion():
    calls = []
    bridge = SmartRecordBridge(
        lambda camera, pre, post: calls.append((camera, pre, post)) or 4
    )
    request = RecordRequest("incident", "cam")
    assert bridge.trigger(request) == 4
    assert calls == [("cam", 5, 5)]
    with pytest.raises(ValueError):
        bridge.trigger(request)
    registered = []
    bridge.completed(
        "cam", 4, "clip.mp4", lambda *args, **kwargs: registered.append((args, kwargs))
    )
    assert registered[0][0] == ("incident", "clip.mp4")
    assert not bridge.pending


def test_anpr_crop_threshold_and_ambiguity():
    from PIL import Image

    from mightyeye_observations.anpr import recognize

    class Detector:
        def detect(self, crop):
            assert crop.size == (100, 470)
            return [(0, 0, 80, 30)]

    class OCR:
        def read(self, crop):
            assert crop.size == (80, 30)
            return ("pb 10 ab 1234", 0.93)

    frame = Image.new("RGB", (1000, 1000))
    obs = observation("car", 0, kind="vehicle", x=0.2)
    result = recognize(
        frame,
        obs,
        Detector(),
        OCR(),
        detector_version="test-detector",
        ocr_version="test-ocr",
    )
    assert result.text == "PB10AB1234"
    assert (
        recognize(
            frame,
            obs,
            Detector(),
            OCR(),
            detector_version="d",
            ocr_version="o",
            minimum_confidence=0.99,
        )
        is None
    )

    class Ambiguous(Detector):
        def detect(self, crop):
            return [(0, 0, 80, 30), (0, 40, 80, 70)]

    assert (
        recognize(frame, obs, Ambiguous(), OCR(), detector_version="d", ocr_version="o")
        is None
    )


def test_corrupt_evidence_never_becomes_ready(tmp_path):
    service = Service(Repository(f"sqlite:///{tmp_path}/db"), mode="synthetic")
    incident = service.ingest(observation("cam", 0, zone="restricted"))[0]
    recorder = EvidenceRecorder(service, tmp_path / "evidence")
    corrupt = tmp_path / "evidence" / "bad.mp4"
    corrupt.write_bytes(b"not video")
    with pytest.raises(ValueError, match="decoded"):
        recorder.register(incident["incident_id"], corrupt)
    assert service.detail(incident["incident_id"])["evidence_status"] == "pending"
