from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from framework import RunResult
from infrastructure.storage.records import (
    ClaimRecord,
    EvidenceItemRecord,
    QualityResultRecord,
    ReportDetailRecord,
    ReportSummaryRecord,
    SourceItemRecord,
)
from infrastructure.storage.persistence.local_json_adapter import LocalJsonPersistenceAdapter
from infrastructure.storage.persistence.record_builders import (
    claim_records_from_result,
    claim_records_from_input,
    evidence_item_records_from_result,
    evidence_item_records_from_input,
    quality_result_record_from_result,
    quality_result_record_from_input,
    report_record_from_result,
    report_record_from_input,
    run_persistence_batch_from_result,
    run_persistence_batch_from_input,
    source_item_records_from_result,
    source_item_records_from_input,
    workflow_run_record_from_result,
    workflow_run_record_from_input,
)
from infrastructure.storage.persistence.record_inputs import (
    RunPersistenceInput,
    run_persistence_input_from_output,
    run_persistence_input_from_result,
)
from infrastructure.storage.persistence.records import (
    ReportRecord,
    RunPersistenceBatch,
    WorkflowRunRecord,
)


class PersistenceRepository(Protocol):
    def migrate(self) -> None: ...

    def latest_report(self) -> ReportDetailRecord: ...

    def get_report(self, report_id: str) -> ReportDetailRecord: ...

    def list_reports(
        self,
        *,
        limit: int = 20,
        workflow_id: str | None = None,
        workflow_ids: tuple[str, ...] | None = None,
    ) -> list[ReportSummaryRecord]: ...

    def search_reports(self, query: str, *, limit: int = 20) -> list[ReportSummaryRecord]: ...

    def save_workflow_run(self, record: WorkflowRunRecord) -> None: ...

    def save_report(self, record: ReportRecord) -> None: ...

    def save_source_item(self, record: SourceItemRecord) -> None: ...

    def save_evidence_item(self, record: EvidenceItemRecord) -> None: ...

    def save_claim(self, record: ClaimRecord) -> None: ...

    def save_quality_result(self, record: QualityResultRecord) -> None: ...

    def save_run_records(self, batch: RunPersistenceBatch) -> None: ...

    def list_source_items(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_evidence_items(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_claims(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_quality_results(self, run_id: str) -> list[dict[str, Any]]: ...


def repository_from_env(
    *,
    artifact_root: str | Path = ".newsroom/runs",
    env: dict[str, str] | None = None,
) -> PersistenceRepository:
    values = env if env is not None else os.environ
    dsn = values.get("NEWS_DATABASE_DSN")
    if dsn:
        from infrastructure.storage.postgres.repository import PostgresRepository

        return PostgresRepository(dsn)
    return LocalJsonPersistenceAdapter(artifact_root)


def persist_run_result(
    repository: PersistenceRepository,
    result: RunResult,
    *,
    profile: str,
    migrate: bool = True,
) -> None:
    if migrate:
        repository.migrate()
    input_model = run_persistence_input_from_result(result, profile=profile)
    persist_run_input(repository, input_model, migrate=False)


def persist_run_input(
    repository: PersistenceRepository,
    input_model: RunPersistenceInput,
    *,
    migrate: bool = True,
) -> None:
    if migrate:
        repository.migrate()
    batch = run_persistence_batch_from_input(input_model)
    save_batch = getattr(repository, "save_run_records", None)
    if save_batch is not None:
        save_batch(batch)
        return

    repository.save_workflow_run(batch.workflow_run)
    if batch.report:
        repository.save_report(batch.report)
    for source_item in batch.source_items:
        _optional_save(repository, "save_source_item", source_item)
    for evidence_item in batch.evidence_items:
        _optional_save(repository, "save_evidence_item", evidence_item)
    for claim in batch.claims:
        _optional_save(repository, "save_claim", claim)
    if batch.quality_result:
        _optional_save(repository, "save_quality_result", batch.quality_result)


def _optional_save(repository: Any, method_name: str, record: Any) -> None:
    method = getattr(repository, method_name, None)
    if method is not None:
        method(record)
