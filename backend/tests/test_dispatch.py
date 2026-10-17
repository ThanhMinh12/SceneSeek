import threading
import pytest

from sceneseek.dispatch import DispatchRegistry


def test_capabilities_are_single_use():
    registry = DispatchRegistry()
    token = registry.register("alice", {"id": "private"})
    assert registry.claim(token) == {"id": "private"}
    with pytest.raises(ValueError):
        registry.claim(token)

def test_foreign_owner_cannot_cancel():
    expired = []
    registry = DispatchRegistry()
    token = registry.register("alice", 7, lambda: expired.append(True))
    assert registry.cancel(token, "bob") is False
    assert registry.claim(token) == 7
    assert expired == []


def test_capacity_and_explicit_cleanup():
    expired = []
    registry = DispatchRegistry(max_pending=1)
    token = registry.register("alice", 7, lambda: expired.append(True))
    with pytest.raises(ValueError):
        registry.register("bob", 8)
    assert registry.cancel(token, "alice") is True
    assert registry.cancel(token, "alice") is False
    assert expired == [True]


def test_abandoned_dispatch_expires():
    expired = threading.Event()
    registry = DispatchRegistry(ttl=0.02)
    token = registry.register("alice", 7, expired.set)
    assert expired.wait(1)
    with pytest.raises(ValueError):
        registry.claim(token)

