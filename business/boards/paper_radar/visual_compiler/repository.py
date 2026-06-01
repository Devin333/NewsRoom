from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from business.boards.paper_radar.visual_compiler.models import (
    PaperAssetManifest,
    PaperCompileInfo,
    PaperCompileStatus,
    PaperCompileStatusRecord,
    PaperDocument,
    PaperReviewReport,
    PaperSourceComparisonReport,
)


PAPERS_VISUAL_COMPILER_DIR_ENV = "NEWSROOM_PAPERS_VISUAL_COMPILER_DIR"


class PaperVisualCompilerRepository:
    def __init__(self, root_dir: str | Path | None = None) -> None:
        self.root_dir = _runtime_dir(root_dir)

    def paper_dir(self, paper_id: str) -> Path:
        return self.root_dir / _safe_file_key(paper_id)

    def draft_dir(self, paper_id: str) -> Path:
        return self.paper_dir(paper_id) / "draft"

    def source_pdf_path(self, paper_id: str, file_name: str = "source.pdf") -> Path:
        return self.paper_dir(paper_id) / file_name

    def asset_path(self, paper_id: str, file_name: str) -> Path:
        return self.paper_dir(paper_id) / file_name

    def read_document(self, paper_id: str) -> PaperDocument | None:
        return PaperDocument.from_dict(_read_json_object(self.paper_dir(paper_id) / "document.json"))

    def read_manifest(self, paper_id: str) -> PaperAssetManifest | None:
        return PaperAssetManifest.from_dict(_read_json_object(self.paper_dir(paper_id) / "manifest.json"))

    def read_compile_info(self, paper_id: str) -> PaperCompileInfo | None:
        return PaperCompileInfo.from_dict(_read_json_object(self.paper_dir(paper_id) / "compile-info.json"))

    def read_review_report(self, paper_id: str) -> PaperReviewReport | None:
        return PaperReviewReport.from_dict(_read_json_object(self.paper_dir(paper_id) / "review-report.json"))

    def read_source_comparison_report(self, paper_id: str) -> PaperSourceComparisonReport | None:
        return PaperSourceComparisonReport.from_dict(_read_json_object(self.paper_dir(paper_id) / "source-comparison-report.json"))

    def read_status(self, paper_id: str) -> PaperCompileStatusRecord | None:
        return PaperCompileStatusRecord.from_dict(_read_json_object(self.paper_dir(paper_id) / "status.json"))

    def read_published_document(self, paper_id: str) -> tuple[PaperDocument, PaperAssetManifest] | None:
        status = self.read_status(paper_id)
        if status is None or status.status != "compiled":
            return None
        document = self.read_document(paper_id)
        manifest = self.read_manifest(paper_id)
        if document is None or manifest is None:
            return None
        if document.status != "compiled":
            return None
        return document, manifest

    def resolve_asset(self, paper_id: str, asset_id: str) -> tuple[Path, str] | None:
        manifest = self.read_manifest(paper_id)
        if manifest is None:
            return None
        for asset in manifest.assets:
            if asset.assetId == asset_id:
                path = self.asset_path(paper_id, asset.fileName).resolve()
                root = self.paper_dir(paper_id).resolve()
                if root not in path.parents and path != root:
                    return None
                return path, asset.mimeType
        return None

    def write_status(
        self,
        paper_id: str,
        *,
        status: PaperCompileStatus,
        updated_at: str,
        diagnostics: Sequence[Mapping[str, Any]] = (),
        compile_info: PaperCompileInfo | None = None,
        review_report: PaperReviewReport | None = None,
        gate_report: Mapping[str, Any] | None = None,
        source_comparison_report: PaperSourceComparisonReport | None = None,
    ) -> PaperCompileStatusRecord:
        record = PaperCompileStatusRecord(
            paperId=paper_id,
            status=status,
            updatedAt=updated_at,
            diagnostics=tuple(dict(item) for item in diagnostics),
            compileInfo=compile_info,
            reviewReport=review_report,
            gateReport=dict(gate_report) if isinstance(gate_report, Mapping) else None,
            sourceComparisonReport=source_comparison_report,
        )
        _write_json_object(self.paper_dir(paper_id) / "status.json", record.to_dict())
        return record

    def write_artifacts(
        self,
        *,
        document: PaperDocument,
        manifest: PaperAssetManifest,
        compile_info: PaperCompileInfo,
        review_report: PaperReviewReport | None,
        gate_report: Mapping[str, Any] | None,
        source_comparison_report: PaperSourceComparisonReport | None = None,
        status: PaperCompileStatus,
        updated_at: str,
        diagnostics: Sequence[Mapping[str, Any]] = (),
    ) -> PaperCompileStatusRecord:
        paper_dir = self.paper_dir(document.paperId)
        _write_json_object(paper_dir / "document.json", document.to_dict())
        _write_json_object(paper_dir / "manifest.json", manifest.to_dict())
        _write_json_object(paper_dir / "compile-info.json", compile_info.to_dict())
        if review_report is not None:
            _write_json_object(paper_dir / "review-report.json", review_report.to_dict())
        if gate_report is not None:
            _write_json_object(paper_dir / "gate-report.json", dict(gate_report))
        if source_comparison_report is not None:
            _write_json_object(paper_dir / "source-comparison-report.json", source_comparison_report.to_dict())
        return self.write_status(
            document.paperId,
            status=status,
            updated_at=updated_at,
            diagnostics=diagnostics,
            compile_info=compile_info,
            review_report=review_report,
            gate_report=gate_report,
            source_comparison_report=source_comparison_report,
        )


def _runtime_dir(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_VISUAL_COMPILER_DIR_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers" / "visual-compiler"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _read_json_object(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _write_json_object(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _safe_file_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    if normalized:
        return normalized[:140]
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
