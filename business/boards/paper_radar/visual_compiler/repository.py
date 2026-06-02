from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

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
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class PaperVisualCompilerRepository:
    def __init__(self, root_dir: str | Path | None = None) -> None:
        self.root_dir = _runtime_dir(root_dir)

    def paper_dir(self, paper_id: str) -> Path:
        return self.root_dir / _safe_file_key(paper_id)

    def paper_dirs(self, paper_id: str) -> tuple[Path, ...]:
        return _candidate_paper_dirs(self.root_dir, paper_id)

    def draft_dir(self, paper_id: str) -> Path:
        return self.paper_dir(paper_id) / "draft"

    def source_pdf_path(self, paper_id: str, file_name: str = "source.pdf") -> Path:
        return self.paper_dir(paper_id) / file_name

    def existing_source_pdf_path(self, paper_id: str, file_name: str = "source.pdf") -> Path | None:
        for paper_dir in self.paper_dirs(paper_id):
            path = (paper_dir / file_name).resolve()
            root = paper_dir.resolve()
            if root not in path.parents and path != root:
                continue
            if path.exists() and path.is_file():
                return path
        return None

    def asset_path(self, paper_id: str, file_name: str) -> Path:
        return self.paper_dir(paper_id) / file_name

    def read_document(self, paper_id: str) -> PaperDocument | None:
        return PaperDocument.from_dict(self._read_artifact(paper_id, "document.json"))

    def read_manifest(self, paper_id: str) -> PaperAssetManifest | None:
        manifest, _paper_dir = self._read_manifest_with_dir(paper_id)
        return manifest

    def read_compile_info(self, paper_id: str) -> PaperCompileInfo | None:
        return PaperCompileInfo.from_dict(self._read_artifact(paper_id, "compile-info.json"))

    def read_review_report(self, paper_id: str) -> PaperReviewReport | None:
        return PaperReviewReport.from_dict(self._read_artifact(paper_id, "review-report.json"))

    def read_source_comparison_report(self, paper_id: str) -> PaperSourceComparisonReport | None:
        return PaperSourceComparisonReport.from_dict(self._read_artifact(paper_id, "source-comparison-report.json"))

    def read_status(self, paper_id: str) -> PaperCompileStatusRecord | None:
        return PaperCompileStatusRecord.from_dict(self._read_artifact(paper_id, "status.json"))

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
        manifest, paper_dir = self._read_manifest_with_dir(paper_id)
        if manifest is None:
            return None
        for asset in manifest.assets:
            if asset.assetId == asset_id:
                path = (paper_dir / asset.fileName).resolve()
                root = paper_dir.resolve()
                if root not in path.parents and path != root:
                    return None
                return path, asset.mimeType
        return None

    def _read_artifact(self, paper_id: str, file_name: str) -> Mapping[str, Any] | None:
        return _read_first_json_object(tuple(paper_dir / file_name for paper_dir in self.paper_dirs(paper_id)))

    def _read_manifest_with_dir(self, paper_id: str) -> tuple[PaperAssetManifest | None, Path]:
        primary = self.paper_dir(paper_id)
        for paper_dir in self.paper_dirs(paper_id):
            manifest = PaperAssetManifest.from_dict(_read_json_object(paper_dir / "manifest.json"))
            if manifest is not None:
                return manifest, paper_dir
        return None, primary

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
    with _locked_path(path) as resolved:
        if not resolved.exists():
            return None
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return payload if isinstance(payload, Mapping) else None


def _read_first_json_object(paths: Sequence[Path]) -> Mapping[str, Any] | None:
    for path in paths:
        payload = _read_json_object(path)
        if payload is not None:
            return payload
    return None


def _write_json_object(path: Path, payload: Mapping[str, Any]) -> None:
    with _locked_path(path) as resolved:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        temp_path = resolved.with_name(f"{resolved.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp")
        temp_path.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(resolved)


def _safe_file_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    if not normalized:
        return digest
    prefix = normalized[: max(1, 140 - len(digest) - 1)].rstrip(".-")
    return f"{prefix}-{digest}" if prefix else digest


def _candidate_paper_dirs(root_dir: Path, paper_id: str) -> tuple[Path, ...]:
    primary = root_dir / _safe_file_key(paper_id)
    legacy = root_dir / _legacy_file_key(paper_id)
    return (primary,) if legacy == primary else (primary, legacy)


def _legacy_file_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    if normalized:
        return normalized[:140]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


@contextmanager
def _locked_path(path: Path) -> Iterator[Path]:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    thread_lock = _path_lock(resolved)
    with thread_lock:
        lock_path = resolved.with_name(f"{resolved.name}.lock")
        with lock_path.open("a+b") as handle:
            _lock_handle(handle)
            try:
                yield resolved
            finally:
                _unlock_handle(handle)


def _path_lock(path: Path) -> threading.RLock:
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[path] = lock
        return lock


def _lock_handle(handle: Any) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_handle(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
