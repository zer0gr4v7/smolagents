from pathlib import Path

import pytest

from smolagents.openclaw import PersistentMemory


def test_observation_round_trip_in_memory():
    mem = PersistentMemory(":memory:")
    obs = mem.record_observation("outdoor_gear", day=1, metrics={"revenue": 12.5, "clicks": 99})
    assert obs.day == 1
    assert obs.metrics["revenue"] == 12.5
    latest = mem.latest_observation("outdoor_gear")
    assert latest is not None
    assert latest.metrics["clicks"] == 99
    mem.close()


def test_observation_replace_on_same_day():
    mem = PersistentMemory(":memory:")
    mem.record_observation("a", 1, {"revenue": 1.0})
    mem.record_observation("a", 1, {"revenue": 2.0})
    obs = mem.observations("a")
    assert len(obs) == 1
    assert obs[0].metrics["revenue"] == 2.0
    mem.close()


def test_tweak_log_orders_by_day():
    mem = PersistentMemory(":memory:")
    mem.record_tweak("a", 2, "ctr", 1, accepted=True, delta_revenue=5.0)
    mem.record_tweak("a", 1, "traffic", -1, accepted=False, delta_revenue=-1.0)
    tw = mem.tweaks("a")
    assert [t.day for t in tw] == [1, 2]
    assert tw[0].accepted is False
    assert tw[1].accepted is True
    mem.close()


def test_state_kv_blob():
    mem = PersistentMemory(":memory:")
    mem.set_state("agent1", "weights", {"ctr": 1.2, "cr": 0.9})
    mem.set_state("agent1", "weights", {"ctr": 1.5})  # overwrite
    assert mem.get_state("agent1", "weights") == {"ctr": 1.5}
    assert mem.get_state("agent1", "missing", default=42) == 42
    mem.close()


def test_notes_returned_newest_first():
    mem = PersistentMemory(":memory:")
    mem.add_note("a", 1, "first")
    mem.add_note("a", 2, "second")
    mem.add_note("a", 3, "third")
    assert mem.notes("a", limit=2) == ["third", "second"]
    mem.close()


def test_persistence_across_reopen(tmp_path: Path):
    db = tmp_path / "oc.db"
    with PersistentMemory(db) as mem:
        mem.record_observation("a", 1, {"revenue": 7.0})
        mem.set_state("a", "params", {"traffic": 100})
    with PersistentMemory(db) as mem2:
        assert mem2.latest_observation("a").metrics["revenue"] == 7.0
        assert mem2.get_state("a", "params") == {"traffic": 100}


def test_schema_version_mismatch_raises(tmp_path: Path):
    db = tmp_path / "v.db"
    with PersistentMemory(db) as _:
        pass
    # Tamper with schema version
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="schema mismatch"):
        PersistentMemory(db)
