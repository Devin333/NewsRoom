from __future__ import annotations

import hashlib
import json
import os
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
    PaperVisualCompilerRepository,
    PyMuPDFPaperCompiler,
    SourceFirstPaperCompiler,
    build_model_layout_provider_from_env,
)
from business.boards.paper_radar.visual_compiler.models import PAPER_DOCUMENT_SCHEMA_VERSION
from business.boards.paper_radar.visual_compiler.base import PaperCompilerError
from business.boards.paper_radar.visual_compiler.reviewer import LLMPaperDocumentReviewer, PaperDocumentReviewer
from interfaces.services.paper_ingest_service import DEFAULT_PDF_MAX_BYTES, PAPERS_PDF_MAX_BYTES_ENV
from interfaces.services.paper_service import PaperNotFoundError, PapersApplicationService


PAPER_VISUAL_COMPILE_TASK_TYPE = "papers.visual_compile"


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
            "gateReport": dict(self.gate_report) if self.gate_report is not None else None,
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


class PaperVisualCompilerApplicationService:
    def __init__(
        self,
        *,
        papers_service: PapersApplicationService | None = None,
        repository: PaperVisualCompilerRepository | None = None,
        compiler: PaperCompiler | None = None,
        asset_gate: PaperAssetGate | None = None,
        reviewer: PaperDocumentReviewer | None = None,
        pdf_fetcher: Callable[[str, int], bytes] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.papers_service = papers_service or PapersApplicationService()
        self.repository = repository or PaperVisualCompilerRepository()
        self.compiler = compiler or _default_paper_compiler()
        self.asset_gate = asset_gate or PaperAssetGate()
        self.reviewer = reviewer or LLMPaperDocumentReviewer(clock=clock)
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
                gate_report=None,
                diagnostics=diagnostics,
            )

        try:
            pdf_bytes = self.pdf_fetcher(source_pdf_url, _pdf_max_bytes())
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
                gate_report=None,
                diagnostics=diagnostics,
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            diagnostics = (
                {
                    "severity": "error",
                    "code": "pdf_fetch_failed",
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
                gate_report=gate_report,
                diagnostics=status.diagnostics,
            )

        review_report = self.reviewer.review(
            document=draft.document,
            manifest=draft.manifest,
            gate_report=gate_report,
        )
        if review_report.verdict != "pass":
            diagnostics = (
                {
                    "severity": "error",
                    "code": "ai_review_unavailable" if review_report.verdict == "unavailable" else "ai_review_rejected",
                    "message": review_report.summary,
                },
            )
            compile_info = _compile_info_with_status(draft.compile_info, "review_failed", diagnostics=diagnostics)
            status = self.repository.write_artifacts(
                document=_document_with_status(draft.document, "review_failed"),
                manifest=draft.manifest,
                compile_info=compile_info,
                review_report=review_report,
                gate_report=gate_report,
                status="review_failed",
                updated_at=_iso(self.clock()),
                diagnostics=diagnostics,
            )
            return PaperVisualCompileResult(
                paper_id=resolved_id,
                status=status.status,
                document=None,
                manifest=None,
                compile_info=compile_info,
                review_report=review_report,
                gate_report=gate_report,
                diagnostics=status.diagnostics,
            )

        document = _document_with_status(draft.document, "compiled")
        compile_info = _compile_info_with_status(draft.compile_info, "compiled", diagnostics=draft.compile_info.diagnostics)
        status = self.repository.write_artifacts(
            document=document,
            manifest=draft.manifest,
            compile_info=compile_info,
            review_report=review_report,
            gate_report=gate_report,
            status="compiled",
            updated_at=_iso(self.clock()),
            diagnostics=tuple(gate_report.get("warnings") or ()),
        )
        return PaperVisualCompileResult(
            paper_id=resolved_id,
            status=status.status,
            document=document,
            manifest=draft.manifest,
            compile_info=compile_info,
            review_report=review_report,
            gate_report=gate_report,
            diagnostics=status.diagnostics,
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


def _pdf_max_bytes() -> int:
    value = os.environ.get(PAPERS_PDF_MAX_BYTES_ENV)
    if value:
        try:
            parsed = int(value)
        except ValueError:
            parsed = DEFAULT_PDF_MAX_BYTES
        return parsed if parsed > 0 else DEFAULT_PDF_MAX_BYTES
    return DEFAULT_PDF_MAX_BYTES


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
