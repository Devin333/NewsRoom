from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infrastructure.storage.records import (
    ClaimRecord,
    EvidenceItemRecord,
    QualityResultRecord,
    SourceItemRecord,
)


@dataclass(frozen=True)
class WorkflowRunRecord:
    run_id: str
    workflow_id: str
    workflow_version: str
    status: str
    profile: str
    artifact_dir: str | None = None
    manifest_path: str | None = None
    events_path: str | None = None
    error: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status,
            "profile": self.profile,
            "artifact_dir": self.artifact_dir,
            "manifest_path": self.manifest_path,
            "events_path": self.events_path,
            "error": dict(self.error) if isinstance(self.error, dict) else self.error,
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowRunRecord":
        return cls(
            run_id=str(payload["run_id"]),
            workflow_id=str(payload["workflow_id"]),
            workflow_version=str(payload["workflow_version"]),
            status=str(payload["status"]),
            profile=str(payload.get("profile") or ""),
            artifact_dir=payload.get("artifact_dir"),
            manifest_path=payload.get("manifest_path"),
            events_path=payload.get("events_path"),
            error=(
                dict(payload["error"])
                if isinstance(payload.get("error"), dict)
                else payload.get("error")
            ),
            metrics=dict(payload.get("metrics") or {}),
        )


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    run_id: str
    status: str
    title: str | None = None
    report_json: dict[str, Any] | None = None
    report_markdown: str | None = None
    quality_score: float | None = None
    citation_coverage_score: float | None = None
    manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "title": self.title,
            "report_json": dict(self.report_json) if isinstance(self.report_json, dict) else self.report_json,
            "report_markdown": self.report_markdown,
            "quality_score": self.quality_score,
            "citation_coverage_score": self.citation_coverage_score,
            "manifest_path": self.manifest_path,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportRecord":
        return cls(
            report_id=str(payload["report_id"]),
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            title=payload.get("title"),
            report_json=(
                dict(payload["report_json"])
                if isinstance(payload.get("report_json"), dict)
                else payload.get("report_json")
            ),
            report_markdown=payload.get("report_markdown"),
            quality_score=_optional_float(payload.get("quality_score")),
            citation_coverage_score=_optional_float(payload.get("citation_coverage_score")),
            manifest_path=payload.get("manifest_path"),
        )


@dataclass(frozen=True)
class RunPersistenceBatch:
    workflow_run: WorkflowRunRecord
    report: ReportRecord | None = None
    source_items: list[SourceItemRecord] = field(default_factory=list)
    evidence_items: list[EvidenceItemRecord] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    quality_result: QualityResultRecord | None = None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


__all__ = ["ReportRecord", "RunPersistenceBatch", "WorkflowRunRecord"]
