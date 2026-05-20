from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infrastructure.storage.records import ReportDetailRecord, ReportSummaryRecord


class ReportNotFoundError(FileNotFoundError):
    """Raised when no local report artifact can be found."""


FINAL_REPORT_STATUS = "final"
BLOCKED_REPORT_STATUS = "blocked"
REPORT_ARTIFACT_KEYS = ("report_json", "blocked_report", "report_markdown")


class LocalJsonRepository:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)

    def latest_report(self) -> ReportDetailRecord:
        candidates = []
        for manifest_path in self.artifact_root.glob("*/manifest.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifacts = manifest.get("artifacts", {})
            if manifest.get("status") != "succeeded":
                continue
            if not _has_report_artifact(artifacts):
                continue
            candidates.append((manifest.get("finished_at") or "", manifest_path, manifest))

        if not candidates:
            raise ReportNotFoundError(f"no local report found under {self.artifact_root}")

        _, manifest_path, manifest = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        return _detail_from_manifest(manifest_path, manifest)

    def get_report(self, report_id: str) -> ReportDetailRecord:
        run_id, report_status = _parse_report_id(report_id)
        if report_status not in {FINAL_REPORT_STATUS, BLOCKED_REPORT_STATUS}:
            raise ReportNotFoundError(f"report not found: {report_id}")
        manifest_path = self.artifact_root / run_id / "manifest.json"
        if not manifest_path.exists():
            raise ReportNotFoundError(f"report not found: {report_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "succeeded":
            raise ReportNotFoundError(f"report not found: {report_id}")
        artifacts = manifest.get("artifacts", {})
        if not _has_report_artifact(artifacts):
            raise ReportNotFoundError(f"report not found: {report_id}")
        if _report_status_from_artifacts(artifacts) != report_status:
            raise ReportNotFoundError(f"report not found: {report_id}")
        return _detail_from_manifest(manifest_path, manifest)

    def list_reports(
        self,
        *,
        limit: int = 20,
        workflow_id: str | None = None,
        workflow_ids: tuple[str, ...] | None = None,
    ) -> list[ReportSummaryRecord]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        records: list[ReportSearchRecord] = []
        for manifest_path, manifest in self._iter_report_manifests(
            workflow_id=workflow_id,
            workflow_ids=workflow_ids,
        ):
            records.append(_summary_from_manifest(manifest_path, manifest))
        records.sort(key=lambda item: item.finished_at, reverse=True)
        return records[:limit]

    def search_reports(self, query: str, *, limit: int = 20) -> list[ReportSummaryRecord]:
        normalized_query = query.lower()
        matches: list[ReportSearchRecord] = []
        for manifest_path, manifest in self._iter_report_manifests():
            artifacts = manifest.get("artifacts", {})
            run_dir = manifest_path.parent
            report_json_path = _artifact_path(run_dir, artifacts.get("report_json"))
            report_markdown_path = _artifact_path(run_dir, artifacts.get("report_markdown"))
            report_json = _read_optional_json(report_json_path)
            report_markdown = _read_optional_text(report_markdown_path)
            haystack = " ".join(
                [
                    str((report_json or {}).get("title") or ""),
                    json.dumps(report_json or {}, ensure_ascii=False, sort_keys=True),
                    report_markdown or "",
                ]
            ).lower()
            if normalized_query not in haystack:
                continue
            matches.append(_summary_from_manifest(manifest_path, manifest))
        matches.sort(key=lambda item: item.finished_at, reverse=True)
        return matches[:limit]

    def _iter_report_manifests(
        self,
        *,
        workflow_id: str | None = None,
        workflow_ids: tuple[str, ...] | None = None,
    ) -> list[tuple[Path, dict[str, Any]]]:
        manifests: list[tuple[Path, dict[str, Any]]] = []
        for manifest_path in self.artifact_root.glob("*/manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("status") != "succeeded":
                continue
            if workflow_id is not None and manifest.get("workflow_id") != workflow_id:
                continue
            if workflow_ids is not None and manifest.get("workflow_id") not in set(workflow_ids):
                continue
            artifacts = manifest.get("artifacts", {})
            if not _has_report_artifact(artifacts):
                continue
            manifests.append((manifest_path, manifest))
        return manifests


def _artifact_path(run_dir: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    path = run_dir / relative
    return path if path.exists() else None


def _has_report_artifact(artifacts: dict[str, Any]) -> bool:
    return any(key in artifacts for key in REPORT_ARTIFACT_KEYS)


def _report_status_from_artifacts(artifacts: dict[str, Any]) -> str:
    if "blocked_report" in artifacts and "report_json" not in artifacts:
        return BLOCKED_REPORT_STATUS
    return FINAL_REPORT_STATUS


def _detail_from_manifest(manifest_path: Path, manifest: dict[str, Any]) -> ReportDetailRecord:
    run_dir = manifest_path.parent
    artifacts = manifest.get("artifacts", {})
    report_status = _report_status_from_artifacts(artifacts)
    report_json_path = _artifact_path(run_dir, artifacts.get("report_json") or artifacts.get("blocked_report"))
    report_markdown_path = _artifact_path(run_dir, artifacts.get("report_markdown"))
    report_json = _read_optional_json(report_json_path)
    report_markdown = _read_optional_text(report_markdown_path)
    run_id = str(manifest["run_id"])
    return ReportDetailRecord(
        report_id=f"{run_id}:{report_status}",
        run_id=run_id,
        status=report_status,
        finished_at=manifest.get("finished_at") or "",
        title=(report_json or {}).get("title"),
        quality_score=manifest.get("quality_score"),
        manifest_path=manifest_path,
        report_json_path=report_json_path,
        report_markdown_path=report_markdown_path,
        report_json=report_json,
        report_markdown=report_markdown,
    )


def _summary_from_manifest(manifest_path: Path, manifest: dict[str, Any]) -> ReportSummaryRecord:
    run_dir = manifest_path.parent
    artifacts = manifest.get("artifacts", {})
    report_status = _report_status_from_artifacts(artifacts)
    report_json_path = _artifact_path(run_dir, artifacts.get("report_json") or artifacts.get("blocked_report"))
    report_markdown_path = _artifact_path(run_dir, artifacts.get("report_markdown"))
    report_json = _read_optional_json(report_json_path)
    run_id = str(manifest["run_id"])
    return ReportSummaryRecord(
        report_id=f"{run_id}:{report_status}",
        run_id=run_id,
        status=report_status,
        finished_at=manifest.get("finished_at") or "",
        title=(report_json or {}).get("title"),
        quality_score=manifest.get("quality_score"),
        workflow_id=manifest.get("workflow_id"),
        profile=manifest.get("profile"),
        manifest_path=manifest_path,
        report_json_path=report_json_path,
        report_markdown_path=report_markdown_path,
    )


def _parse_report_id(report_id: str) -> tuple[str, str]:
    if ":" not in report_id:
        raise ValueError(f"invalid report id: {report_id}")
    run_id, report_status = report_id.split(":", 1)
    relative = Path(run_id)
    if not run_id or relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid report id: {report_id}")
    if not report_status:
        raise ValueError(f"invalid report id: {report_id}")
    return run_id, report_status


def _read_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _read_optional_text(path: Path | None) -> str | None:
    if path is None:
        return None
    return path.read_text(encoding="utf-8")
