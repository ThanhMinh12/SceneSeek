from pathlib import Path

import numpy as np
import pytest

from sceneseek.catalog import Catalog
from sceneseek.database import Database
from sceneseek.native import SimilarityIndex


@pytest.fixture(params=["numpy", "cpp"])
def index(request):
    native = SimilarityIndex()
    if request.param == "numpy":
        native._library = None
    elif native.backend != "cpp":
        pytest.skip("Build the native library before running parity tests")
    return native


@pytest.mark.parametrize("rate", [0.5, 0.75, 1.0, 1.25, 1.5, 2.0])
def test_playback_rate_uses_seconds_not_frame_indices(tmp_path: Path, index, rate):
    database = Database(tmp_path / "catalog.sqlite3")
    database.create_video("target", "Target", "target.mp4", tmp_path / "target.mp4")
    database.update_video("target", status="ready", duration_seconds=40, frame_count=20)
    catalog = Catalog(tmp_path, database, index)
    target = np.eye(20, dtype=np.float32)
    timestamps = np.arange(20) * 2.0
    catalog.save("target", target, timestamps.tolist(), [f"{i:06}.jpg" for i in range(20)], "test")
    duration = 12 / rate
    query_times = np.arange(0, duration, 0.1)
    source_times = 6 + query_times * rate
    query = np.column_stack([
        np.interp(source_times, timestamps, target[:, dimension])
        for dimension in range(20)
    ]).astype(np.float32)

    result = catalog.search_sequence(
        query, "test", 1, query_timestamps=query_times.tolist(), query_duration=duration,
    )[0]

    assert result["timestamp_seconds"] == pytest.approx(6)
    assert result["end_seconds"] == pytest.approx(18)
    assert result["playback_rate"] == pytest.approx(rate)
    assert result["score"] > 0.999


def test_rounding_matches_cpp_at_half_indices(index):
    target = np.eye(5, dtype=np.float32)
    # llround([0, .5, 1]) -> [0, 1, 1], not [0, 0, 1].
    query = target[[1, 2, 2]]
    match = index.best_sequence(query, target, rates=(0.5,))
    assert match is not None
    assert match[0] > 0.999
    assert match[1:3] == (1, 2)


def test_invalid_rates_are_ignored(index):
    target = np.eye(3, dtype=np.float32)
    assert index.best_sequence(target, target, rates=(0, -1, float("nan"))) is None


def test_one_codec_or_cut_outlier_does_not_dominate_alignment(index):
    target = np.eye(5, dtype=np.float32)
    query = target.copy()
    query[3] *= -1
    match = index.best_sequence(query, target, rates=(1.0,))
    assert match is not None
    assert match[1:3] == (0,4)
    assert match[0] == pytest.approx(1.0, abs=1e-6)
