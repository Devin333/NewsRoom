from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.research.application.catalog import (
    InMemoryResearchCatalogRepository,
    ResearchPaperCatalogService,
)
from backend.research.application.parse_paper import (
    MetadataOnlySourceResolver,
    ParsePaperError,
    ParsePaperRequest,
    ParsePaperUseCase,
    ResolvedPaperSource,
    infer_source_type,
)
from backend.research.document.chunk_manifest import ChunkManifestManager
from backend.research.document.chunker import PaperDocumentChunker
from backend.research.domain import (
    ResearchDocument,
    ResearchEvidencePack,
    ResearchPaper,
    ResearchPaperIdentity,
    ResearchSection,
    ResearchSourceSnapshot,
    SourceLineage,
)
from backend.research.domain.paper import PaperSourceRecord


class _Resolver:
    def __init__(self, *, source_url: str, paper_id: str, content: bytes) -> None:
        self.source_url = source_url
        self.paper_id = paper_id
        self.content = content

    def resolve(self, request: ParsePaperRequest) -> ResolvedPaperSource:
        paper = ResearchPaper(
            paper_id=self.paper_id,
            title="A Stable Paper Identity",
            authors=["Ada Lovelace"],
            published_at=datetime(2026, 1, 2, tzinfo=UTC),
            source="publisher",
            source_url=self.source_url,
        )
        digest = __import__("hashlib").sha256(self.content).hexdigest()
        snapshot = ResearchSourceSnapshot(
            snapshot_id=f"snapshot-{self.paper_id}",
            paper_id=self.paper_id,
            source_type="publisher",
            canonical_url=self.source_url,
            external_id=None,
            content_type="text/html",
            source_hash=digest,
            fetched_at=datetime.now(UTC),
            lineage=SourceLineage(source_refs=[self.source_url], source_hash=digest),
        )
        return ResolvedPaperSource(
            paper=paper,
            snapshot=snapshot,
            content=self.content,
            content_type="text/html",
        )


class _Parser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        self.calls += 1
        digest = __import__("hashlib").sha256(source_bytes).hexdigest()
        source_ref = f"paper://{paper_id}/method"
        return ResearchDocument(
            paper_id=paper_id,
            source_hash=digest,
            sections=[
                ResearchSection(
                    section_id="method",
                    title="Method",
                    text="The method is fully traceable.",
                    source_ref=source_ref,
                )
            ],
            lineage=SourceLineage(source_refs=[source_ref], source_hash=digest),
            metadata={"parse_source": "html"},
        )


class _Artifacts:
    def __init__(self) -> None:
        self.payloads: list[tuple[str, dict]] = []

    def publish(self, *, artifact_type: str, payload: dict, metadata: dict | None = None) -> str:
        self.payloads.append((artifact_type, {"payload": payload, "metadata": metadata or {}}))
        return f"artifact://test/{artifact_type}/{len(self.payloads)}"


class _FailingParser:
    def parse(self, _paper_id: str, _source_bytes: bytes) -> ResearchDocument:
        raise RuntimeError("primary parser unavailable")


class _CompilerFallback:
    def __init__(self) -> None:
        self.source: PaperSourceRecord | None = None

    def compile(self, source: PaperSourceRecord) -> ResearchDocument:
        self.source = source
        return ResearchDocument(
            paper_id=source.paper_id,
            source_hash=source.source_hash or "fallback-hash",
            sections=[
                ResearchSection(
                    section_id="fallback-method",
                    title="Method",
                    text="Compiler fallback preserved the source lineage.",
                    source_ref="paper://fallback/method",
                )
            ],
            lineage=SourceLineage(
                source_refs=["paper://fallback/method"],
                source_hash=source.source_hash or "fallback-hash",
            ),
            metadata={"compiler": "fallback"},
        )


