"""Controlled synthetic dataset. This validates plumbing, never camera accuracy."""

import json
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import imageio_ffmpeg
from PIL import Image, ImageDraw

from . import storage as db
from .contract import Observation
from .engine import entity_key
from .evidence import EvidenceRecorder
from .service import Service
from .storage import Repository

START = datetime(2026, 9, 15, 9, tzinfo=timezone.utc)


def observation(
    camera,
    second,
    *,
    track="person-1",
    kind="person",
    x=0.2,
    zone="walkway",
    direction="OUT",
    lines=(),
):
    return Observation(
        observation_id=uuid5(NAMESPACE_URL, f"demo-v2:{camera}:{second}:{track}"),
        camera_id=camera,
        timestamp=START + timedelta(seconds=second),
        local_track_id=f"demo-v2:{track}",
        entity_type=kind,
        bbox=(
            x,
            0.35,
            x + (0.07 if kind == "bag" else 0.1),
            0.65 if kind == "bag" else 0.82,
        ),
        confidence=0.94,
        zone=zone,
        direction=direction,
        line_crossing=lines,
        model_version="synthetic-v2",
        evidence_pointer=None,
    )


def scenarios():
    for t in range(13):
        yield observation(
            "CAM-INTRUSION",
            t,
            x=0.1 + t * 0.035,
            zone="restricted" if t >= 4 else "walkway",
        )
    for t in range(41):
        yield observation("CAM-LOITER", t, zone="waiting")
    for t in range(61):
        yield observation("CAM-BAG", t, x=0.27 if t < 5 else 0.82)
        yield observation("CAM-BAG", t, track="bag-1", kind="bag", x=0.36)
    for t in range(13):
        yield observation(
            "CAM-DIRECTION",
            t,
            x=0.1 + t * 0.04,
            direction="IN",
            lines=("exit",) if t == 6 else (),
        )
        yield observation(
            "CAM-VEHICLE",
            t,
            track="vehicle-1",
            kind="vehicle",
            x=0.1 + t * 0.04,
            lines=("entry",) if t == 6 else (),
        )
        yield observation("CAM-NORMAL", t, x=0.1 + t * 0.04)
    for t in range(16):
        yield observation("CAM-NEGATIVE", t, zone="waiting")
    for t in range(3):
        yield observation("CAM01", 80 + t, x=0.6 + t * 0.04)
        yield observation(
            "CAM02", 90 + t, track="person-8", x=0.1 + t * 0.04, direction="IN"
        )


def render_source(path: Path, items: list[Observation], fps=5):
    start = min(o.timestamp for o in items)
    duration = (max(o.timestamp for o in items) - start).total_seconds() + 1
    by_time = defaultdict(list)
    for o in items:
        by_time[int((o.timestamp - start).total_seconds())].append(o)
    width, height = 640, 360
    process = subprocess.Popen(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    last = []
    try:
        for frame in range(int(duration * fps)):
            second = frame // fps
            last = by_time.get(second, last)
            image = Image.new("RGB", (width, height), "#1c2927")
            d = ImageDraw.Draw(image)
            for x in range(0, width, 40):
                d.line((x, 50, x, height), fill="#2a3933")
            for y in range(60, height, 40):
                d.line((0, y, width, y), fill="#2a3933")
            d.rectangle((350, 70, 620, 330), outline="#836548", width=2)
            d.text((365, 78), "MONITORED AREA", fill="#c59c77")
            d.line((320, 100, 320, 350), fill="#a5b581", width=2)
            d.text((18, 16), "MIGHTYEYE / SYNTHETIC DEMONSTRATION", fill="#ead5a6")
            d.text(
                (18, 35),
                f"{items[0].camera_id}    T+{second:03}s    NOT REAL CAMERA FOOTAGE",
                fill="#a6b7ac",
            )
            for o in last:
                a, b, c, e = o.bbox
                rect = (
                    int(a * width),
                    int(b * height),
                    int(c * width),
                    int(e * height),
                )
                color = "#dac095" if o.entity_type == "bag" else "#b2c99b"
                d.rectangle(rect, outline=color, width=2)
                if o.entity_type == "person":
                    cx = (rect[0] + rect[2]) // 2
                    d.ellipse((cx - 9, rect[1] + 15, cx + 9, rect[1] + 33), fill=color)
                    d.line((cx, rect[1] + 35, cx, rect[3] - 30), fill=color, width=5)
                    d.line(
                        (cx, rect[3] - 30, cx - 12, rect[3] - 4), fill=color, width=4
                    )
                    d.line(
                        (cx, rect[3] - 30, cx + 12, rect[3] - 4), fill=color, width=4
                    )
                elif o.entity_type == "vehicle":
                    d.rectangle(
                        (rect[0] + 3, rect[1] + 45, rect[2] - 3, rect[3] - 20),
                        fill="#657b70",
                    )
                d.text(
                    (rect[0], max(55, rect[1] - 16)),
                    f"{o.local_track_id.split(':')[-1]} / {o.zone}",
                    fill=color,
                )
            process.stdin.write(image.tobytes())
        process.stdin.close()
        error = process.stderr.read().decode()
        if process.wait(timeout=120):
            raise RuntimeError(error)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return start, duration


def build_demo(output: str | Path, *, database_url=None, videos=True):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    service = Service(
        Repository(database_url or f"sqlite:///{root / 'mightyeye.db'}"),
        mode="synthetic",
    )
    items = list(scenarios())
    fixture = root / "observations.jsonl"
    fixture.write_text("".join(o.model_dump_json() + "\n" for o in items))
    grouped = defaultdict(list)
    for o in items:
        service.ingest(o)
        grouped[o.camera_id].append(o)
    from .anpr import PlateResult
    from .association import Appearance

    vehicle = next(o for o in items if o.entity_type == "vehicle" and o.line_crossing)
    service.attach_plate(
        PlateResult(
            text="PB10AB1234",
            confidence=0.91,
            source_observation_id=str(vehicle.observation_id),
            detector_version="synthetic-plate-v1",
            ocr_version="synthetic-ocr-v1",
            synthetic=True,
        )
    )
    handover = []
    for camera in ("CAM01", "CAM02"):
        sample = next(o for o in reversed(items) if o.camera_id == camera)
        handover.append(
            service.attach_appearance(
                Appearance(
                    entity_id=entity_key(sample),
                    camera_id=camera,
                    timestamp=sample.timestamp,
                    direction=sample.direction,
                    embedding=[1.0, 0.0, 0.0],
                    model_version="synthetic-reid-v1",
                    source_observation_id=str(sample.observation_id),
                )
            )
        )
    counts = {}
    for item in service.repo.list_incidents(limit=1000):
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    expected = {
        k: 1
        for k in (
            "restricted_intrusion",
            "loitering",
            "abandoned_object",
            "wrong_direction",
            "vehicle_entry",
        )
    }
    if counts != expected:
        raise AssertionError(f"Unexpected demo events: {counts}; expected {expected}")
    recorder = EvidenceRecorder(service, root / "evidence")
    if videos:
        sources = root / "sources"
        sources.mkdir(exist_ok=True)
        for camera, observations in grouped.items():
            path = sources / f"{camera}.mp4"
            start, duration = render_source(path, observations)
            for incident in service.repo.list_incidents(camera_id=camera):
                evidence = recorder.record(
                    incident["incident_id"],
                    source=path,
                    source_start=start,
                    source_duration=duration,
                    synthetic=True,
                )
                with service.repo.engine.begin() as conn:
                    record = service.repo.get(db.cameras, camera)
                    record["preview_evidence_id"] = evidence["evidence_id"]
                    service.repo.put(conn, db.cameras, camera, record)
    report = {
        "synthetic": True,
        "observations": len(items),
        "incidents": counts,
        "expected": expected,
        "passed": True,
        "playable_evidence": videos,
        "negative_cameras": ["CAM-NORMAL", "CAM-NEGATIVE"],
        "synthetic_handover": handover[-1],
        "synthetic_plate": "PB10AB1234",
        "hardware_acceptance": "pending; synthetic results do not establish vision accuracy",
    }
    (root / "acceptance.json").write_text(json.dumps(report, indent=2))
    return report
