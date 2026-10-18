from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import threading
import json
import subprocess

import numpy as np
import pytest

from sceneseek.catalog import Catalog
from sceneseek.database import Database
from sceneseek.engine import NativeEngine
from sceneseek.native import SimilarityIndex
from sceneseek.reference_catalog import ReferenceCatalog


@pytest.fixture
def native():
    index = SimilarityIndex()
    assert index.backend == 'cpp', 'Build the C++ core before running engine integration tests'
    return index


def seed(database, video_id, owner='a', duration=30):
    database.create_video(video_id, video_id, video_id+'.mp4', Path(video_id+'.mp4'), owner)
    database.update_video(video_id, status='ready', duration_seconds=duration)


@pytest.mark.parametrize('workers', [1, 4])
def test_frame_ranking_and_temporal_dedup_match_reference(tmp_path, native, workers):
    database = Database(tmp_path/'db.sqlite3')
    native_dir, reference_dir = tmp_path/'native', tmp_path/'reference'
    native_dir.mkdir(); reference_dir.mkdir()
    catalog = Catalog(native_dir, database, native, cache_bytes=4096, workers=workers)
    fallback = SimilarityIndex(); fallback._library = None
    reference = ReferenceCatalog(reference_dir, database, fallback)
    random = np.random.default_rng(19)
    for i in range(5):
        video_id = f'video-{i}'
        seed(database, video_id, owner='a' if i < 4 else 'b')
        matrix = random.normal(size=(60, 16)).astype(np.float32)
        timestamps = (np.arange(60)*.5).tolist()
        names = [f'{row:06}.jpg' for row in range(60)]
        for target in (catalog, reference):
            target.save(video_id, matrix, timestamps, names, 'model')
    for _ in range(12):
        query = random.normal(size=16).astype(np.float32)
        actual = catalog.search_frames(query, 'model', 12, owner_id='a')
        expected = reference.search_frames(query, 'model', 12, owner_id='a')
        assert [(r['video_id'], r['timestamp_seconds'], r['thumbnail_url']) for r in actual] == [
            (r['video_id'], r['timestamp_seconds'], r['thumbnail_url']) for r in expected]
        np.testing.assert_allclose([r['score'] for r in actual], [r['score'] for r in expected], atol=1e-6)
        assert all(r['video_id'] != 'video-4' for r in actual)
    assert catalog.engine.stats()['cached_bytes'] <= 4096


def test_cpp_owns_files_and_serves_after_restart(tmp_path, native):
    database = Database(tmp_path/'db.sqlite3')
    seed(database, 'a')
    catalog = Catalog(tmp_path, database, native)
    catalog.save('a', np.eye(3, dtype=np.float32), [0, 3, 6], ['a.jpg','b.jpg','c.jpg'], 'model')
    assert (tmp_path/'a.ssidx').is_file() and not (tmp_path/'a.npz').exists()
    catalog.engine.close()
    reopened = Catalog(tmp_path, database, native)
    assert reopened.search_frames(np.array([1,0,0]), 'model', 1, 'a')[0]['timestamp_seconds'] == 0
    assert reopened.search_frames(np.array([1,0,0]), 'different-model', 1, 'a') == []
    reopened.remove('a')
    assert not (tmp_path/'a.ssidx').exists()


def test_authorized_legacy_migration_keeps_recoverable_archives(tmp_path, native):
    database = Database(tmp_path/'db.sqlite3')
    fallback = SimilarityIndex(); fallback._library = None
    legacy = ReferenceCatalog(tmp_path, database, fallback)
    for video, owner in [('mine','a'), ('foreign','b')]:
        seed(database, video, owner)
        legacy.save(video, np.eye(3, dtype=np.float32), [0,3,6], ['0.jpg','1.jpg','2.jpg'], 'model')
    catalog = Catalog(tmp_path, database, native)
    assert catalog.search_frames(np.array([1,0,0]), 'model', 1, 'a')[0]['video_id'] == 'mine'
    assert (tmp_path/'mine.ssidx').exists() and (tmp_path/'mine.npz').exists()
    assert not (tmp_path/'foreign.ssidx').exists()
    catalog.remove('mine')
    assert not (tmp_path/'mine.ssidx').exists() and not (tmp_path/'mine.npz').exists()
    assert (tmp_path/'foreign.npz').exists()


def test_corrupt_shard_is_skipped_without_python_fallback(tmp_path, native):
    database = Database(tmp_path/'db.sqlite3')
    seed(database, 'bad'); seed(database, 'good')
    catalog = Catalog(tmp_path, database, native)
    for video in ('bad','good'):
        catalog.save(video, np.eye(2, dtype=np.float32), [0,3], ['0.jpg','1.jpg'], 'model')
    (tmp_path/'bad.ssidx').write_bytes(b'broken header')
    result = catalog.search_frames(np.array([1,0]), 'model', 5, 'a')
    assert result and all(r['video_id'] == 'good' for r in result)
    assert catalog.engine.stats()['skipped_shards'] >= 1


