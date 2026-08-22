from __future__ import annotations

import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet

from infrastructure.storage.events.activity_store import (
    PostgresRecordedActivityStore,
    SQLiteRecordedActivityStore,
)


def test_sqlite_graph_cutover_drops_flat_activity_results(tmp_path: Path) -> None:
    database = tmp_path / "activities.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE harness_activity_results "
            "(activity_id TEXT PRIMARY KEY, ciphertext BLOB NOT NULL)"
        )
        connection.execute(
            "INSERT INTO harness_activity_results (activity_id, ciphertext) "
            "VALUES (?, ?)",
            ("legacy-activity", b"legacy-ciphertext"),
        )

    SQLiteRecordedActivityStore(database, encryption_key=Fernet.generate_key())

    with sqlite3.connect(database) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert "harness_activity_results" not in tables
    assert {"event_activity_payloads", "event_activity_records"} <= tables


def test_recorded_activity_stores_expose_no_flat_result_api() -> None:
    for store_type in (SQLiteRecordedActivityStore, PostgresRecordedActivityStore):
        assert not hasattr(store_type, "put_result")
        assert not hasattr(store_type, "resolve_result")
