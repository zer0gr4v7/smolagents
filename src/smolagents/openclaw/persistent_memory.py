"""SQLite-backed persistent memory for OpenClaw agents.

smolagents' built-in :class:`~smolagents.memory.AgentMemory` lives in-process
only - when the agent finishes, its trace evaporates. The revenue engine has
to run for *days* and learn from history, so each niche agent is paired with a
:class:`PersistentMemory` that durably stores:

* **observations**: daily per-niche metrics (traffic, conversions, revenue, ...)
* **tweaks**:       proposed parameter changes and whether they were accepted
* **notes**:        free-form journal entries the agent writes to itself
* **state**:        opaque key/value blobs (e.g. the current formula weights)

Everything is keyed by ``agent_id`` so a single SQLite file can host all ten
niche agents plus the orchestrator. Schema is versioned via ``PRAGMA user_version``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


__all__ = ["PersistentMemory", "Observation", "Tweak"]


SCHEMA_VERSION = 1


@dataclass
class Observation:
    agent_id: str
    day: int
    metrics: dict[str, float]
    timestamp: float

    def to_row(self) -> tuple[str, int, str, float]:
        return self.agent_id, self.day, json.dumps(self.metrics), self.timestamp

    @classmethod
    def from_row(cls, row: tuple[str, int, str, float]) -> "Observation":
        return cls(agent_id=row[0], day=row[1], metrics=json.loads(row[2]), timestamp=row[3])


@dataclass
class Tweak:
    agent_id: str
    day: int
    lever: str
    direction: int
    accepted: bool
    delta_revenue: float
    timestamp: float


_INIT_SQL = """
CREATE TABLE IF NOT EXISTS observations (
    agent_id   TEXT NOT NULL,
    day        INTEGER NOT NULL,
    metrics    TEXT NOT NULL,
    timestamp  REAL NOT NULL,
    PRIMARY KEY (agent_id, day)
);

CREATE TABLE IF NOT EXISTS tweaks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    day             INTEGER NOT NULL,
    lever           TEXT NOT NULL,
    direction       INTEGER NOT NULL,
    accepted        INTEGER NOT NULL,
    delta_revenue   REAL NOT NULL,
    timestamp       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tweaks_agent_day ON tweaks(agent_id, day);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    day         INTEGER NOT NULL,
    note        TEXT NOT NULL,
    timestamp   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_agent ON notes(agent_id);

CREATE TABLE IF NOT EXISTS state (
    agent_id    TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (agent_id, key)
);
"""


class PersistentMemory:
    """Thread-safe SQLite store for OpenClaw agents.

    Use ``":memory:"`` for the path to get an ephemeral in-process database
    (useful in tests). Anything else is treated as a filesystem path that
    will be created on first use.
    """

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False lets the orchestrator hand the same memory
        # to subagents on different threads; the lock below serializes writes.
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_INIT_SQL)
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current == 0:
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif current != SCHEMA_VERSION:
                raise RuntimeError(
                    f"OpenClaw memory schema mismatch: db has v{current}, code expects v{SCHEMA_VERSION}"
                )

    # ---- observations ----------------------------------------------------

    def record_observation(self, agent_id: str, day: int, metrics: dict[str, float]) -> Observation:
        obs = Observation(agent_id=agent_id, day=day, metrics=metrics, timestamp=time.time())
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO observations(agent_id, day, metrics, timestamp) VALUES (?,?,?,?)",
                obs.to_row(),
            )
        return obs

    def latest_observation(self, agent_id: str) -> Observation | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT agent_id, day, metrics, timestamp FROM observations "
                "WHERE agent_id=? ORDER BY day DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
        return Observation.from_row(row) if row else None

    def observations(self, agent_id: str) -> list[Observation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT agent_id, day, metrics, timestamp FROM observations "
                "WHERE agent_id=? ORDER BY day ASC",
                (agent_id,),
            ).fetchall()
        return [Observation.from_row(r) for r in rows]

    def iter_observations(self) -> Iterator[Observation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT agent_id, day, metrics, timestamp FROM observations ORDER BY day ASC, agent_id ASC"
            ).fetchall()
        for r in rows:
            yield Observation.from_row(r)

    # ---- tweaks ----------------------------------------------------------

    def record_tweak(
        self,
        agent_id: str,
        day: int,
        lever: str,
        direction: int,
        accepted: bool,
        delta_revenue: float,
    ) -> Tweak:
        tw = Tweak(
            agent_id=agent_id,
            day=day,
            lever=lever,
            direction=direction,
            accepted=accepted,
            delta_revenue=delta_revenue,
            timestamp=time.time(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO tweaks(agent_id, day, lever, direction, accepted, delta_revenue, timestamp) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    tw.agent_id,
                    tw.day,
                    tw.lever,
                    tw.direction,
                    int(tw.accepted),
                    tw.delta_revenue,
                    tw.timestamp,
                ),
            )
        return tw

    def tweaks(self, agent_id: str) -> list[Tweak]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT agent_id, day, lever, direction, accepted, delta_revenue, timestamp "
                "FROM tweaks WHERE agent_id=? ORDER BY day ASC, id ASC",
                (agent_id,),
            ).fetchall()
        return [
            Tweak(
                agent_id=r[0],
                day=r[1],
                lever=r[2],
                direction=r[3],
                accepted=bool(r[4]),
                delta_revenue=r[5],
                timestamp=r[6],
            )
            for r in rows
        ]

    # ---- free-form notes -------------------------------------------------

    def add_note(self, agent_id: str, day: int, note: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO notes(agent_id, day, note, timestamp) VALUES (?,?,?,?)",
                (agent_id, day, note, time.time()),
            )

    def notes(self, agent_id: str, limit: int | None = None) -> list[str]:
        sql = "SELECT note FROM notes WHERE agent_id=? ORDER BY id DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._conn.execute(sql, (agent_id,)).fetchall()
        return [r[0] for r in rows]

    # ---- opaque state blobs ---------------------------------------------

    def set_state(self, agent_id: str, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO state(agent_id, key, value, updated_at) VALUES (?,?,?,?)",
                (agent_id, key, json.dumps(value), time.time()),
            )

    def get_state(self, agent_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM state WHERE agent_id=? AND key=?",
                (agent_id, key),
            ).fetchone()
        return json.loads(row[0]) if row else default

    # ---- lifecycle -------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "PersistentMemory":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