def test_equivalent_sources_merge_by_fingerprint_and_retain_provenance(tmp_path: Path) -> None:
    repository = InMemoryResearchCatalogRepository()
    parser = _Parser()
    events = []
    artifacts = _Artifacts()

    class _Events:
        def append(self, run_id: str, event: dict) -> None:
            events.append({"run_id": run_id, **event})

    use_case = ParsePaperUseCase(
        source_resolver=_Resolver(
            source_url="https://publisher.example/paper",
            paper_id="publisher-paper",
            content=b"<html><h1>Method</h1><p>text</p></html>",
        ),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
        document_repository=repository,
        document_parser=parser,
        artifact_store=artifacts,
        event_sink=_Events(),
        chunker=PaperDocumentChunker(),
        chunk_manifest=ChunkManifestManager(tmp_path / "manifests"),
    )

    first = use_case.parse(
        ParsePaperRequest(
            source="https://publisher.example/paper",
            run_id="run-1",
            tenant_id="tenant-a",
            user_id="user-a",
        )
    )

    use_case._resolver = _Resolver(  # noqa: SLF001 - contract test swaps source adapter
        source_url="https://publisher.example/alternate",
        paper_id="publisher-paper-v2",
        content=b"<html><h1>Method</h1><p>text</p></html>",
    )
    second = use_case.parse(
        ParsePaperRequest(
            source="https://publisher.example/alternate",
            run_id="run-2",
            tenant_id="tenant-a",
            user_id="user-a",
        )
    )

    assert first.status == "parsed"
    assert second.paper_id == first.paper_id
    assert second.identity is not None
    assert len(repository.list_for_paper(first.paper_id, actor_scope={"tenant_id": "tenant-a", "user_id": "user-a"})) == 2
    assert set(second.identity.field_provenance["title"]) == {first.source_snapshots[0].snapshot_id, second.source_snapshots[0].snapshot_id}
    assert second.idempotent is True
    assert second.artifact_refs == first.artifact_refs
    assert len(artifacts.payloads) == 3
    assert parser.calls == 1
    assert any(event["from_status"] == "resolving" and event["to_status"] == "parsing" for event in events)
    manifest_files = list((tmp_path / "manifests").rglob("chunk_manifest.json"))
    assert len(manifest_files) == 1

    third = use_case.parse(
        ParsePaperRequest(
            source="https://publisher.example/alternate",
            run_id="run-3",
            tenant_id="tenant-a",
            user_id="user-a",
        )
    )
    assert third.idempotent is True
    assert len(repository.list_for_paper(first.paper_id, actor_scope={"tenant_id": "tenant-a", "user_id": "user-a"})) == 2


def test_metadata_only_never_claims_a_document() -> None:
    repository = InMemoryResearchCatalogRepository()
    result = ParsePaperUseCase(
        source_resolver=MetadataOnlySourceResolver(),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
        document_repository=repository,
    ).parse(
        ParsePaperRequest(
            source="https://publisher.example/restricted",
            source_type="publisher",
            tenant_id="tenant-a",
            user_id="user-a",
        )
    )

    assert result.status == "metadata_only"
    assert result.document is None
    assert result.source_snapshots[0].access_status == "metadata_only"
    assert result.source_snapshots[0].actor_scope == {"tenant_id": "tenant-a", "user_id": "user-a"}
    assert repository.get_document(result.paper_id, actor_scope={"tenant_id": "tenant-a", "user_id": "user-a"}) is None


def test_metadata_only_projects_catalog_candidates_without_claiming_document() -> None:
    repository = InMemoryResearchCatalogRepository()
    catalog = ResearchPaperCatalogService(catalog_repository=repository)
    result = ParsePaperUseCase(
        source_resolver=MetadataOnlySourceResolver(),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
        document_repository=repository,
        catalog_projection=catalog,
    ).parse(
        ParsePaperRequest(
            source="https://publisher.example/restricted-with-metadata",
            source_type="publisher",
            tenant_id="tenant-a",
            user_id="user-a",
            metadata={"title": "Metadata paper", "tasks": ["task-x"]},
        )
    )

    assert result.status == "metadata_only"
    assert result.catalog_status == "catalog_partial"
    assert result.catalog_entry is not None
    assert result.catalog_entry.relations[0].status == "candidate"
    assert result.document is None


def test_github_repository_requires_explicit_paper_context() -> None:
    repository = InMemoryResearchCatalogRepository()
    events = []

    class _Events:
        def append(self, run_id: str, event: dict) -> None:
            events.append({"run_id": run_id, **event})

    use_case = ParsePaperUseCase(
        source_resolver=MetadataOnlySourceResolver(),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
        event_sink=_Events(),
    )

    with pytest.raises(ParsePaperError) as error:
        use_case.parse(
            ParsePaperRequest(
                source="https://github.com/example/research-code",
                source_type="github",
                tenant_id="tenant-a",
                user_id="user-a",
            )
        )

    assert error.value.code == "github_paper_context_required"
    assert repository._papers == {}  # noqa: SLF001 - verify no identity was persisted
    assert events[-1]["to_status"] == "failed"


