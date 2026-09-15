import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError
from mightyeye_observations.contract import Observation
from mightyeye_observations.deepstream.adapter import DeepStreamAdapter, UNTRACKED_OBJECT_ID
from mightyeye_observations.io import read_observations, write_observations
from mightyeye_observations.synthetic import generate
from mightyeye_observations.world_state import replay, WorldState


def convert(**overrides):
    obj = NS(rect_params=NS(left=100, top=100, width=200, height=300),
             confidence=0.9, object_id=7, class_id=0)
    for k in list(overrides):
        if hasattr(obj, k):
            setattr(obj, k, overrides.pop(k))
    adapter = DeepStreamAdapter(camera_id='cam-01', session_id='run-1',
                               model_version='detector-v1', class_map={0: 'person'})
    kwargs = dict(frame_number=1, object_index=0, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                  frame_width=1000, frame_height=1000)
    kwargs.update(overrides)
    return adapter.convert_object(obj, **kwargs)


def test_adapter_contract_and_stable_identity():
    item = convert(zone='entrance', direction='right', line_crossing=('gate',), evidence_pointer='evidence/1.jpg')
    assert item.bbox == (0.1, 0.1, 0.3, 0.4)
    assert item.local_track_id == 'run-1:7'
    assert item.line_crossing == ('gate',)
    assert item.observation_id == convert().observation_id
    assert item.observation_id != convert(object_index=1).observation_id
    assert set(item.model_dump()) == {'observation_id', 'camera_id', 'timestamp', 'local_track_id',
        'entity_type', 'bbox', 'confidence', 'zone', 'direction', 'line_crossing', 'model_version', 'evidence_pointer'}
    assert Observation.model_validate_json(item.model_dump_json()) == item


def test_unknown_and_untracked_sentinels():
    item = convert(object_id=UNTRACKED_OBJECT_ID, confidence=-0.10000000149, class_id=999)
    assert item.local_track_id is None
    assert item.confidence is None
    assert item.entity_type == 'unknown'


@pytest.mark.parametrize('kwargs', [
    {'confidence': 1.1}, {'confidence': float('nan')}, {'confidence': -0.5},
    {'timestamp': datetime(2026, 1, 1)}, {'frame_width': 0}, {'frame_number': -1},
    {'rect_params': NS(left=0, top=0, width=-1, height=1)},
    {'rect_params': NS(left=float('nan'), top=0, width=1, height=1)},
    {'rect_params': NS(left=1100, top=0, width=10, height=10)},
])
def test_bad_metadata_rejected(kwargs):
    with pytest.raises(ValueError):
        convert(**kwargs)


def test_clips_to_frame():
    assert convert(rect_params=NS(left=-10, top=0, width=1100, height=100)).bbox == (0, 0, 1, 0.1)


@pytest.mark.parametrize('patch', [{'bbox': [0.5, 0, 0.1, 1]}, {'confidence': 2},
    {'camera_id': ''}, {'unexpected_vendor_field': 1}, {'timestamp': '2026-01-01T00:00:00'}])
def test_wire_contract_rejects_bad_data(patch):
    data = convert().model_dump(mode='json')
    data.update(patch)
    with pytest.raises(ValidationError):
        Observation.model_validate(data)


@pytest.mark.parametrize('extension', ['.json', '.jsonl'])
def test_offline_roundtrip_and_replay(tmp_path, extension):
    items = list(generate())
    path = tmp_path / ('observations' + extension)
    assert write_observations(path, items) == 30
    assert list(read_observations(path)) == items
    state = replay(read_observations(path))
    assert state.summary()['track_count'] == 1
    assert len(state.candidates) == 1
    assert state.candidates[0]['type'] == 'line_crossing'
    for item in items:
        state.apply(item)
    assert state.summary()['observation_count'] == 30
    assert len(state.candidates) == 1
    with pytest.raises(FileExistsError):
        write_observations(path, items)


def test_synthetic_scenarios():
    assert list(generate(seed=5)) == list(generate(seed=5))
    assert list(generate(seed=5)) != list(generate(seed=6))
    state = replay(generate(scenario='multi-camera'))
    assert state.summary()['track_count'] == 2
    state = replay(generate(scenario='zone-entry'))
    assert [c['type'] for c in state.candidates] == ['zone_enter']


def test_old_data_cannot_rewind_track_and_untracked_not_merged():
    items = list(generate())
    state = WorldState()
    state.apply(items[-1])
    state.apply(items[0])
    assert next(iter(state.tracks.values())) == items[-1]
    state.apply(convert(object_id=UNTRACKED_OBJECT_ID))
    assert state.untracked_count == 1
    assert len(state.tracks) == 1


def test_error_includes_line(tmp_path):
    path = tmp_path / 'bad.jsonl'
    path.write_text(convert().model_dump_json() + '\n{}\n')
    with pytest.raises(ValueError, match='line 2'):
        list(read_observations(path))


def test_live_frame_traversal_with_sdk_double(monkeypatch):
    obj = NS(rect_params=NS(left=0, top=0, width=10, height=10), confidence=0.8, object_id=1, class_id=0)
    monkeypatch.setitem(sys.modules, 'pyds', NS(NvDsObjectMeta=NS(cast=lambda x: x)))
    frame = NS(frame_num=1, obj_meta_list=NS(data=obj, next=NS(data=obj, next=None)))
    adapter = DeepStreamAdapter(camera_id='cam', session_id='session', model_version='v1', class_map={0:'person'})
    result = adapter.convert_frame(frame, timestamp=datetime.now(timezone.utc), frame_width=100, frame_height=100)
    assert len(result) == 2
    assert result[0].observation_id != result[1].observation_id
    frame.obj_meta_list = None
    assert adapter.convert_frame(frame, timestamp=datetime.now(timezone.utc), frame_width=100, frame_height=100) == []


def test_sdk_import_boundary():
    root = Path(__file__).parents[1] / 'src' / 'mightyeye_observations'
    for file in root.rglob('*.py'):
        if 'deepstream' in file.parts:
            continue
        for node in ast.walk(ast.parse(file.read_text())):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            assert not any(any(part in {'pyds', 'gi', 'deepstream'} for part in name.split('.')) for name in names), file


def test_committed_schema_matches_model():
    schema = Path(__file__).parents[1] / 'schemas' / 'observation-v1.schema.json'
    assert json.loads(schema.read_text()) == Observation.model_json_schema()


def test_cli_replay_in_process_without_sdk(tmp_path):
    import os
    import subprocess
    path = tmp_path / 'fixture.jsonl'
    write_observations(path, generate())
    root = Path(__file__).parents[1]
    script = '''
import importlib.abc
import sys
class RejectSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pyds', 'gi'}:
            raise AssertionError('Offline replay attempted to load NVIDIA runtime')
sys.meta_path.insert(0, RejectSDK())
from mightyeye_observations.cli import main
main()
'''
    result = subprocess.run([sys.executable, '-c', script, 'replay', str(path)],
        capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': str(root / 'src')})
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary['observation_count'] == 30
    assert len(summary['candidates']) == 1


def test_adapter_json_can_feed_downstream(tmp_path):
    items = [convert(frame_number=0), convert(frame_number=1, line_crossing=('gate',))]
    path = tmp_path / 'adapter.jsonl'
    write_observations(path, items)
    state = replay(read_observations(path))
    assert state.summary()['track_count'] == 1
    assert state.candidates[0]['observation_id'] == str(items[-1].observation_id)
