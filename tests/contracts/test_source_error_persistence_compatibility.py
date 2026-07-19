from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

from business.foundation.models.source_error_normalization import normalize_source_errors
from business.layers.signal.artifact_refs import SignalArtifactRef
from business.layers.signal.artifacts import SourceArtifactWriter
from framework.artifacts import ArtifactManager
from framework.events.canonical import StoredEvent
from framework.events.runtime.replay_engine import ReplayCheckpoint


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "source_policy_persistence"
ERROR_ARTIFACT_PATH = (
    FIXTURE_ROOT
    / "sources"
    / "errors"
    / "rss-source"
    / "legacy-fetch-timeout.json"
)


def test_historical_source_error_reader_is_lossless_and_does_not_mutate_input() -> None:
    fixture_bytes = ERROR_ARTIFACT_PATH.read_bytes()
    payload = _load_json(ERROR_ARTIFACT_PATH)["error"]
    snapshot = deepcopy(payload)

    [error] = normalize_source_errors([payload])

    assert payload == snapshot
    assert error.retryable is False
    assert error.request_ref == {"artifact_id": "request-ref"}
    assert error.response_ref == {"artifact_id": "response-ref"}
    assert error.occurred_at.utcoffset() == timedelta(hours=8)
    assert error.metadata["nested"] == {"attempts": [1, 2]}
    assert error.metadata["retryable"] is False
    assert ERROR_ARTIFACT_PATH.read_bytes() == fixture_bytes


def test_committed_source_error_artifact_index_uses_real_model_readers() -> None:
    index_path = FIXTURE_ROOT / "source_artifacts" / "index.json"
    index = _load_json(index_path)
    [entry] = [
        value for value in index["entries"] if value["artifact_type"] == "source_error"
    ]
    artifact_ref = SignalArtifactRef.from_dict(entry["artifact_ref"])
    artifact_payload = _load_json(FIXTURE_ROOT / artifact_ref.path)
    [error] = normalize_source_errors([artifact_payload["error"]])

    assert artifact_ref.run_id == "legacy-source-run"
    assert artifact_ref.path == "sources/errors/rss-source/legacy-fetch-timeout.json"
    assert entry["request_ref"] == error.request_ref
    assert entry["response_ref"] == error.response_ref
    assert error.url == "https://example.com/News/?topic=AI"
    assert error.retryable is False


def test_source_error_artifact_and_index_preserve_historical_contract(
    tmp_path: Path,
) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("legacy-source-error-run")
    legacy_payload = _load_json(ERROR_ARTIFACT_PATH)["error"]
    [error] = normalize_source_errors([legacy_payload])

    index = SourceArtifactWriter(manager).write_source_artifacts(
        "legacy-source-error-run",
        source_errors=[error],
    )

    assert index is not None
    [entry] = [
        value for value in index["entries"] if value["artifact_type"] == "source_error"
    ]
    error_paths = list(
        (tmp_path / "legacy-source-error-run" / "sources" / "errors").rglob("*.json")
    )
    assert len(error_paths) == 1
    assert index["error_count"] == 1
    payload = json.loads(
        (tmp_path / "legacy-source-error-run" / entry["path"]).read_text(
            encoding="utf-8"
        )
    )
    assert entry["request_ref"] == {"artifact_id": "request-ref"}
    assert entry["response_ref"] == {"artifact_id": "response-ref"}
    assert payload["error"]["retryable"] is False
    assert payload["error"]["request_ref"] == {"artifact_id": "request-ref"}
    assert payload["error"]["response_ref"] == {"artifact_id": "response-ref"}
    assert payload["error"]["occurred_at"] == "2026-07-19T16:30:00+08:00"
    assert payload["error"]["metadata"]["retryable"] is False


def test_source_error_event_and_replay_checkpoint_round_trip_unchanged() -> None:
    event_path = FIXTURE_ROOT / "legacy_source_error_event.json"
    checkpoint_path = FIXTURE_ROOT / "legacy_source_error_replay_checkpoint.json"
    event_payload = _load_json(event_path)
    checkpoint_payload = _load_json(checkpoint_path)

    restored_event = StoredEvent.from_dict(event_payload)
    restored_checkpoint = ReplayCheckpoint.from_dict(checkpoint_payload)
    restored_event_payload = restored_event.to_dict()
    restored_checkpoint_payload = restored_checkpoint.to_dict()
    event_error_payload = restored_event_payload["payload"]["error"]
    checkpoint_error_payload = restored_checkpoint_payload["state"]["source_errors"][0]
    event_error = normalize_source_errors([event_error_payload])[0]
    checkpoint_error = normalize_source_errors([checkpoint_error_payload])[0]

    assert restored_event_payload == event_payload
    assert restored_checkpoint_payload == checkpoint_payload
    assert "retryable" not in event_error_payload
    assert event_error_payload["metadata"]["retryable"] == "false"
    assert checkpoint_error_payload == event_error_payload
    assert event_error.to_dict() == checkpoint_error.to_dict()
    assert event_error.request_ref == {"artifact_id": "request-ref"}
    assert event_error.response_ref == {"artifact_id": "response-ref"}
    assert event_error.occurred_at.utcoffset() == timedelta(hours=8)


def test_rollback_read_path_never_rewrites_legacy_source_error_bytes() -> None:
    paths = (
        FIXTURE_ROOT / "source_artifacts" / "index.json",
        ERROR_ARTIFACT_PATH,
        FIXTURE_ROOT / "legacy_source_error_event.json",
        FIXTURE_ROOT / "legacy_source_error_replay_checkpoint.json",
    )
    before_read = {path: path.read_bytes() for path in paths}

    index = _load_json(paths[0])
    error_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_error"
    )
    SignalArtifactRef.from_dict(error_entry["artifact_ref"])
    normalize_source_errors([_load_json(paths[1])["error"]])
    StoredEvent.from_dict(_load_json(paths[2]))
    ReplayCheckpoint.from_dict(_load_json(paths[3]))

    assert {path: path.read_bytes() for path in paths} == before_read


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload
