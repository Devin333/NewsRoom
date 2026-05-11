from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ReportNotFoundError(FileNotFoundError):
    """Raised when no local report artifact can be found."""


@dataclass(frozen=True)
class LatestReportRecord:
    report_id: str
    run_id: str
    status: str
    finished_at: str
    title: str | None
    quality_score: float | None
    manifest_path: Path
    report_json_path: Path | None
    report_markdown_path: Path | None
    report_json: dict[str, Any] | None
    report_markdown: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "finished_at": self.finished_at,
            "title": self.title,
            "quality_score": self.quality_score,
            "manifest_path": str(self.manifest_path),
            "report_json_path": str(self.report_json_path) if self.report_json_path else None,
            "report_markdown_path": (
                str(self.report_markdown_path) if self.report_markdown_path else None
            ),
            "report_json": self.report_json,
            "report_markdown": self.report_markdown,
        }


@dataclass(frozen=True)
class ReportSearchRecord:
    report_id: str
    run_id: str
    status: str
    finished_at: str
    title: str | None
    quality_score: float | None
    manifest_path: Path
    report_json_path: Path | None
    report_markdown_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "finished_at": self.finished_at,
            "title": self.title,
            "quality_score": self.quality_score,
            "manifest_path": str(self.manifest_path),
            "report_json_path": str(self.report_json_path) if self.report_json_path else None,
            "report_markdown_path": (
                str(self.report_markdown_path) if self.report_markdown_path else None
            ),
        }


class LocalJsonRepository:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)

    def latest_report(self) -> LatestReportRecord:
        candidates = []
        for manifest_path in self.artifact_root.glob("*/manifest.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifacts = manifest.get("artifacts", {})
            if manifest.get("status") != "succeeded":
                continue
            if "report_json" not in artifacts and "report_markdown" not in artifacts:
                continue
            candidates.append((manifest.get("finished_at") or "", manifest_path, manifest))

        if not candidates:
            raise ReportNotFoundError(f"no local report found under {self.artifact_root}")

        _, manifest_path, manifest = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        return _detail_from_manifest(manifest_path, manifest)

    def get_report(self, report_id: str) -> LatestReportRecord:
        run_id, report_status = _parse_report_id(report_id)
        if report_status != "final":
            raise ReportNotFoundError(f"report not found: {report_id}")
        manifest_path = self.artifact_root / run_id / "manifest.json"
        if not manifest_path.exists():
            raise ReportNotFoundError(f"report not found: {report_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "succeeded":
            raise ReportNotFoundError(f"report not found: {report_id}")
        artifacts = manifest.get("artifacts", {})
        if "report_json" not in artifacts and "report_markdown" not in artifacts:
            raise ReportNotFoundError(f"report not found: {report_id}")
        return _detail_from_manifest(manifest_path, manifest)

    def search_reports(self, query: str, *, limit: int = 20) -> list[ReportSearchRecord]:
        normalized_query = query.lower()
        matches: list[ReportSearchRecord] = []
        for manifest_path in self.artifact_root.glob("*/manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("status") != "succeeded":
                continue
            artifacts = manifest.get("artifacts", {})
            if "report_json" not in artifacts and "report_markdown" not in artifacts:
                continue
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
            matches.append(
                ReportSearchRecord(
                    report_id=f"{manifest['run_id']}:final",
                    run_id=str(manifest["run_id"]),
                    status=str(manifest["status"]),
                    finished_at=manifest.get("finished_at") or "",
                    title=(report_json or {}).get("title"),
                    quality_score=manifest.get("quality_score"),
                    manifest_path=manifest_path,
                    report_json_path=report_json_path,
                    report_markdown_path=report_markdown_path,
                )
            )
        matches.sort(key=lambda item: item.finished_at, reverse=True)
        return matches[:limit]


def _artifact_path(run_dir: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    path = run_dir / relative
    return path if path.exists() else None


def _detail_from_manifest(manifest_path: Path, manifest: dict[str, Any]) -> LatestReportRecord:
    run_dir = manifest_path.parent
    artifacts = manifest.get("artifacts", {})
    report_json_path = _artifact_path(run_dir, artifacts.get("report_json"))
    report_markdown_path = _artifact_path(run_dir, artifacts.get("report_markdown"))
    report_json = _read_optional_json(report_json_path)
    report_markdown = _read_optional_text(report_markdown_path)
    run_id = str(manifest["run_id"])
    return LatestReportRecord(
        report_id=f"{run_id}:final",
        run_id=run_id,
        status=str(manifest["status"]),
        finished_at=manifest.get("finished_at") or "",
        title=(report_json or {}).get("title"),
        quality_score=manifest.get("quality_score"),
        manifest_path=manifest_path,
        report_json_path=report_json_path,
        report_markdown_path=report_markdown_path,
        report_json=report_json,
        report_markdown=report_markdown,
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