def test_explicit_github_observation_does_not_overwrite_existing_paper_title() -> None:
    repository = InMemoryResearchCatalogRepository()
    existing = ResearchPaper(
        paper_id="paper-known",
        title="Authoritative paper title",
        authors=["Paper Author"],
        source="arxiv",
        metadata={"actor_scope": {"tenant_id": "tenant-a", "user_id": "user-a"}},
    )
    repository.save(existing)
    repository.save(
        ResearchPaperIdentity(
            paper_id=existing.paper_id,
            title=existing.title,
            authors=existing.authors,
            metadata={"actor_scope": {"tenant_id": "tenant-a", "user_id": "user-a"}},
        )
    )

    resolved = MetadataOnlySourceResolver().resolve(
        ParsePaperRequest(
            source="https://github.com/example/research-code",
            source_type="github",
            tenant_id="tenant-a",
            user_id="user-a",
            metadata={"paper_id": existing.paper_id, "title": "Repository name"},
        )
    )
    resolved = resolved.__class__(
        paper=resolved.paper.model_copy(update={"paper_id": existing.paper_id}),
        snapshot=resolved.snapshot.model_copy(update={"paper_id": existing.paper_id}),
        content=resolved.content,
        content_type=resolved.content_type,
        source_record=resolved.source_record,
        access_status=resolved.access_status,
        diagnostics=resolved.diagnostics,
    )
    class _ResolvedResolver:
        def resolve(self, _request: ParsePaperRequest) -> ResolvedPaperSource:
            return resolved

    result = ParsePaperUseCase(
        source_resolver=_ResolvedResolver(),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
    )
    parsed = result.parse(
        ParsePaperRequest(
            source="https://github.com/example/research-code",
            source_type="github",
            tenant_id="tenant-a",
            user_id="user-a",
            metadata={"paper_id": existing.paper_id, "title": "Repository name"},
        )
    )

    assert parsed.paper.title == existing.title
    assert repository.get_paper(existing.paper_id, actor_scope={"tenant_id": "tenant-a", "user_id": "user-a"}).title == existing.title


def test_metadata_only_reuses_snapshot_and_reports_idempotency() -> None:
    repository = InMemoryResearchCatalogRepository()
    use_case = ParsePaperUseCase(
        source_resolver=MetadataOnlySourceResolver(),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
    )
    request = ParsePaperRequest(
        source="https://publisher.example/restricted",
        source_type="publisher",
        tenant_id="tenant-a",
        user_id="user-a",
    )

    first = use_case.parse(request.model_copy(update={"run_id": "metadata-run-1"}))
    second = use_case.parse(request.model_copy(update={"run_id": "metadata-run-2"}))

    assert first.status == second.status == "metadata_only"
    assert second.idempotent is True
    assert second.source_snapshots[0].snapshot_id == first.source_snapshots[0].snapshot_id


def test_parser_failure_uses_compiler_fallback_with_canonical_source_record() -> None:
    repository = InMemoryResearchCatalogRepository()
    compiler = _CompilerFallback()
    use_case = ParsePaperUseCase(
        source_resolver=_Resolver(
            source_url="https://publisher.example/fallback",
            paper_id="fallback-paper",
            content=b"fallback content",
        ),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
        document_repository=repository,
        document_parser=_FailingParser(),
        document_compiler=compiler,
    )

    result = use_case.parse(
        ParsePaperRequest(
            source="https://publisher.example/fallback",
            tenant_id="tenant-a",
            user_id="user-a",
        )
    )

    assert result.status == "parsed"
    assert result.document is not None
    assert compiler.source is not None
    assert compiler.source.paper_id == result.paper_id
    assert compiler.source.source_hash == result.source_snapshots[0].source_hash
    assert result.document.metadata["parser_attempts"][0]["backend"] == "document_parser"
    assert result.document.metadata["parser_attempts"][0]["reason_code"] == "document_parser_failed"
    assert "primary parser unavailable" not in str(result.document.model_dump(mode="json"))


def test_unsupported_binary_source_fails_without_text_fallback() -> None:
    repository = InMemoryResearchCatalogRepository()
    use_case = ParsePaperUseCase(
        source_resolver=_Resolver(
            source_url="https://publisher.example/archive.zip",
            paper_id="unsupported-paper",
            content=b"PK\x03\x04not-a-paper-archive",
        ),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
    )

    with pytest.raises(ParsePaperError) as error:
        use_case.parse(
            ParsePaperRequest(
                source="https://publisher.example/archive.zip",
                source_type="publisher",
            )
        )

    assert error.value.code == "unsupported_format"
    assert error.value.status_code == 415


def test_evidence_pack_preserves_lineage_scope_when_metadata_has_other_fields() -> None:
    pack = ResearchEvidencePack(
        pack_id="pack-scope",
        paper_id="paper-scope",
        lineage=SourceLineage(
            source_refs=["paper://scope"],
            metadata={"actor_scope": {"tenant_id": "tenant-a"}},
        ),
        metadata={"builder": "test"},
    )

    assert pack.actor_scope == {"tenant_id": "tenant-a"}
    assert pack.metadata["actor_scope"] == {"tenant_id": "tenant-a"}
    assert pack.lineage.metadata["actor_scope"] == {"tenant_id": "tenant-a"}


