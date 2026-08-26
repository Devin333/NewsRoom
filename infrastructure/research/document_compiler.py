from __future__ import annotations

from typing import Any

from business.research.domain.common import SourceLineage, stable_research_id
from business.research.domain.document import ResearchDocument, ResearchSection
from business.research.domain.paper import PaperSourceRecord
from business.research.ports.document_compiler import DocumentCompilerPort
from business.research.ports.document_parser import DocumentParserPort
from framework.shared.graph_identity import GraphExecutionIdentity
from infrastructure.external.sources.arxiv import ArxivSourceConnector
from infrastructure.external.sources.fetch_policy import SourceRateLimitExceededError
from infrastructure.research.errors import (
    ResearchAdapterError,
    ResearchDocumentCompileError,
)
from infrastructure.research.source_provider import require_arxiv_id


class ResearchDocumentCompilerAdapter:
    """Compile accepted arXiv sources without inventing unavailable content."""

    def __init__(
        self,
        source_fetcher: ArxivSourceConnector | Any | None = None,
        *,
        latex_compiler: DocumentCompilerPort | None = None,
        pdf_parser: DocumentParserPort | None = None,
        allow_abstract_fallback: bool = True,
    ) -> None:
        self._source_fetcher = source_fetcher or ArxivSourceConnector()
        self._latex_compiler = latex_compiler
        self._pdf_parser = pdf_parser
        self._allow_abstract_fallback = bool(allow_abstract_fallback)

    def compile(
        self,
        source: PaperSourceRecord,
        *,
        execution_identity: GraphExecutionIdentity | None = None,
    ) -> ResearchDocument:
        if source.source_type != "arxiv":
            raise ResearchDocumentCompileError("only arXiv Research sources are supported")
        if not source.source_hash:
            raise ResearchDocumentCompileError(
                "accepted arXiv source record is missing its source hash",
                retryable=False,
            )
        arxiv_id = require_arxiv_id(source.source_url)
        attempts: list[dict[str, Any]] = []

        if self._latex_compiler is None:
            attempts.append(_unavailable_attempt("latex"))
        else:
            try:
                document = self._latex_compiler.compile(source)
            except Exception as exc:
                attempts.append(_failed_attempt("latex", exc))
            else:
                return _with_compile_metadata(
                    document,
                    source=source,
                    compiler="latex",
                    attempts=[{"compiler": "latex", "status": "succeeded"}],
                    missing_information=[],
                )

        if self._pdf_parser is None:
            attempts.append(_unavailable_attempt("pdf_cascade"))
        else:
            try:
                package = self._source_fetcher.fetch_pdf_package(arxiv_id)
                parser = self._pdf_parser
                try:
                    document = parser.parse(
                        source.paper_id,
                        package.content,
                        execution_identity=execution_identity,
                    )
                except TypeError as exc:
                    # Existing pure/fake parser ports intentionally keep the
                    # two-argument protocol.  Only the external adapter needs
                    # the physical Graph identity keyword.
                    if "execution_identity" not in str(exc):
                        raise
                    document = parser.parse(source.paper_id, package.content)
            except Exception as exc:
                attempts.append(_failed_attempt("pdf_cascade", exc))
            else:
                return _with_compile_metadata(
                    document,
                    source=source,
                    compiler="pdf_cascade",
                    attempts=[
                        *attempts,
                        {"compiler": "pdf_cascade", "status": "succeeded"},
                    ],
                    missing_information=[],
                    source_package_checksum=package.checksum,
                )

        if not self._allow_abstract_fallback:
            raise ResearchDocumentCompileError(
                "configured Research document compilers could not produce a document",
                retryable=True,
            )
        return _abstract_document(source, attempts=attempts)


def _abstract_document(
    source: PaperSourceRecord,
    *,
    attempts: list[dict[str, Any]],
) -> ResearchDocument:
    abstract = str(source.metadata.get("abstract") or "").strip()
    title = str(source.metadata.get("title") or "Abstract").strip() or "Abstract"
    if not abstract:
        raise ResearchDocumentCompileError(
            "accepted arXiv metadata contains no abstract for fallback",
            retryable=False,
        )
    arxiv_id = require_arxiv_id(source.source_url)
    source_ref = f"arxiv://{arxiv_id}/abstract"
    source_hash = source.source_hash
    if not source_hash:
        raise ResearchDocumentCompileError(
            "accepted arXiv source record is missing its source hash",
            retryable=False,
        )
    return ResearchDocument(
        paper_id=source.paper_id,
        source_hash=source_hash,
        sections=[
            ResearchSection(
                section_id=stable_research_id(
                    "research_section",
                    source.paper_id,
                    "abstract",
                ),
                title="Abstract",
                level=1,
                text=abstract,
                source_ref=source_ref,
                metadata={
                    "section_type": "abstract",
                    "source_title": title,
                    "derived_from": "accepted_arxiv_metadata",
                },
            )
        ],
        lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
        metadata={
            "parse_source": "arxiv_abstract",
            "compiler": "abstract_fallback",
            "degraded": True,
            "missing_information": ["full_text_sections"],
            "compiler_attempts": list(attempts),
            "arxiv_id": arxiv_id,
        },
    )


def _failed_attempt(compiler: str, exc: Exception) -> dict[str, Any]:
    attempt: dict[str, Any] = {
        "compiler": compiler,
        "status": "failed",
        "error_type": type(exc).__name__,
    }
    if isinstance(exc, ResearchAdapterError):
        attempt["error_code"] = exc.error_code
        attempt["retryable"] = exc.retryable
    if isinstance(exc, SourceRateLimitExceededError):
        attempt.update(
            {
                "error_code": "source_rate_limited",
                "retryable": True,
                "domain": exc.domain,
                "limit_per_minute": exc.limit_per_minute,
                "window_seconds": exc.window_seconds,
                "retry_after_seconds": exc.retry_after_seconds,
            }
        )
    return attempt


def _unavailable_attempt(compiler: str) -> dict[str, str]:
    return {
        "compiler": compiler,
        "status": "unavailable",
        "error_type": "not_configured",
    }


def _with_compile_metadata(
    document: ResearchDocument,
    *,
    source: PaperSourceRecord,
    compiler: str,
    attempts: list[dict[str, Any]],
    missing_information: list[str],
    source_package_checksum: str | None = None,
) -> ResearchDocument:
    source_hash = source.source_hash
    if not source_hash:
        raise ResearchDocumentCompileError(
            "accepted arXiv source record is missing its source hash",
            retryable=False,
        )
    metadata = {
        **dict(document.metadata),
        "compiler": compiler,
        "compiler_attempts": list(attempts),
        "compiled_content_hash": document.source_hash,
        "missing_information": list(missing_information),
    }
    if document.lineage.source_hash and document.lineage.source_hash != document.source_hash:
        metadata["compiled_lineage_source_hash"] = document.lineage.source_hash
    if source_package_checksum:
        metadata["source_package_checksum"] = source_package_checksum
    return document.model_copy(
        update={
            "source_hash": source_hash,
            "lineage": document.lineage.model_copy(update={"source_hash": source_hash}),
            "metadata": metadata,
        }
    )


__all__ = ["ResearchDocumentCompilerAdapter"]
