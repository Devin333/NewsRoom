from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from business.boards.paper_radar.visual_compiler import (
    ArxivSourcePaperCompiler,
    PaperAssetGate,
    PaperAssetManifest,
    PaperCompileInfo,
    PaperCompileStatusRecord,
    PaperCompiler,
    PaperDocument,
    PaperLayoutProviderConfigurationError,
    PaperReviewReport,
    PaperSourceComparer,
    PaperSourceComparisonReport,
    PaperVisualCompilerRepository,
    PyMuPDFPaperCompiler,
    SourceFirstPaperCompiler,
    build_model_layout_provider_from_env,
)
from business.boards.paper_radar.source_comparison_memory import PaperSourceComparisonMemoryService
from business.boards.paper_radar.visual_compiler.models import (
    PAPER_DOCUMENT_SCHEMA_VERSION,
    PAPER_TABLE_MODEL_STYLE_SCHEMA_VERSION,
)
from business.boards.paper_radar.visual_compiler.base import PaperCompilerError
from business.boards.paper_radar.visual_compiler.reviewer import LLMPaperDocumentReviewer, PaperDocumentReviewer
from interfaces.services.paper_ingest_service import DEFAULT_PDF_MAX_BYTES, PAPERS_PDF_MAX_BYTES_ENV
from interfaces.services.paper_reader_memory_repository import paper_reader_memory_repository_from_env
from interfaces.services.paper_service import PaperNotFoundError, PapersApplicationService


PAPER_VISUAL_COMPILE_TASK_TYPE = "papers.visual_compile"
PAPER_VISUAL_COMPILE_BACKFILL_TASK_TYPE = "papers.visual_compile_backfill"
DEFAULT_READER_PDF_MAX_BYTES = 160_000_000
PDF_FETCH_RETRY_ATTEMPTS = 3
PDF_FETCH_RETRY_DELAY_SECONDS = 1.0
TERMINAL_PDF_FETCH_CODES = {"source_pdf_not_found", "source_pdf_unavailable", "source_pdf_too_large"}


class PaperVisualCompileError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        diagnostics: Sequence[Mapping[str, Any]] = (),
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(dict(item) for item in diagnostics)
        self.retryable = retryable


@dataclass(frozen=True)
class PaperVisualCompileResult:
    paper_id: str
    status: str
    document: PaperDocument | None
    manifest: PaperAssetManifest | None
    compile_info: PaperCompileInfo | None
    review_report: PaperReviewReport | None
    source_comparison_report: PaperSourceComparisonReport | None
    gate_report: Mapping[str, Any] | None
    diagnostics: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "paperId": self.paper_id,
            "status": self.status,
            "document": self.document.to_dict() if self.document is not None and self.status == "compiled" else None,
            "manifest": self.manifest.to_dict() if self.manifest is not None and self.status == "compiled" else None,
            "compileInfo": self.compile_info.to_dict() if self.compile_info is not None else None,
            "reviewReport": self.review_report.to_dict() if self.review_report is not None else None,
            "sourceComparisonReport": self.source_comparison_report.to_dict() if self.source_comparison_report is not None else None,
            "gateReport": dict(self.gate_report) if self.gate_report is not None else None,
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


@dataclass(frozen=True)
class PaperVisualCompileBackfillCandidate:
    paper_id: str
    slug: str
    title: str
    current_status: str
    reason: str
    source_pdf_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "paperId": self.paper_id,
            "slug": self.slug,
            "title": self.title,
            "currentStatus": self.current_status,
            "reason": self.reason,
            "sourcePdfUrl": self.source_pdf_url,
        }