def test_source_snapshot_and_document_merge_lineage_scope_with_unrelated_metadata() -> None:
    lineage = SourceLineage(
        source_refs=["paper://scope"],
        metadata={"actor_scope": {"tenant_id": "tenant-a"}},
    )
    snapshot = ResearchSourceSnapshot(
        snapshot_id="snapshot-scope",
        paper_id="paper-scope",
        canonical_url="https://example.test/paper",
        lineage=lineage,
        metadata={"fetcher": "test"},
    )
    document = ResearchDocument(
        paper_id="paper-scope",
        source_hash="hash-scope",
        lineage=SourceLineage(
            source_refs=["paper://scope"],
            source_hash="hash-scope",
            metadata={"actor_scope": {"tenant_id": "tenant-a"}},
        ),
        metadata={"parser_backend": "test"},
    )

    assert snapshot.actor_scope == {"tenant_id": "tenant-a"}
    assert snapshot.metadata["actor_scope"] == {"tenant_id": "tenant-a"}
    assert document.actor_scope == {"tenant_id": "tenant-a"}
    assert document.metadata["actor_scope"] == {"tenant_id": "tenant-a"}


def test_doi_url_is_classified_as_doi_source() -> None:
    assert infer_source_type("https://doi.org/10.1234/Example") == "doi"


def test_parser_retry_is_bounded_and_recorded_as_durable_phase_event() -> None:
    repository = InMemoryResearchCatalogRepository()
    events: list[dict] = []

    class _Events:
        def append(self, run_id: str, event: dict) -> None:
            events.append({"run_id": run_id, **event})

    class _RetryingUseCase(ParsePaperUseCase):
        attempts = 0

        def _parse_document(self, paper, snapshot, resolved):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("transient parser worker failure")
            return _Parser().parse(paper.paper_id, resolved.content or b"")

    use_case = _RetryingUseCase(
        source_resolver=_Resolver(
            source_url="https://publisher.example/retry",
            paper_id="retry-paper",
            content=b"retryable source",
        ),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
        document_repository=repository,
        event_sink=_Events(),
        max_retries=1,
    )

    result = use_case.parse(ParsePaperRequest(source="https://publisher.example/retry", run_id="retry-run"))

    assert result.status == "parsed"
    assert use_case.attempts == 2
    retry_events = [event for event in events if event.get("phase") == "retry_scheduled"]
    assert len(retry_events) == 1
    assert retry_events[0]["attempt"] == 1
    assert retry_events[0]["max_retries"] == 1


def test_source_retry_is_bounded_and_recorded_before_identity_resolution() -> None:
    repository = InMemoryResearchCatalogRepository()
    events: list[dict] = []

    class _Events:
        def append(self, run_id: str, event: dict) -> None:
            events.append({"run_id": run_id, **event})

    class _FlakyResolver:
        attempts = 0

        def resolve(self, request: ParsePaperRequest) -> ResolvedPaperSource:
            self.attempts += 1
            if self.attempts == 1:
                error = ConnectionError("temporary source transport failure")
                error.retryable = True  # type: ignore[attr-defined]
                raise error
            return _Resolver(
                source_url="https://publisher.example/source-retry",
                paper_id="source-retry-paper",
                content=b"source retry content",
            ).resolve(request)

    resolver = _FlakyResolver()
    result = ParsePaperUseCase(
        source_resolver=resolver,
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
        document_repository=repository,
        document_parser=_Parser(),
        event_sink=_Events(),
        max_retries=1,
    ).parse(
        ParsePaperRequest(
            source="https://publisher.example/source-retry",
            run_id="source-retry-run",
        )
    )

    assert result.status == "parsed"
    assert resolver.attempts == 2
    retry_events = [event for event in events if event.get("phase") == "retry_scheduled"]
    assert len(retry_events) == 1
    assert retry_events[0]["status"] == "resolving"
    assert retry_events[0]["attempt"] == 1


def test_parse_error_emits_terminal_failed_event_before_rethrowing() -> None:
    repository = InMemoryResearchCatalogRepository()
    events: list[dict] = []

    class _Events:
        def append(self, run_id: str, event: dict) -> None:
            events.append({"run_id": run_id, **event})

    class _FailingUseCase(ParsePaperUseCase):
        def _parse_document(self, paper, snapshot, resolved):  # type: ignore[no-untyped-def]
            raise ParsePaperError("document_parse_failed", "structured parser failed")

    use_case = _FailingUseCase(
        source_resolver=_Resolver(
            source_url="https://publisher.example/failed",
            paper_id="failed-paper",
            content=b"failed source",
        ),
        paper_repository=repository,
        identity_repository=repository,
        source_snapshot_repository=repository,
        event_sink=_Events(),
    )

    with pytest.raises(ParsePaperError, match="structured parser failed"):
        use_case.parse(ParsePaperRequest(source="https://publisher.example/failed", run_id="failed-run"))

    assert any(event["to_status"] == "failed" for event in events)
