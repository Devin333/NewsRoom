from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ReportNotFoundError(FileNotFoundError):
    """Raised when no local report artifact can be found."""


@dataclass(frozen=True)
class LatestReportRecord:
    run_id: str
    status: str
    finished_at: str
    manifest_path: Path
    report_json_path: Path | None
    report_markdown_path: Path | None
    report_json: dict[str, Any] | None
    report_markdown: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "finished_at": self.finished_at,
            "manifest_path": str(self.manifest_path),
            "report_json_path": str(self.report_json_path) if self.report_json_path else None,
            "report_markdown_path": (
                str(self.report_markdown_path) if self.report_markdown_path else None
            ),
            "report_json": self.report_json,
            "report_markdown": self.report_markdown,
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
        run_dir = manifest_path.parent
        artifacts = manifest.get("artifacts", {})
        report_json_path = _artifact_path(run_dir, artifacts.get("report_json"))
        report_markdown_path = _artifact_path(run_dir, artifacts.get("report_markdown"))
        report_json = (
            json.loads(report_json_path.read_text(encoding="utf-8")) if report_json_path else None
        )
        report_markdown = (
            report_markdown_path.read_text(encoding="utf-8") if report_markdown_path else None
        )
        return LatestReportRecord(
            run_id=manifest["run_id"],
            status=manifest["status"],
            finished_at=manifest.get("finished_at") or "",
            manifest_path=manifest_path,
            report_json_path=report_json_path,
            report_markdown_path=report_markdown_path,
            report_json=report_json,
            report_markdown=report_markdown,
        )


def _artifact_path(run_dir: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    path = run_dir / relative
    return path if path.exists() else None
