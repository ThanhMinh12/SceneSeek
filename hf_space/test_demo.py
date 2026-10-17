from pathlib import Path
from types import SimpleNamespace

import pytest

from hf_space.demo import DemoSessions
from sceneseek.embeddings import DeterministicEmbedder


@pytest.fixture
def sessions(tmp_path):
    return DemoSessions(tmp_path / 'sessions', SimpleNamespace(get=lambda: DeterministicEmbedder()),
                        Path(__file__).resolve().parents[1] / 'build/libsceneseek_core.so', max_sessions=2)


def test_rejects_path_traversal(sessions):
    with pytest.raises(ValueError):
        sessions.delete('../other-files')


def test_library_isolation_and_targeted_cleanup(sessions):
    first, second = sessions.new(), sessions.new()
    a, b = sessions.service(first), sessions.service(second)
    a.database.create_video('one', 'Private video', 'test.mp4', Path('/missing'), first)
    assert len(a.database.list_videos(first)) == 1
    assert b.database.list_videos(second) == []
    sessions.delete(first)
    assert not sessions.path(first).exists()
    assert sessions.path(second).exists()


def test_session_capacity_is_bounded(sessions):
    sessions.service(sessions.new())
    sessions.service(sessions.new())
    with pytest.raises(ValueError, match='busy'):
        sessions.service(sessions.new())


def test_search_requires_own_index(sessions):
    with pytest.raises(ValueError, match='Index a video'):
        sessions.search(sessions.new(), 'text', 'a rabbit')


def test_empty_upload_is_rejected(sessions, tmp_path):
    empty = tmp_path / 'empty.mp4'
    empty.touch()
    with pytest.raises(ValueError, match='non-empty'):
        sessions.index(sessions.new(), str(empty))
