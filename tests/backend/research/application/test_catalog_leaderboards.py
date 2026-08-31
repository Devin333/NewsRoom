from __future__ import annotations

from datetime import UTC, datetime

from backend.research.application.catalog import (
    InMemoryResearchCatalogRepository,
    ResearchPaperCatalogService,
)
from backend.research.application.catalog import CatalogLeaderboardResult
from backend.research.benchmark import ResearchScore
from backend.research.benchmark import ResearchBenchmark, ResearchDataset, ResearchMetric, ResearchSOTAClaim
from backend.research.domain.code_repository import CodeRepositoryProfile
from backend.research.domain import ResearchPaper, ResearchPaperIdentity, ResearchSourceSnapshot, SourceLineage


def _service() -> ResearchPaperCatalogService:
    repository = InMemoryResearchCatalogRepository()
    return ResearchPaperCatalogService(catalog_repository=repository)


def _score(
    score_id: str,
    value: float,
    *,
    direction: str = "higher_is_better",
    dataset_version: str = "v1",
    split: str = "test",
    protocol: str = "zero-shot",
    status: str = "verified",
) -> ResearchScore:
    return ResearchScore(
        score_id=score_id,
        paper_id=f"paper-{score_id}",
        benchmark_id="benchmark-1",
        dataset_id="dataset-1",
        metric_id="metric-1",
        value=value,
        source_refs=[f"source://{score_id}"],
        evidence_refs=[f"evidence://{score_id}"],
        verification_status=status,
        direction=direction,
        split=split,
        unit="%",
        evaluation_protocol=protocol,
        metadata={"dataset_version": dataset_version},
    )


def test_compare_scores_excludes_non_verified_and_sorts_higher_direction() -> None:
    result = _service().compare_scores(
        [
            _score("score-b", 90.0),
            _score("score-a", 90.0),
            _score("score-candidate", 99.0, status="candidate"),
        ]
    )

    assert [row["scoreId"] for row in result.rows] == ["score-a", "score-b"]
    assert result.groups[0]["rows"] == result.rows
    assert result.excluded_scores == [{"scoreId": "score-candidate", "reason": "status:candidate"}]


def test_compare_scores_sorts_lower_direction_and_separates_incompatible_groups() -> None:
    result = _service().compare_scores(
        [
            _score("low-b", 0.2, direction="lower_is_better"),
            _score("low-a", 0.1, direction="lower_is_better"),
            _score("other-version", 0.05, direction="lower_is_better", dataset_version="v2"),
        ]
    )

    assert len(result.groups) == 2
    assert result.rows == []
    first, second = result.groups
    assert first["compatibilityKey"]["datasetVersion"] == "v1"
    assert [row["scoreId"] for row in first["rows"]] == ["low-a", "low-b"]
    assert second["compatibilityKey"]["datasetVersion"] == "v2"
    assert [row["scoreId"] for row in second["rows"]] == ["other-version"]


def test_leaderboard_result_uses_independent_excluded_score_lists() -> None:
    left = CatalogLeaderboardResult(rows=[], observed_at=datetime.now(UTC))
    right = CatalogLeaderboardResult(rows=[], observed_at=datetime.now(UTC))

    left.excluded_scores.append({"scoreId": "left"})

    assert right.excluded_scores == []


def test_verify_score_requires_complete_protocol_and_typed_definitions() -> None:
    service = _service()
    score = _score("incomplete", 90.0, status="candidate").model_copy(
        update={"split": None, "evaluation_protocol": None, "dataset_version": None}
    )
    verified = service.verify_score(score)

    assert verified.verification_status == "rejected"
    assert "benchmark_definition_missing" in verified.metadata["verification_reasons"]
    assert "split_missing" in verified.metadata["verification_reasons"]


def test_verify_score_promotes_only_protocol_compatible_score() -> None:
    service = _service()
    benchmark = ResearchBenchmark(
        benchmark_id="benchmark-1",
        name="Benchmark",
        task="task",
        dataset_ids=["dataset-1"],
    )
    dataset = ResearchDataset(dataset_id="dataset-1", name="Dataset", version="v1")
    metric = ResearchMetric(metric_id="metric-1", name="Metric", direction="higher_is_better", unit="%")
    score = _score("complete", 90.0, status="candidate")

    verified = service.verify_score(
        score,
        benchmark=benchmark,
        dataset=dataset,
        metric=metric,
        expected_protocol="zero-shot",
    )

    assert verified.verification_status == "verified"
    assert verified.dataset_version == "v1"