@dataclass(frozen=True)
class PaperVisualCompileBackfillPlan:
    run_id: str | None
    force: bool
    limit: int | None
    scanned_count: int
    candidate_count: int
    skipped_count: int
    skipped_no_pdf_count: int
    candidates: tuple[PaperVisualCompileBackfillCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "force": self.force,
            "limit": self.limit,
            "scannedCount": self.scanned_count,
            "candidateCount": self.candidate_count,
            "skippedCount": self.skipped_count,
            "skippedNoPdfCount": self.skipped_no_pdf_count,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class PaperVisualCompilerApplicationService:
    def __init__(
        self,
        *,
        papers_service: PapersApplicationService | None = None,
        repository: PaperVisualCompilerRepository | None = None,
        compiler: PaperCompiler | None = None,
        asset_gate: PaperAssetGate | None = None,
        source_comparer: PaperSourceComparer | None = None,
        reviewer: PaperDocumentReviewer | None = None,
        source_memory_service: PaperSourceComparisonMemoryService | None = None,
        pdf_fetcher: Callable[[str, int], bytes] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.papers_service = papers_service or PapersApplicationService()
        self.repository = repository or PaperVisualCompilerRepository()
        self.compiler = compiler or _default_paper_compiler()
        self.asset_gate = asset_gate or PaperAssetGate()
        self.source_comparer = source_comparer or PaperSourceComparer()
        self.reviewer = reviewer or LLMPaperDocumentReviewer(clock=clock)
        self.source_memory_service = source_memory_service or PaperSourceComparisonMemoryService(
            repository=paper_reader_memory_repository_from_env()
        )
        self.pdf_fetcher = pdf_fetcher or _fetch_pdf_bytes
        self.clock = clock or (lambda: datetime.now(UTC))

    def get_document_payload(self, paper_id: str) -> Mapping[str, Any]:
        paper = self._paper_dict(paper_id)
        resolved_id = paper["id"]
        status = self.get_compile_status(resolved_id)
        published = self.repository.read_published_document(resolved_id)
        if published is None:
            return {
                "paper": paper,
                "status": status.to_dict(),
                "document": None,
                "manifest": None,
                "ai": _ai_panel_payload(paper, status),
            }
        document, manifest = published
        return {
            "paper": paper,
            "status": status.to_dict(),
            "document": document.to_dict(),
            "manifest": manifest.to_dict(),
            "ai": _ai_panel_payload(paper, status),
        }

    def get_compile_status(self, paper_id: str) -> PaperCompileStatusRecord:
        paper = self._paper_dict(paper_id)
        resolved_id = paper["id"]
        status = self.repository.read_status(resolved_id)
        if status is not None:
            return status
        return PaperCompileStatusRecord(
            paperId=resolved_id,
            status="queued",
            updatedAt=_iso(self.clock()),
            diagnostics=(
                {
                    "severity": "info",
                    "code": "not_compiled",
                    "message": "paper has not been visually compiled yet",
                },
            ),
        )

    def compile_paper(self, paper_id: str, *, force: bool = False, run_id: str | None = None) -> PaperVisualCompileResult:
        paper = self._paper_dict(paper_id)
        resolved_id = paper["id"]
        existing = self.repository.read_status(resolved_id)
        if existing is not None and existing.status == "compiled" and not force:
            refresh_reason = self._backfill_reason(resolved_id, force=False)
            if refresh_reason is None:
                published = self.repository.read_published_document(resolved_id)
                document = published[0] if published else None
                manifest = published[1] if published else None
                return PaperVisualCompileResult(
                    paper_id=resolved_id,
                    status="compiled",
                    document=document,
                    manifest=manifest,
                    compile_info=existing.compileInfo,
                    review_report=existing.reviewReport,
                    source_comparison_report=existing.sourceComparisonReport,
                    gate_report=existing.gateReport,
                    diagnostics=existing.diagnostics,
                )

        started = self.clock()
        self.repository.write_status(
            resolved_id,
            status="compiling",
            updated_at=_iso(started),
            diagnostics=(
                {
                    "severity": "info",
                    "code": "compile_started",
                    "message": "paper visual compilation started",
                    "runId": run_id,
                },
            ),
        )
        source_pdf_url = _source_pdf_url(paper)
        if not source_pdf_url:
            diagnostics = (
                {
                    "severity": "error",
                    "code": "source_pdf_missing",
                    "message": "paper does not have a resolvable source PDF URL",
                },
            )
            status = self.repository.write_status(
                resolved_id,
                status="compile_failed",
                updated_at=_iso(self.clock()),
                diagnostics=diagnostics,
            )
            return PaperVisualCompileResult(
                paper_id=resolved_id,
                status=status.status,
                document=None,
                manifest=None,
                compile_info=None,
                review_report=None,
                source_comparison_report=None,
                gate_report=None,
                diagnostics=diagnostics,
            )

        try:
            pdf_bytes = self.pdf_fetcher(source_pdf_url, _pdf_max_bytes())
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            diagnostics = (_pdf_fetch_failure_diagnostic(exc),)
            status = self.repository.write_status(
                resolved_id,
                status="compile_failed",
                updated_at=_iso(self.clock()),
                diagnostics=diagnostics,
            )
            return PaperVisualCompileResult(
                paper_id=resolved_id,
                status=status.status,
                document=None,
                manifest=None,
                compile_info=None,
                review_report=None,
                source_comparison_report=None,
                gate_report=None,
                diagnostics=diagnostics,
            )

        try:
            draft = self.compiler.compile(
                pdf_bytes=pdf_bytes,
                paper=paper,
                output_dir=self.repository.paper_dir(resolved_id),
                source_pdf_url=source_pdf_url,
                started_at=started,
                finished_at=self.clock(),
            )
        except PaperCompilerError as exc:
            diagnostics = (
                {
                    "severity": "error",
                    "code": exc.code,
                    "message": str(exc),
                },
                *exc.diagnostics,
            )
            status = self.repository.write_status(
                resolved_id,
                status="compile_failed",
                updated_at=_iso(self.clock()),
                diagnostics=diagnostics,
            )
            return PaperVisualCompileResult(
                paper_id=resolved_id,
                status=status.status,
                document=None,
                manifest=None,
                compile_info=None,
                review_report=None,
                source_comparison_report=None,
                gate_report=None,
                diagnostics=diagnostics,
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            diagnostics = (
                {
                    "severity": "error",
                    "code": "paper_visual_compile_failed",
                    "message": str(exc),
                },
            )
            status = self.repository.write_status(
                resolved_id,
                status="compile_failed",
                updated_at=_iso(self.clock()),
                diagnostics=diagnostics,
            )
            return PaperVisualCompileResult(
                paper_id=resolved_id,
                status=status.status,
                document=None,
                manifest=None,
                compile_info=None,
                review_report=None,
                source_comparison_report=None,
                gate_report=None,
                diagnostics=diagnostics,
            )

        gate_report = self.asset_gate.validate(
            document=draft.document,
            manifest=draft.manifest,
            paper_dir=self.repository.paper_dir(resolved_id),
        )
        if not gate_report.get("passed"):
            compile_info = _compile_info_with_status(draft.compile_info, "needs_review", diagnostics=gate_report.get("errors") or ())
            status = self.repository.write_artifacts(
                document=_document_with_status(draft.document, "needs_review"),
                manifest=draft.manifest,
                compile_info=compile_info,
                review_report=None,
                gate_report=gate_report,
                status="needs_review",
                updated_at=_iso(self.clock()),
                diagnostics=tuple(gate_report.get("errors") or ()),
            )
            return PaperVisualCompileResult(
                paper_id=resolved_id,
                status=status.status,
                document=None,
                manifest=None,
                compile_info=compile_info,
                review_report=None,
                source_comparison_report=None,
                gate_report=gate_report,
                diagnostics=status.diagnostics,
            )

        source_comparison_report = self.source_comparer.compare(
            document=draft.document,
            manifest=draft.manifest,
            compile_info=draft.compile_info,
            paper_dir=self.repository.paper_dir(resolved_id),
            paper=paper,
            gate_report=gate_report,
            created_at=self.clock(),
        )
        memory_result = self.source_memory_service.ingest_source_comparison(
            report=source_comparison_report,
            compile_info=draft.compile_info,
            paper=paper,
            artifact_ref=str((self.repository.paper_dir(resolved_id) / "source-comparison-report.json").resolve()),
            journal_path=self.repository.paper_dir(resolved_id) / "source-comparison-memory.json",
        )
        memory_diagnostics = _source_memory_diagnostics(memory_result.to_dict())
        if not source_comparison_report.passed:
            comparison_diagnostics = (
                *tuple(source_comparison_report.errors),
                *tuple(source_comparison_report.warnings),
                *memory_diagnostics,
            )
            compile_info = _compile_info_with_status(
                draft.compile_info,
                "needs_review",
                diagnostics=(*draft.compile_info.diagnostics, *comparison_diagnostics),
            )
            status = self.repository.write_artifacts(
                document=_document_with_status(draft.document, "needs_review"),
                manifest=draft.manifest,
                compile_info=compile_info,
                review_report=None,
                gate_report=gate_report,
                source_comparison_report=source_comparison_report,
                status="needs_review",
                updated_at=_iso(self.clock()),
                diagnostics=comparison_diagnostics,
            )
            return PaperVisualCompileResult(
                paper_id=resolved_id,
                status=status.status,
                document=None,
                manifest=None,
                compile_info=compile_info,
                review_report=None,
                source_comparison_report=source_comparison_report,
                gate_report=gate_report,
                diagnostics=status.diagnostics,
            )

        review_report = self.reviewer.review(
            document=draft.document,
            manifest=draft.manifest,
            gate_report=gate_report,
        )

        document = _document_with_status(draft.document, "compiled")
        diagnostics = (
            *tuple(gate_report.get("warnings") or ()),
            *tuple(source_comparison_report.warnings),
            *_review_diagnostics(review_report),
            *memory_diagnostics,
        )
        compile_info = _compile_info_with_status(
            draft.compile_info,
            "compiled",
            diagnostics=(*draft.compile_info.diagnostics, *diagnostics),
        )
        status = self.repository.write_artifacts(
            document=document,
            manifest=draft.manifest,
            compile_info=compile_info,
            review_report=review_report,
            gate_report=gate_report,
            source_comparison_report=source_comparison_report,
            status="compiled",
            updated_at=_iso(self.clock()),
            diagnostics=diagnostics,
        )
        return PaperVisualCompileResult(
            paper_id=resolved_id,
            status=status.status,
            document=document,
            manifest=draft.manifest,
            compile_info=compile_info,
            review_report=review_report,
            source_comparison_report=source_comparison_report,
            gate_report=gate_report,
            diagnostics=status.diagnostics,
        )

    def plan_visual_compile_backfill(
        self,
        *,
        limit: int | None = None,
        force: bool = False,
        run_id: str | None = None,
    ) -> PaperVisualCompileBackfillPlan:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")

        candidates: list[PaperVisualCompileBackfillCandidate] = []
        scanned_count = 0
        skipped_no_pdf_count = 0
        for paper in self.papers_service.list_published_papers():
            scanned_count += 1
            paper_payload = paper.to_dict()
            source_pdf_url = _source_pdf_url(paper_payload)
            if not source_pdf_url:
                skipped_no_pdf_count += 1
                continue
            reason = self._backfill_reason(paper_payload["id"], force=force)
            if reason is None:
                continue
            status = self.repository.read_status(paper_payload["id"])
            candidates.append(
                PaperVisualCompileBackfillCandidate(
                    paper_id=paper_payload["id"],
                    slug=str(paper_payload.get("slug") or paper_payload["id"]),
                    title=str(paper_payload.get("title") or paper_payload["id"]),
                    current_status=status.status if status is not None else "not_compiled",
                    reason=reason,
                    source_pdf_url=source_pdf_url,
                )
            )
            if limit is not None and len(candidates) >= limit:
                break

        candidate_count = len(candidates)
        skipped_count = max(0, scanned_count - candidate_count - skipped_no_pdf_count)
        return PaperVisualCompileBackfillPlan(
            run_id=run_id,
            force=force,
            limit=limit,
            scanned_count=scanned_count,
            candidate_count=candidate_count,
            skipped_count=skipped_count,
            skipped_no_pdf_count=skipped_no_pdf_count,
            candidates=tuple(candidates),
        )

    def resolve_asset(self, paper_id: str, asset_id: str) -> tuple[Path, str] | None:
        paper = self._paper_dict(paper_id)
        return self.repository.resolve_asset(paper["id"], asset_id)

    def source_preview(
        self,
        paper_id: str,
        *,
        page_number: int,
        bbox: tuple[float, float, float, float],
    ) -> Path | None:
        paper = self._paper_dict(paper_id)
        resolved_id = paper["id"]
        manifest = self.repository.read_manifest(resolved_id)
        if manifest is None:
            return None
        if not any(asset.kind == "page" and asset.pageNumber == page_number for asset in manifest.assets):
            return None
        source_file_name = manifest.sourcePdfFileName or "source.pdf"
        source_pdf = self.repository.source_pdf_path(resolved_id, source_file_name)
        if not source_pdf.exists():
            return None
        bbox_hash = hashlib.sha256(json.dumps({"page": page_number, "bbox": bbox}, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        output_path = self.repository.paper_dir(resolved_id) / "source-previews" / f"page-{page_number:04d}-{bbox_hash}.png"
        if output_path.exists():
            return output_path
        return self.compiler.render_source_preview(
            source_pdf_path=source_pdf,
            page_number=page_number,
            bbox=bbox,
            output_path=output_path,
        )

    def _paper_dict(self, paper_id: str) -> dict[str, Any]:
        paper = self.papers_service.get_paper(paper_id)
        payload = paper.to_dict()
        if not payload.get("id"):
            raise PaperNotFoundError("paper not found")
        return payload

    def _backfill_reason(self, paper_id: str, *, force: bool) -> str | None:
        status = self.repository.read_status(paper_id)
        if force:
            return "forced"
        if status is None:
            return "missing_status"
        if status.status != "compiled":
            if status.status == "compile_failed" and _is_terminal_pdf_fetch_failure(status.diagnostics):
                return None
            return status.status
        if status.compileInfo is None or status.compileInfo.status != "compiled":
            return "compile_info_incomplete"
        published = self.repository.read_published_document(paper_id)
        if published is None:
            return "published_document_missing"
        document, _manifest = published
        if _document_has_outdated_table_style_schema(document):
            return "table_style_schema_outdated"
        if status.sourceComparisonReport is None:
            return "source_comparison_missing"
        if not status.sourceComparisonReport.passed:
            return "source_comparison_failed"
        return None


def _document_with_status(document: PaperDocument, status: str) -> PaperDocument:
    return PaperDocument(
        paperId=document.paperId,
        schemaVersion=document.schemaVersion or PAPER_DOCUMENT_SCHEMA_VERSION,
        status=status,  # type: ignore[arg-type]
        title=document.title,
        compiledAt=document.compiledAt,
        sourceHash=document.sourceHash,
        paper=document.paper,
        outline=document.outline,
        blocks=document.blocks,
        auxiliary=document.auxiliary,
    )


def _compile_info_with_status(
    compile_info: PaperCompileInfo,
    status: str,
    *,
    diagnostics: Sequence[Mapping[str, Any]],
) -> PaperCompileInfo:
    return PaperCompileInfo(
        paperId=compile_info.paperId,
        status=status,  # type: ignore[arg-type]
        provider=compile_info.provider,
        sourceHash=compile_info.sourceHash,
        startedAt=compile_info.startedAt,
        finishedAt=compile_info.finishedAt,
        sourcePdfUrl=compile_info.sourcePdfUrl,
        pageCount=compile_info.pageCount,
        blockCount=compile_info.blockCount,
        assetCount=compile_info.assetCount,
        diagnostics=tuple(dict(item) for item in diagnostics),
    )


def _review_diagnostics(review_report: PaperReviewReport) -> tuple[Mapping[str, Any], ...]:
    if review_report.verdict == "pass":
        return ()
    if review_report.verdict == "unavailable":
        return (
            {
                "severity": "warning",
                "code": "ai_review_unavailable",
                "message": review_report.summary,
            },
        )
    return (
        {
            "severity": "warning",
            "code": "ai_review_non_blocking_failed",
            "message": review_report.summary,
        },
    )


def _source_memory_diagnostics(result: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    error = _text(result.get("error"))
    if not error:
        return ()
    return (
        {
            "severity": "warning",
            "code": "source_comparison_memory_failed",
            "message": error,
        },
    )


def _document_has_outdated_table_style_schema(document: PaperDocument) -> bool:
    for block in document.blocks:
        if block.type != "table":
            continue
        table_model = block.metadata.get("tableModel")
        if not isinstance(table_model, Mapping):
            return True
        if _positive_table_schema_version(table_model.get("styleSchemaVersion")) < PAPER_TABLE_MODEL_STYLE_SCHEMA_VERSION:
            return True
    return False


def _positive_table_schema_version(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str):
        try:
            return max(0, int(value.strip()))
        except ValueError:
            return 0
    return 0


def _source_pdf_url(paper: Mapping[str, Any]) -> str | None:
    for key in ("pdfUrl", "paperUrl", "arxivUrl"):
        value = _normalized_pdf_url(paper.get(key))
        if value:
            return value
    arxiv_id = _text(paper.get("arxivId"))
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return None


def _default_paper_compiler() -> SourceFirstPaperCompiler:
    try:
        layout_provider = build_model_layout_provider_from_env()
    except PaperLayoutProviderConfigurationError:
        raise
    return SourceFirstPaperCompiler(
        source_compiler=ArxivSourcePaperCompiler(),
        fallback_compiler=PyMuPDFPaperCompiler(layout_provider=layout_provider),
    )


def _normalized_pdf_url(value: Any) -> str | None:
    text = _text(value).rstrip(".,;:)]}>'\"")
    if not text:
        return None
    if "arxiv.org/abs/" in text:
        text = text.replace("/abs/", "/pdf/")
    if "arxiv.org/pdf/" in text and not text.casefold().endswith(".pdf"):
        text = f"{text}.pdf"
    if "arxiv.org/pdf/" not in text and not text.casefold().endswith(".pdf"):
        return None
    if text.startswith("https://") or text.startswith("http://"):
        return text.replace("http://", "https://", 1)
    return None


def _ai_panel_payload(paper: Mapping[str, Any], status: PaperCompileStatusRecord) -> Mapping[str, Any]:
    return {
        "summary": paper.get("aiSummary"),
        "signals": {
            "abstractSnippet": paper.get("abstractSnippet"),
            "methodRefs": paper.get("methodRefs") or [],
            "taskRefs": paper.get("taskRefs") or [],
            "benchmarks": paper.get("benchmarks") or [],
            "implementations": paper.get("implementations") or [],
        },
        "review": status.reviewReport.to_dict() if status.reviewReport is not None else None,
        "diagnostics": [dict(item) for item in status.diagnostics],
    }


def _fetch_pdf_bytes(url: str, max_bytes: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, PDF_FETCH_RETRY_ATTEMPTS + 1):
        try:
            return _fetch_pdf_bytes_once(url, max_bytes)
        except HTTPError as exc:
            if not _is_retryable_http_error(exc) or attempt >= PDF_FETCH_RETRY_ATTEMPTS:
                raise
            last_error = exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt >= PDF_FETCH_RETRY_ATTEMPTS:
                raise
            last_error = exc
        if PDF_FETCH_RETRY_DELAY_SECONDS > 0:
            time.sleep(PDF_FETCH_RETRY_DELAY_SECONDS)
    if last_error is not None:
        raise last_error
    raise RuntimeError("PDF fetch retry loop exited unexpectedly")


def _fetch_pdf_bytes_once(url: str, max_bytes: int) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/pdf,*/*",
            "User-Agent": "NewsRoom/0.1 paper-visual-compiler contact: local-dev",
        },
    )
    with urlopen(request, timeout=90) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("PDF exceeds configured maximum size")
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("PDF exceeds configured maximum size")
    return payload


def _is_retryable_http_error(error: HTTPError) -> bool:
    return getattr(error, "code", None) in {408, 425, 429, 500, 502, 503, 504}


def _pdf_fetch_failure_diagnostic(error: Exception) -> Mapping[str, Any]:
    code = "pdf_fetch_failed"
    retryable = True
    if isinstance(error, HTTPError):
        if error.code == 404:
            code = "source_pdf_not_found"
            retryable = False
        elif error.code in {401, 403, 410, 451}:
            code = "source_pdf_unavailable"
            retryable = False
        elif not _is_retryable_http_error(error):
            code = "source_pdf_unavailable"
            retryable = False
    elif isinstance(error, ValueError) and "PDF exceeds configured maximum size" in str(error):
        code = "source_pdf_too_large"
        retryable = False
    return {
        "severity": "error",
        "code": code,
        "message": str(error),
        "retryable": retryable,
    }


def _is_terminal_pdf_fetch_failure(diagnostics: Sequence[Mapping[str, Any]]) -> bool:
    for item in diagnostics:
        if _text(item.get("code")) in TERMINAL_PDF_FETCH_CODES:
            return True
    return False


def _pdf_max_bytes() -> int:
    value = os.environ.get(PAPERS_PDF_MAX_BYTES_ENV)
    if value:
        try:
            parsed = int(value)
        except ValueError:
            parsed = DEFAULT_READER_PDF_MAX_BYTES
        return parsed if parsed > 0 else DEFAULT_READER_PDF_MAX_BYTES
    return max(DEFAULT_PDF_MAX_BYTES, DEFAULT_READER_PDF_MAX_BYTES)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
