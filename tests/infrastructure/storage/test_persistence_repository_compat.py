from __future__ import annotations

from pathlib import Path

import infrastructure.storage.persistence as persistence


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_persistence_package_exports_repository_symbols() -> None:
    assert persistence.PersistenceRepository is not None
    assert persistence.GraphRunRecord is not None
    assert not hasattr(persistence, "WorkflowRunRecord")
    assert persistence.ReportRecord is not None
    assert persistence.RunPersistenceBatch is not None
    assert persistence.RunPersistenceInput is not None
    assert persistence.LocalJsonPersistenceAdapter.__module__ == (
        "infrastructure.storage.persistence.local_json_adapter"
    )
    assert persistence.repository_from_env is not None
    assert persistence.persist_run_input is not None
    assert persistence.persist_run_result is not None
    assert persistence.run_persistence_input_from_output is not None
    assert persistence.run_persistence_input_from_result is not None
    assert persistence.run_persistence_batch_from_input is not None


def test_legacy_storage_repository_module_is_removed() -> None:
    assert not (PROJECT_ROOT / "infrastructure" / "storage" / "repository.py").exists()
