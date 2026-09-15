"""Recorded-video evidence extraction; original source remains unmodified."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import imageio_ffmpeg

from . import storage as db


class EvidenceRecorder:
    def __init__(self, service, root: str | Path):
        self.service = service
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        incident_id: str,
        *,
        source: str | Path,
        source_start: datetime,
        source_duration: float,
        pre_seconds=3.0,
        post_seconds=3.0,
        synthetic=False,
    ):
        incident = self.service.detail(incident_id)
        if incident is None:
            raise LookupError("Incident not found")
        if source_start.tzinfo is None:
            raise ValueError("source_start requires timezone")
        if min(pre_seconds, post_seconds) < 0 or source_duration <= 0:
            raise ValueError("invalid clip duration")
        source = Path(source).resolve(strict=True)
        trigger = datetime.fromisoformat(incident["end_time"] or incident["start_time"])
        relative = (trigger - source_start).total_seconds()
        if not 0 <= relative < source_duration:
            raise ValueError("Incident trigger is outside source recording")
        start = max(0, relative - pre_seconds)
        end = min(source_duration, relative + post_seconds)
        if end <= start:
            raise ValueError("Requested evidence is empty")
        directory = self.root / incident_id
        directory.mkdir(exist_ok=True)
        clip = directory / "clip.mp4"
        temporary = directory / "clip.pending.mp4"
        frame = directory / "frame.jpg"
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-ss",
                str(start),
                "-i",
                str(source),
                "-t",
                str(end - start),
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        temporary.replace(clip)
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-ss",
                str(relative - start),
                "-i",
                str(clip),
                "-frames:v",
                "1",
                str(frame),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        item = self.register(
            incident_id,
            clip,
            synthetic=synthetic,
            extra={
                "source_start": source_start.isoformat(),
                "offset_seconds": start,
                "duration_seconds": end - start,
                "trigger_offset_seconds": relative - start,
                "pre_seconds_actual": relative - start,
                "post_seconds_actual": end - relative,
                "coverage": "complete"
                if start == relative - pre_seconds and end == relative + post_seconds
                else "partial",
                "frame_path": str(frame.relative_to(self.root)),
                "source_sha256": self.digest(source),
            },
        )
        (directory / "metadata.json").write_text(json.dumps(item, indent=2))
        return item

    @staticmethod
    def digest(path):
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def register(self, incident_id, path, *, synthetic=False, extra=None):
        # Live Smart Record completion may register its finished clip through this boundary.
        path = Path(path).resolve(strict=True)
        if (
            not path.is_relative_to(self.root)
            or not path.is_file()
            or path.stat().st_size == 0
        ):
            raise ValueError("Evidence must be a nonempty file under evidence root")
        if path.suffix.lower() != ".mp4":
            raise ValueError("Expected MP4 evidence")
        if self.service.detail(incident_id) is None:
            raise LookupError("Incident not found")
        # A filename alone is not evidence of a playable video stream.
        try:
            subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-f",
                    "null",
                    "-",
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise ValueError("Evidence video could not be decoded") from exc
        evidence_id = str(
            uuid5(NAMESPACE_URL, f"evidence:{incident_id}:{self.digest(path)}")
        )
        item = {
            **(extra or {}),
            "evidence_id": evidence_id,
            "incident_id": incident_id,
            "path": str(path.relative_to(self.root)),
            "sha256": self.digest(path),
            "state": "ready",
            "synthetic": synthetic,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.service.lock, self.service.repo.engine.begin() as conn:
            self.service.repo.put(
                conn, db.evidence, evidence_id, item, incident_id=incident_id
            )
            from sqlalchemy import select

            incident = conn.execute(
                select(db.incidents.c.payload).where(
                    db.incidents.c.incident_id == incident_id
                )
            ).scalar_one()
            incident["evidence_status"] = "ready"
            self.service.repo.put(conn, db.incidents, incident_id, incident)
        return item

    def resolve(self, item, frame=False):
        relative = item.get("frame_path") if frame else item["path"]
        if not relative:
            raise FileNotFoundError("No frame available")
        path = (self.root / relative).resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise ValueError("Evidence path leaves configured root")
        return path
