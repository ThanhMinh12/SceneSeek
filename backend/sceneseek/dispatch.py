"""Short-lived, single-use browser-dispatch capabilities for queued inference."""
from __future__ import annotations

import secrets
import threading


class DispatchRegistry:
    def __init__(self, max_pending: int = 8, ttl: float = 180):
        self.max_pending = max_pending
        self.ttl = ttl
        self._entries = {}
        self._lock = threading.RLock()

    def register(self, owner: str, payload, on_expire=lambda: None) -> str:
        with self._lock:
            if len(self._entries) >= self.max_pending:
                raise ValueError("The inference queue is full. Try again shortly.")
            token = secrets.token_urlsafe(32)
            timer = threading.Timer(self.ttl, self.cancel, args=(token,))
            timer.daemon = True
            self._entries[token] = (owner, payload, on_expire, timer)
            timer.start()
            return token

    def claim(self, token: str):
        with self._lock:
            entry = self._entries.pop(token, None)
        if entry is None:
            raise ValueError("This inference request expired or was already started. Submit it again.")
        entry[3].cancel()
        return entry[1]

    def cancel(self, token: str, owner: str | None = None):
        with self._lock:
            entry = self._entries.get(token)
            if entry is None or (owner is not None and not secrets.compare_digest(owner, entry[0])):
                return False
            del self._entries[token]
        entry[3].cancel()
        entry[2]()
        return True