@pytest.mark.parametrize('bad_id', ['../a', '/absolute', 'nested/name', 'a\0b', '', '..'])
def test_invalid_ids_cannot_escape_catalog(tmp_path, native, bad_id):
    engine = NativeEngine(native._library, tmp_path)
    with pytest.raises(ValueError):
        engine.save(bad_id, np.eye(2, dtype=np.float32), [0,3], ['0.jpg','1.jpg'], 'model')


@pytest.mark.parametrize('kind', ['nan', 'dimensions', 'timestamps', 'thumbnail'])
def test_invalid_buffers_are_rejected_without_destroying_old_index(tmp_path, native, kind):
    engine = NativeEngine(native._library, tmp_path)
    engine.save('a', np.eye(2, dtype=np.float32), [0,3], ['0.jpg','1.jpg'], 'model')
    matrix, times, names = np.eye(2, dtype=np.float32), [0,3], ['0.jpg','1.jpg']
    if kind == 'nan': matrix[0,0] = np.nan
    if kind == 'dimensions': matrix = np.ones((0,2))
    if kind == 'timestamps': times = [3,0]
    if kind == 'thumbnail': names[0] = '../private'
    with pytest.raises(ValueError): engine.save('a', matrix, times, names, 'model')
    allowed = [{'id':'a', 'duration_seconds':6}]
    assert engine.search(np.array([1,0]), 'model', allowed, 1)[0][1].score > .999


def test_empty_allowlist_does_not_touch_another_sessions_cache(tmp_path, native):
    engine = NativeEngine(native._library, tmp_path)
    engine.save('private', np.eye(2, dtype=np.float32), [0,3], ['0.jpg','1.jpg'], 'model')
    before = engine.stats()
    assert engine.search(np.array([1,0]), 'model', [], 3) == []
    assert engine.stats() == before


def test_deletion_during_legacy_migration_does_not_resurrect_files(tmp_path, native):
    database = Database(tmp_path/'db.sqlite3')
    seed(database, 'a')
    fallback = SimilarityIndex(); fallback._library = None
    ReferenceCatalog(tmp_path, database, fallback).save('a', np.eye(2, dtype=np.float32), [0,3], ['0.jpg','1.jpg'], 'model')
    catalog = Catalog(tmp_path, database, native)
    entered, deleted = threading.Event(), threading.Event()
    original = catalog._reference._load
    def waiting_load(video_id):
        entered.set()
        assert deleted.wait(5)
        return original(video_id)
    waiting_load.cache_clear = original.cache_clear
    catalog._reference._load = waiting_load
    def remove():
        assert entered.wait(5)
        database.delete_video('a')
        deleted.set()
        catalog.remove('a')
    with ThreadPoolExecutor(max_workers=2) as pool:
        search = pool.submit(catalog.search_frames, np.array([1,0]), 'model', 1, 'a')
        deletion = pool.submit(remove)
        search.result(timeout=10); deletion.result(timeout=10)
    assert not (tmp_path/'a.ssidx').exists() and not (tmp_path/'a.npz').exists()


def test_unbuilt_fallback_cannot_silently_serve_native_library(tmp_path, native):
    database = Database(tmp_path/'db.sqlite3')
    seed(database, 'a')
    Catalog(tmp_path, database, native).save('a', np.eye(2, dtype=np.float32), [0,3], ['0.jpg','1.jpg'], 'model')
    fallback = SimilarityIndex(); fallback._library = None
    catalog = Catalog(tmp_path, database, fallback)
    with pytest.raises(RuntimeError, match='uses native indexes'):
        catalog.search_frames(np.array([1,0]), 'model', 1, 'a')


def test_concurrent_bridge_calls_hold_owned_immutable_snapshots(tmp_path, native):
    engine = NativeEngine(native._library, tmp_path, cache_bytes=4096, workers=2)
    allowed = [{'id':'a', 'duration_seconds':6}]
    engine.save('a', np.eye(2, dtype=np.float32), [0,3], ['0.jpg','1.jpg'], 'model')
    def operation(i):
        if i % 4 == 0:
            engine.save('a', np.eye(2, dtype=np.float32)[::-1], [0,3], ['0.jpg','1.jpg'], 'model')
        else:
            assert engine.search(np.array([1,0]), 'model', allowed, 1)[0][1].score > .999
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(operation, range(80)))
    engine.close()
    with pytest.raises(RuntimeError): engine.stats()


def test_cli_build_inspect_and_query_native_index(tmp_path):
    binary = Path(__file__).resolve().parents[2]/'build/sceneseek'
    matrix = tmp_path/'matrix.txt'; matrix.write_text('3 2\n1 0\n0 1\n-1 0\n')
    query = tmp_path/'query.txt'; query.write_text('1 2\n1 0\n')
    def run(*args):
        return json.loads(subprocess.check_output([str(binary), *map(str,args)], text=True))
    assert run('index', tmp_path, 'a', 'model', matrix, 3)['indexed_rows'] == 3
    assert run('inspect', tmp_path, 'a')['dimensions'] == 2
    result = run('search', tmp_path, 'model', query, 'a:9')
    assert result[0]['video_id'] == 'a' and result[0]['timestamp_seconds'] == 0
