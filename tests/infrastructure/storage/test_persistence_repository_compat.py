from __future__ import annotations

import infrastructure.storage.persistence as persistence
import infrastructure.storage.repository as legacy_repository


def test_old_repository_path_exports_new_persistence_symbols() -> None:
    assert legacy_repository.PersistenceRepository is persistence.PersistenceRepository
    assert legacy_repository.WorkflowRunRecord is persistence.WorkflowRunRecord
    assert legacy_repository.ReportRecord is persistence.ReportRecord
    assert legacy_repository.RunPersistenceBatch is persistence.RunPersistenceBatch
    assert legacy_repository.RunPersistenceInput is persistence.RunPersistenceInput
    assert legacy_repository.LocalJsonPersistenceAdapter is persistence.LocalJsonPersistenceAdapter
    assert (
        legacy_repository.LocalJsonPersistenceAdapter.__module__
        == "infrastructure.storage.persistence.local_json_adapter"
    )
    assert legacy_repository.repository_from_env is persistence.repository_from_env
    assert legacy_repository.persist_run_input is persistence.persist_run_input
    assert legacy_repository.persist_run_result is persistence.persist_run_result
    assert (
        legacy_repository.run_persistence_input_from_output
        is persistence.run_persistence_input_from_output
    )
    assert (
        legacy_repository.run_persistence_input_from_result
        is persistence.run_persistence_input_from_result
    )
    assert (
        legacy_repository.run_persistence_batch_from_input
        is persistence.run_persistence_batch_from_input
    )
