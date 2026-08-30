from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.research.domain import (
    ResearchPaperCatalogEntry,
    ResearchPaperIdentity,
    ResearchPaperRelation,
    ResearchSourceSnapshot,
    SourceLineage,
    build_paper_identity_fingerprint,
    metric_compatibility_key,
    same_paper_identity,
    validate_relation_for_publication,
)


def _lineage() -> SourceLineage:
    return SourceLineage(source_refs=["source://arxiv/1234"])


def test_source_snapshot_normalizes_url_and_requires_locator() -> None:
    snapshot = ResearchSourceSnapshot(
        snapshot_id="snap-1",
        paper_id="paper-1",
        source_type="arxiv",
        canonical_url="https://arxiv.org/abs/1234?utm_source=test",
        external_id="1234",
        content_type="application/pdf",
        fetched_at=datetime(2026, 8, 30, tzinfo=UTC),
        lineage=_lineage(),
    )

    assert snapshot.canonical_url == "https://arxiv.org/abs/1234"
    assert snapshot.fetched_at is not None and snapshot.fetched_at.tzinfo is UTC

    with pytest.raises(ValidationError, match="requires canonical_url"):
        ResearchSourceSnapshot(snapshot_id="snap-2", paper_id="paper-1", lineage=_lineage())


def test_identity_fingerprint_and_external_ids_are_deterministic() -> None:
    left = ResearchPaperIdentity(
        paper_id="paper-1",
        title="A Useful Paper",
        authors=["Bob", "Alice"],
        published_year=2026,
        arxiv_id="1234.5678",
    )
    right = ResearchPaperIdentity(
        paper_id="paper-2",
        title="Different title",
        arxiv_id="1234.5678",
    )

    assert left.fingerprint == build_paper_identity_fingerprint("A Useful Paper", ["Bob", "Alice"], 2026)
    assert same_paper_identity(left, right) is True


def test_relation_requires_matching_target_and_lineage() -> None:
    relation = ResearchPaperRelation(
        relation_id="rel-1",
        paper_id="paper-1",
        relation_type="paper_benchmark",
        target_type="benchmark",
        target_id="mmlu",
        source_snapshot_refs=["snap-1"],
        evidence_refs=["evidence-1"],
        status="candidate",
    )
    assert validate_relation_for_publication(relation).passed is False

    with pytest.raises(ValidationError, match="requires target_type=benchmark"):
        ResearchPaperRelation(
            relation_id="rel-2",
            paper_id="paper-1",
            relation_type="paper_benchmark",
            target_type="task",
            target_id="mmlu",
            source_snapshot_refs=["snap-1"],
            evidence_refs=["evidence-1"],
        )


def test_verified_relation_and_catalog_entry_preserve_typed_boundaries() -> None:
    identity = ResearchPaperIdentity(paper_id="paper-1", title="A Paper")
    relation = ResearchPaperRelation(
        relation_id="rel-1",
        paper_id="paper-1",
        relation_type="paper_code_repository",
        target_type="code_repository",
        target_id="org/repo",
        status="verified",
        confidence=1.0,
        source_snapshot_refs=["snap-1"],
        evidence_refs=["evidence-1"],
    )
    entry = ResearchPaperCatalogEntry(
        entry_id="entry-1",
        paper_id="paper-1",
        identity=identity,
        relations=[relation, relation],
        source_snapshot_refs=["snap-1", "snap-1"],
        status="catalog_ready",
    )

    assert len(entry.relations) == 1
    assert entry.source_snapshot_refs == ["snap-1"]
    assert validate_relation_for_publication(relation).passed is True


def test_metric_compatibility_key_normalizes_comparison_dimensions() -> None:
    key = metric_compatibility_key(
        dataset_id=" MMLU ",
        dataset_version="v1",
        metric_id="Accuracy",
        metric_direction="higher_is_better",
        metric_unit=" % ",
        split=" Test ",
        evaluation_protocol=" zero-shot ",
    )
    assert key == ("mmlu", "v1", "accuracy", "higher_is_better", "%", "test", "zero-shot")
