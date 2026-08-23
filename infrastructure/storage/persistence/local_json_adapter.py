from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from infrastructure.storage.local_json import LocalJsonRepository
from infrastructure.storage.records import (
    ClaimRecord,
    EvidenceItemRecord,
    QualityResultRecord,
    ReportDetailRecord,
    ReportSummaryRecord,
    SourceItemRecord,
)
from infrastructure.storage.persistence.records import (
    GraphRunRecord,
    ReportRecord,
    RunPersistenceBatch,
)


class LocalJsonPersistenceAdapter:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)
        self.local_json = LocalJsonRepository(self.artifact_root)

    def latest_report(self) -> ReportDetailRecord:
        return _coerce_report_detail_record(self.local_json.latest_report())

    def get_report(self, report_id: str) -> ReportDetailRecord:
        return _coerce_report_detail_record(self.local_json.get_report(report_id))

    def list_reports(
        self,
        *,
        limit: int = 20,
        graph_id: str | None = None,
        graph_ids: tuple[str, ...] | None = None,
    ) -> list[ReportSummaryRecord]:
        return [
            _coerce_report_summary_record(record)
            for record in self.local_json.list_reports(
                limit=limit,
                graph_id=graph_id,
                graph_ids=graph_ids,
            )
        ]

    def search_reports(self, query: str, *, limit: int = 20) -> list[ReportSummaryRecord]:
        return [
            _coerce_report_summary_record(record)
            for record in self.local_json.search_reports(query, limit=limit)
        ]

    def migrate(self) -> None:
        (self.artifact_root / "_records" / "graph_runs").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "reports").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "source_items").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "evidence_items").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "claims").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "quality_results").mkdir(parents=True, exist_ok=True)

    def save_graph_run(self, record: GraphRunRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "graph_runs"
            / f"{_safe_record_name(record.run_id)}.json",
            record.to_dict(),
        )

    def save_report(self, record: ReportRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root / "_records" / "reports" / f"{_safe_record_name(record.report_id)}.json",
            record.to_dict(),
        )

    def save_source_item(self, record: SourceItemRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "source_items"
            / _safe_record_name(record.run_id)
            / f"{_safe_record_name(record.source_item_id)}.json",
            record.to_dict(),
        )

    def save_evidence_item(self, record: EvidenceItemRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "evidence_items"
            / _safe_record_name(record.run_id)
            / f"{_safe_record_name(record.evidence_id)}.json",
            record.to_dict(),
        )

    def save_claim(self, record: ClaimRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "claims"
            / _safe_record_name(record.run_id)
            / f"{_safe_record_name(record.claim_id)}.json",
            record.to_dict(),
        )

    def save_quality_result(self, record: QualityResultRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "quality_results"
            / _safe_record_name(record.run_id)
            / f"{_safe_record_name(record.quality_result_id)}.json",
            record.to_dict(),
        )

    def save_run_records(self, batch: RunPersistenceBatch) -> None:
        self.save_graph_run(batch.graph_run)
        if batch.report is not None:
            self.save_report(batch.report)
        for source_item in batch.source_items:
            self.save_source_item(source_item)
        for evidence_item in batch.evidence_items:
            self.save_evidence_item(evidence_item)
        for claim in batch.claims:
            self.save_claim(claim)
        if batch.quality_result is not None:
            self.save_quality_result(batch.quality_result)

    def list_source_items(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "source_items" / _safe_run_id(run_id))

    def list_evidence_items(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "evidence_items" / _safe_run_id(run_id))

    def list_claims(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "claims" / _safe_run_id(run_id))

    def list_quality_results(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(
            self.artifact_root / "_records" / "quality_results" / _safe_run_id(run_id)
        )


def _coerce_report_detail_record(record: Any) -> ReportDetailRecord:
    if isinstance(record, ReportDetailRecord):
        return record
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    return ReportDetailRecord(
        report_id=str(payload["report_id"]),
        run_id=str(payload["run_id"]),
        status=str(payload["status"]),
        finished_at=str(payload.get("finished_at") or ""),
        title=payload.get("title"),
        quality_score=_optional_float(payload.get("quality_score")),
        citation_coverage_score=_optional_float(payload.get("citation_coverage_score")),
        manifest_path=payload.get("manifest_path"),
        report_json_path=payload.get("report_json_path"),
        report_markdown_path=payload.get("report_markdown_path"),
        report_json=payload.get("report_json") if isinstance(payload.get("report_json"), dict) else None,
        report_markdown=payload.get("report_markdown"),
    )


def _coerce_report_summary_record(record: Any) -> ReportSummaryRecord:
    if isinstance(record, ReportSummaryRecord):
        return record
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    return ReportSummaryRecord(
        report_id=str(payload["report_id"]),
        run_id=str(payload["run_id"]),
        status=str(payload["status"]),
        finished_at=str(payload.get("finished_at") or ""),
        title=payload.get("title"),
        quality_score=_optional_float(payload.get("quality_score")),
        citation_coverage_score=_optional_float(payload.get("citation_coverage_score")),
        graph_id=payload.get("graph_id"),
        graph_version=payload.get("graph_version"),
        profile=payload.get("profile"),
        manifest_path=payload.get("manifest_path"),
        report_json_path=payload.get("report_json_path"),
        report_markdown_path=payload.get("report_markdown_path"),
    )


def _write_record_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(path)
    except Exception:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
        raise


def _read_record_dir(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for record_path in sorted(path.glob("*.json")):
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _safe_record_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "record"


def _safe_run_id(value: str) -> str:
    if not value:
        raise ValueError("run_id is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid run_id: {value}")
    return _safe_record_name(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


__all__ = ["LocalJsonPersistenceAdapter"]
