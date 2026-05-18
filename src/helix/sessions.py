"""In-memory elicitation sessions.

A session carries the partial answers for one in-flight intent so the user
can be asked one thing at a time. Sessions are evicted after ``TTL`` seconds,
so an abandoned wizard does not leak. Thread-safe to mirror ``Atlas``.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

TTL = 1800  # 30 minutes


@dataclass
class Session:
    id: str
    intent: str
    answers: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self, ttl: int = TTL):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._data: dict[str, Session] = {}

    def _evict(self) -> None:
        cutoff = time.time() - self._ttl
        for sid in [s.id for s in self._data.values() if s.ts < cutoff]:
            del self._data[sid]

    def open(self, intent: str) -> Session:
        with self._lock:
            self._evict()
            sid = f"ask_{secrets.token_hex(3)}"
            s = Session(id=sid, intent=intent)
            self._data[sid] = s
            return s

    def get(self, sid: str) -> Session | None:
        with self._lock:
            self._evict()
            return self._data.get(sid)

    def update(self, sid: str, answers: dict) -> Session | None:
        with self._lock:
            self._evict()
            s = self._data.get(sid)
            if s is None:
                return None
            s.answers.update(answers)
            s.ts = time.time()
            return s

    def close(self, sid: str) -> None:
        with self._lock:
            self._data.pop(sid, None)


# Process-wide store shared by the CLI today and the MCP server later.
SESSIONS = SessionStore()
