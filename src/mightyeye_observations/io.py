"""Portable JSON array / JSONL storage, with contextual validation errors."""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from .contract import Observation


def read_observations(path: str | Path) -> Iterator[Observation]:
    path = Path(path)
    with path.open(encoding="utf-8") as stream:
        if path.suffix == ".json":
            payload = json.load(stream)
            if not isinstance(payload, list):
                raise ValueError(f"{path}: expected a JSON array")
            for index, item in enumerate(payload, 1):
                try:
                    yield Observation.model_validate(item)
                except ValueError as exc:
                    raise ValueError(f"{path}: observation {index}: {exc}") from exc
        else:
            for index, line in enumerate(stream, 1):
                if line.strip():
                    try:
                        yield Observation.model_validate_json(line)
                    except ValueError as exc:
                        raise ValueError(f"{path}: line {index}: {exc}") from exc


def write_observations(path: str | Path, observations: Iterable[Observation]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = list(observations)
    # Exclusive creation protects existing recordings from accidental overwrite.
    with path.open("x", encoding="utf-8") as stream:
        if path.suffix == ".json":
            json.dump(
                [o.model_dump(mode="json") for o in items],
                stream,
                indent=2,
                allow_nan=False,
            )
            stream.write("\n")
        else:
            for item in items:
                stream.write(item.model_dump_json() + "\n")
    return len(items)