def test_catalog_persists_typed_code_profile_with_paper_scope() -> None:
    repository = InMemoryResearchCatalogRepository()
    profile = CodeRepositoryProfile(
        repo_url="https://github.com/example/research",
        owner="example",
        name="research",
        metadata={"paper_id": "paper-code", "actor_scope": {"tenant_id": "tenant-a"}},
    )
    repository.save_code_profile(profile)

    values = repository.list_code_profiles("paper-code", actor_scope={"tenant_id": "tenant-a"})

    assert values and values[0].repo_url.endswith("/example/research")


def test_catalog_code_relation_uses_canonical_repository_id_and_url_ref() -> None:
    repository = InMemoryResearchCatalogRepository()
    service = ResearchPaperCatalogService(catalog_repository=repository)
    paper = ResearchPaper(
        paper_id="paper-code-relation",
        title="Code relation paper",
        metadata={
            "code_urls": ["https://github.com/example/research"],
            "code_profile": {
                "repo_url": "https://github.com/example/research",
                "canonical_repo_id": "github:example/research",
                "owner": "example",
                "name": "research",
                "observations": [],
            },
        },
    )
    snapshot = ResearchSourceSnapshot(
        snapshot_id="snapshot-code-relation",
        paper_id=paper.paper_id,
        source_type="publisher",
        canonical_url="https://example.test/paper",
        lineage=SourceLineage(source_refs=["https://example.test/paper"]),
    )

    entry = service.refresh_from_parse(
        paper=paper,
        identity=ResearchPaperIdentity(paper_id=paper.paper_id, title=paper.title),
        snapshot=snapshot,
        document=None,
        evidence_pack=None,
        actor_scope={"tenant_id": "tenant-a"},
    )

    relations = [
        relation
        for relation in entry.relations
        if relation.relation_type == "paper_code_repository"
    ]
    assert len(relations) == 1
    assert relations[0].target_id == "github:example/research"
    assert relations[0].target_ref == "https://github.com/example/research"
    assert relations[0].metadata["canonical_repo_id"] == "github:example/research"


def test_catalog_include_code_false_skips_github_enrichment() -> None:
    class RecordingGithub:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch_profile(self, url: str) -> CodeRepositoryProfile:
            self.calls.append(url)
            return CodeRepositoryProfile(
                repo_url=url,
                canonical_repo_id="github:example/research",
                owner="example",
                name="research",
            )

    github = RecordingGithub()
    repository = InMemoryResearchCatalogRepository()
    service = ResearchPaperCatalogService(
        catalog_repository=repository,
        github_repository=github,
    )
    paper = ResearchPaper(
        paper_id="paper-no-code-enrichment",
        title="No code enrichment",
        metadata={"code_urls": ["https://github.com/example/research"]},
    )
    snapshot = ResearchSourceSnapshot(
        snapshot_id="snapshot-no-code-enrichment",
        paper_id=paper.paper_id,
        canonical_url="https://example.test/paper",
        lineage=SourceLineage(source_refs=["https://example.test/paper"]),
    )

    entry = service.refresh_from_parse(
        paper=paper,
        identity=ResearchPaperIdentity(paper_id=paper.paper_id, title=paper.title),
        snapshot=snapshot,
        document=None,
        evidence_pack=None,
        actor_scope={"tenant_id": "tenant-a"},
        include_code=False,
    )

    assert github.calls == []
    assert entry.metadata["diagnostics"] == [
        {"code": "github_enrichment_skipped", "reason": "include_code_false"}
    ]
    assert repository.list_code_profiles(
        paper.paper_id,
        actor_scope={"tenant_id": "tenant-a"},
    ) == []


def test_sota_verification_persists_and_rejects_scope_widening() -> None:
    repository = InMemoryResearchCatalogRepository()
    service = ResearchPaperCatalogService(catalog_repository=repository)
    scope = {"tenant_id": "tenant-a", "user_id": "user-a"}
    benchmark = ResearchBenchmark(
        benchmark_id="benchmark-1",
        name="Benchmark",
        task="task",
        dataset_ids=["dataset-1"],
        metadata={"actor_scope": scope},
    )
    dataset = ResearchDataset(
        dataset_id="dataset-1",
        name="Dataset",
        version="v1",
        metadata={"actor_scope": scope},
    )
    metric = ResearchMetric(
        metric_id="metric-1",
        name="Metric",
        direction="higher_is_better",
        unit="%",
        metadata={"actor_scope": scope},
    )
    score = _score("sota-score", 99.0).model_copy(update={
        "paper_id": "paper-sota",
        "actor_scope": scope,
        "metadata": {"dataset_version": "v1", "actor_scope": scope},
    })
    claim = ResearchSOTAClaim(
        claim_id="claim-sota",
        paper_id="paper-sota",
        benchmark_id="benchmark-1",
        dataset_id="dataset-1",
        metric_id="metric-1",
        score_id="sota-score",
        claim_text="SOTA on the benchmark",
        source_refs=["paper://sota/table-1"],
        source_snapshot_refs=["snapshot-sota"],
        evidence_refs=["evidence://sota"],
        dataset_version="v1",
        split="test",
        unit="%",
        direction="higher_is_better",
        evaluation_protocol="zero-shot",
        actor_scope=scope,
    )
    verified = service.verify_score(score, benchmark=benchmark, dataset=dataset, metric=metric)
    assert verified.verification_status == "verified"
    promoted = service.verify_sota_claim(
        claim,
        score=verified,
        benchmark=benchmark,
        dataset=dataset,
        metric=metric,
    )
    assert promoted.verification_status == "verified"
    assert repository.list_sota_claims("paper-sota", actor_scope=scope)[0].verification_status == "verified"

    unscoped_claim = claim.model_copy(update={"actor_scope": {}, "metadata": {}})
    rejected = service.verify_sota_claim(
        unscoped_claim,
        score=verified,
        benchmark=benchmark,
        dataset=dataset,
        metric=metric,
    )
    assert rejected.verification_status == "conflicting"
    assert "actor_scope_mismatch" in rejected.metadata["verification_reasons"]


