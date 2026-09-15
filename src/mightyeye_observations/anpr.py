"""ANPR provider boundary. Detector/OCR models are supplied by deployment."""

import re
from typing import Protocol

from PIL import Image
from pydantic import Field

from .domain import StrictModel


class PlateResult(StrictModel):
    text: str = Field(min_length=4, max_length=20, pattern=r"^[A-Z0-9]+$")
    confidence: float = Field(ge=0, le=1)
    source_observation_id: str
    detector_version: str
    ocr_version: str
    synthetic: bool = False


class PlateDetector(Protocol):
    def detect(self, vehicle_crop: Image.Image) -> list[tuple[int, int, int, int]]: ...


class OCR(Protocol):
    def read(self, plate_crop: Image.Image) -> tuple[str, float]: ...


def recognize(
    frame: Image.Image,
    observation,
    detector: PlateDetector,
    ocr: OCR,
    *,
    detector_version: str,
    ocr_version: str,
    minimum_confidence=0.8,
):
    if observation.entity_type != "vehicle":
        raise ValueError("ANPR requires a vehicle observation")
    w, h = frame.size
    a, b, c, d = observation.bbox
    vehicle = frame.crop((int(a * w), int(b * h), int(c * w), int(d * h)))
    results = []
    for box in detector.detect(vehicle):
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= vehicle.width and 0 <= y1 < y2 <= vehicle.height):
            raise ValueError("Plate detector returned an invalid crop")
        text, confidence = ocr.read(vehicle.crop(box))
        text = re.sub(r"[^A-Z0-9]", "", text.upper())
        if confidence >= minimum_confidence and 4 <= len(text) <= 20:
            results.append(
                PlateResult(
                    text=text,
                    confidence=confidence,
                    source_observation_id=str(observation.observation_id),
                    detector_version=detector_version,
                    ocr_version=ocr_version,
                )
            )
    # Ambiguous readings are not forced into a single plate.
    return results[0] if len(results) == 1 else None
