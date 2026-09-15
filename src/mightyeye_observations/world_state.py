"""Minimal downstream consumer. Consumes only the public contract."""
from collections.abc import Iterable
from .contract import Observation

class WorldState:
    def __init__(self):
        self.tracks: dict[tuple[str, str], Observation] = {}
        self.seen = set()
        self.candidates: list[dict] = []
        self.untracked_count = 0

    def apply(self, item: Observation) -> None:
        if item.observation_id in self.seen:
            return
        self.seen.add(item.observation_id)
        if item.local_track_id is None:
            self.untracked_count += 1
            return
        key = (item.camera_id, item.local_track_id)
        prior = self.tracks.get(key)
        if prior and item.timestamp < prior.timestamp:
            return
        self.tracks[key] = item
        events = [("line_crossing", line) for line in item.line_crossing or ()]
        if prior and prior.zone != item.zone and item.zone is not None:
            events.append(("zone_enter", item.zone))
        for kind, name in events:
            self.candidates.append({"type": kind, "name": name, "camera_id": item.camera_id,
                "local_track_id": item.local_track_id, "observation_id": str(item.observation_id),
                "timestamp": item.timestamp.isoformat(), "phase": "candidate"})

    def summary(self):
        return {"observation_count": len(self.seen), "track_count": len(self.tracks),
                "untracked_count": self.untracked_count, "candidates": self.candidates}


def replay(observations: Iterable[Observation]) -> WorldState:
    state = WorldState()
    for observation in observations:
        state.apply(observation)
    return state