def test_sota_verification_rejects_score_from_another_paper() -> None:
    repository = InMemoryResearchCatalogRepository()
    service = ResearchPaperCatalogService(catalog_repository=repository)
    score = _score("cross-paper", 99.0)
    claim = ResearchSOTAClaim(
        claim_id="cross-paper-claim",
        paper_id="paper-a",
        benchmark_id=score.benchmark_id,
        dataset_id=score.dataset_id,
        metric_id=score.metric_id,
        score_id=score.score_id,
        claim_text="SOTA claim",
        source_refs=["paper://paper-a/table"],
        evidence_refs=["evidence://paper-a/table"],
        dataset_version="v1",
        split="test",
        unit="%",
        direction="higher_is_better",
        evaluation_protocol="zero-shot",
    )

    promoted = service.verify_sota_claim(claim, score=score)

    assert promoted.verification_status == "conflicting"
    assert "paper_link_mismatch" in promoted.metadata["verification_reasons"]


def test_catalog_keeps_evidence_missing_score_as_candidate_relation() -> None:
    repository = InMemoryResearchCatalogRepository()
    service = ResearchPaperCatalogService(catalog_repository=repository)
    paper = ResearchPaper(
        paper_id="paper-candidate-score",
        title="Candidate score paper",
        metadata={
            "scores": [{
                "benchmark_id": "benchmark-1",
                "dataset_id": "dataset-1",
                "metric_id": "metric-1",
                "value": 42.0,
            }],
        },
    )
    snapshot = ResearchSourceSnapshot(
        snapshot_id="snapshot-candidate-score",
        paper_id=paper.paper_id,
        canonical_url="https://example.test/paper",
        lineage=SourceLineage(source_refs=["https://example.test/paper"]),
    )

    entry = service.refresh_from_parse(
        paper=paper,
        identity=ResearchPaperIdentity(
            paper_id=paper.paper_id,
            title=paper.title,
            authors=paper.authors,
        ),
        snapshot=snapshot,
        document=None,
        evidence_pack=None,
        actor_scope={"tenant_id": "tenant-a", "user_id": "user-a"},
    )

    relations = [relation for relation in entry.relations if relation.relation_type == "paper_score"]
    assert len(relations) == 1
    assert relations[0].status == "candidate"
    assert relations[0].evidence_refs == []
    assert relations[0].metadata["evidence_missing"] is True


def test_catalog_preserves_unresolved_text_sota_claim_as_candidate() -> None:
    repository = InMemoryResearchCatalogRepository()
    service = ResearchPaperCatalogService(catalog_repository=repository)
    paper = ResearchPaper(
        paper_id="paper-unresolved-sota",
        title="Unresolved SOTA paper",
        metadata={"sota_claims": [{"claim_text": "We achieve state of the art."}]},
    )
    snapshot = ResearchSourceSnapshot(
        snapshot_id="snapshot-unresolved-sota",
        paper_id=paper.paper_id,
        canonical_url="https://example.test/paper",
        lineage=SourceLineage(source_refs=["https://example.test/paper"]),
    )
    identity = ResearchPaperIdentity(
        paper_id=paper.paper_id,
        title=paper.title,
    )

    service.refresh_from_parse(
        paper=paper,
        identity=identity,
        snapshot=snapshot,
        document=None,
        evidence_pack=None,
        actor_scope={"tenant_id": "tenant-a"},
    )

    claims = repository.list_sota_claims(
        paper.paper_id,
        actor_scope={"tenant_id": "tenant-a"},
    )
    assert len(claims) == 1
    assert claims[0].verification_status == "candidate"
    assert claims[0].metadata["unresolved_fields"] == [
        "benchmark_id",
        "dataset_id",
        "metric_id",
    ]
