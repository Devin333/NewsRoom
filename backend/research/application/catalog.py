from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Iterable, Mapping

from pydantic import Field

from backend.foundation import PrimitiveModel, normalize_key
from backend.research.domain.catalog import (
    ResearchPaperCatalogEntry,
    ResearchPaperIdentity,
    ResearchPaperRelation,
    ResearchSourceSnapshot,
    actor_scope_matches,
    actor_scope_ref,
    metric_compatibility_key,
)
from backend.research.domain.common import stable_research_id
from backend.research.domain.code_repository import CodeRepositoryProfile
from backend.research.code_repository.ports import GithubRepositoryPort
from backend.research.domain.document import ResearchDocument
from backend.research.domain.evidence import ResearchEvidencePack
from backend.research.domain.paper import ResearchPaper
from backend.research.benchmark.models import (
    ResearchBenchmark,
    ResearchDataset,
    ResearchMetric,
    ResearchSOTAClaim,
    ResearchScore,
)
from backend.research.ports.catalog import (
    ResearchCodeRepositoryProfileRepository,
    ResearchPaperCatalogRepository,
    ResearchPaperIdentityRepository,
    ResearchPaperRelationRepository,
    ResearchSourceSnapshotRepository,
    ResearchSOTAClaimRepository,
)
from backend.research.ports.paper_ingest import (
    ResearchDocumentRepository,
    ResearchEvidencePackRepository,
    ResearchPaperReadRepository,
)


class CatalogError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})


class CatalogLeaderboardResult(PrimitiveModel):
    benchmark_id: str | None = None
    metric_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    split: str | None = None
    evaluation_protocol: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    groups: list[dict[str, Any]] = Field(default_factory=list)
    included_scores: list[dict[str, Any]] = Field(default_factory=list)
    excluded_scores: list[dict[str, Any]] = Field(default_factory=list)


class ResearchPaperCatalogService:
    """Application facade for typed paper Catalog and deterministic gates."""

    def __init__(
        self,
        *,
        catalog_repository: ResearchPaperCatalogRepository,
        identity_repository: ResearchPaperIdentityRepository | None = None,
        relation_repository: ResearchPaperRelationRepository | None = None,
        source_snapshot_repository: ResearchSourceSnapshotRepository | None = None,
        paper_repository: ResearchPaperReadRepository | None = None,
        document_repository: ResearchDocumentRepository | None = None,
        evidence_repository: ResearchEvidencePackRepository | None = None,
        code_profile_repository: ResearchCodeRepositoryProfileRepository | None = None,
        sota_claim_repository: ResearchSOTAClaimRepository | None = None,
        github_repository: GithubRepositoryPort | None = None,
    ) -> None:
        self._catalog = catalog_repository
        self._identity = identity_repository
        self._relations = relation_repository
        self._snapshots = source_snapshot_repository
        self._papers = paper_repository
        self._documents = document_repository
        self._evidence = evidence_repository
        self._code_profiles = code_profile_repository or (
            catalog_repository
            if isinstance(catalog_repository, ResearchCodeRepositoryProfileRepository)
            else None
        )
        self._github = github_repository
        self._sota_claims = sota_claim_repository or (
            catalog_repository
            if isinstance(catalog_repository, ResearchSOTAClaimRepository)
            else None
        )

    def refresh_from_parse(
        self,
        *,
        paper: ResearchPaper,
        identity: ResearchPaperIdentity,
        snapshot: ResearchSourceSnapshot,
        document: ResearchDocument | None,
        evidence_pack: ResearchEvidencePack | None,
        actor_scope: Mapping[str, str],
        run_id: str | None = None,
        include_code: bool = True,
        catalog_eligible: bool = True,
    ) -> ResearchPaperCatalogEntry:
        scope = dict(actor_scope)
        existing = _scoped_call(self._catalog.get, paper.paper_id, actor_scope=scope)
        paper, code_diagnostics = (
            self._enrich_code_profiles(paper, actor_scope=scope)
            if include_code
            else (paper, [{"code": "github_enrichment_skipped", "reason": "include_code_false"}])
        )
        evidence_refs = evidence_pack.evidence_ids if evidence_pack is not None else []
        self._persist_code_profiles(paper, actor_scope=scope)
        score_candidates = self._candidate_scores(
            paper=paper,
            snapshot=snapshot,
            evidence_refs=evidence_refs,
            document=document,
            actor_scope=scope,
        )
        for score in score_candidates:
            self._save_score(score)
        sota_candidates = self._candidate_sota_claims(
            paper=paper,
            snapshot=snapshot,
            evidence_refs=evidence_refs,
            document=document,
            score_candidates=score_candidates,
            actor_scope=scope,
        )
        for claim in sota_candidates:
            self._save_sota_claim(claim)
        generated = self._candidate_relations(
            paper=paper,
            snapshot=snapshot,
            evidence_refs=evidence_refs,
            document=document,
            score_candidates=score_candidates,
            actor_scope=scope,
        )
        relations = _merge_relations(existing.relations if existing is not None else [], generated)
        now = datetime.now(UTC)
        entry = ResearchPaperCatalogEntry(
            entry_id=(existing.entry_id if existing is not None else stable_research_id("research_catalog_entry", paper.paper_id)),
            paper_id=paper.paper_id,
            identity=identity,
            relations=relations,
            status=("catalog_ready" if catalog_eligible and relations and all(item.status == "verified" for item in relations) else "catalog_partial"),
            source_snapshot_refs=_unique([*(existing.source_snapshot_refs if existing is not None else []), snapshot.snapshot_id]),
            identity_ref=f"identity://{identity.paper_id}",
            relation_refs=[relation.relation_id for relation in relations],
            evidence_coverage={
                "relations": (
                    sum(bool(relation.evidence_refs) for relation in relations) / len(relations)
                    if relations
                    else 0.0
                ),
                "source_snapshots": 1.0,
            },
            created_at=(existing.created_at if existing is not None else now),
            updated_at=now,
            observed_at=now,
            last_refresh_run_id=(run_id or snapshot.metadata.get("run_id") or (existing.last_refresh_run_id if existing is not None else None)),
            actor_scope=scope,
            metadata={
                **(dict(existing.metadata) if existing is not None else {}),
                "actor_scope": scope,
                "relation_count": len(relations),
                "candidate_count": sum(item.status == "candidate" for item in relations),
                "diagnostics": code_diagnostics,
                "sota_claim_refs": [claim.claim_id for claim in sota_candidates],
                "quality_gate": {
                    "catalog_eligible": bool(catalog_eligible),
                    "status": "passed" if catalog_eligible else "failed",
                },
            },
        )
        self._catalog.save(entry)
        if self._identity is not None:
            self._identity.save(identity)
        if self._relations is not None:
            for relation in relations:
                self._relations.save(relation)
        return entry

    def get_catalog(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchPaperCatalogEntry:
        entry = _scoped_call(
            self._catalog.get,
            _required_id(paper_id, "paper_id"),
            actor_scope=dict(actor_scope or {}),
        )
        if entry is None:
            raise CatalogError("catalog_not_found", f"catalog not found for paper {paper_id}", status_code=404)
        if not actor_scope_matches(entry.metadata.get("actor_scope"), actor_scope):
            raise CatalogError("catalog_not_found", f"catalog not found for paper {paper_id}", status_code=404)
        return entry

    def search_papers(
        self,
        query: str = "",
        *,
        limit: int = 50,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchPaperCatalogEntry]:
        if isinstance(limit, bool) or int(limit) < 1 or int(limit) > 200:
            raise CatalogError("invalid_limit", "limit must be between 1 and 200", status_code=400)
        values = _scoped_call(
            self._catalog.search,
            str(query or "").strip(),
            limit=int(limit),
            actor_scope=dict(actor_scope or {}),
        )
        return [
            entry
            for entry in values
            if actor_scope_matches(entry.metadata.get("actor_scope"), actor_scope)
        ]

    def list_sources(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchSourceSnapshot]:
        if self._snapshots is None:
            return []
        values = _scoped_call(
            self._snapshots.list_for_paper,
            _required_id(paper_id, "paper_id"),
            actor_scope=dict(actor_scope or {}),
        )
        return [
            snapshot
            for snapshot in values
            if actor_scope_matches(
                {**snapshot.metadata, **dict(snapshot.lineage.metadata)},
                actor_scope,
            )
        ]

    def get_document(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchDocument | None:
        if self._documents is None:
            return None
        document = _scoped_call(
            self._documents.get,
            _required_id(paper_id, "paper_id"),
            actor_scope=dict(actor_scope or {}),
        )
        if document is None:
            return None
        return document if actor_scope_matches(document.lineage.metadata, actor_scope) else None

    def get_code(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        entry = self.get_catalog(paper_id, actor_scope=actor_scope)
        profiles: list[dict[str, Any]] = []
        if self._code_profiles is not None:
            values = _scoped_call(
                self._code_profiles.list_code_profiles,
                paper_id,
                actor_scope=dict(actor_scope or {}),
            )
            profiles.extend(
                profile.model_dump(mode="json", exclude_none=True)
                for profile in values
                if isinstance(profile, CodeRepositoryProfile)
                and actor_scope_matches(profile.metadata.get("actor_scope"), actor_scope)
            )
        for relation in entry.relations:
            if relation.target_type != "code_repository":
                continue
            profile = relation.metadata.get("profile")
            if isinstance(profile, Mapping):
                profile_payload = dict(profile)
                if not any(
                    str(existing.get("repo_url") or existing.get("repoUrl") or "").casefold()
                    == str(profile_payload.get("repo_url") or profile_payload.get("repoUrl") or "").casefold()
                    for existing in profiles
                ):
                    profiles.append(profile_payload)
            elif not any(str(existing.get("canonical_repo_id") or existing.get("repositoryId") or "") == relation.target_id for existing in profiles):
                profiles.append({"repositoryId": relation.target_id, "status": relation.status})
        return profiles

    def get_benchmarks(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
        benchmark_id: str | None = None,
        metric_id: str | None = None,
        dataset_id: str | None = None,
        dataset_version: str | None = None,
        split: str | None = None,
        evaluation_protocol: str | None = None,
    ) -> dict[str, Any]:
        entry = self.get_catalog(paper_id, actor_scope=actor_scope)
        relations = [relation.model_dump(mode="json", exclude_none=True) for relation in entry.relations if relation.target_type in {"benchmark", "dataset", "metric", "score"}]
        scores = self._scores_for_paper(paper_id, actor_scope=actor_scope)
        if benchmark_id:
            scores = [score for score in scores if score.benchmark_id == benchmark_id]
        if metric_id:
            scores = [score for score in scores if score.metric_id == metric_id]
        if dataset_id:
            scores = [score for score in scores if normalize_key(score.dataset_id) == normalize_key(dataset_id)]
        if dataset_version:
            scores = [score for score in scores if normalize_key(str(score.dataset_version or score.metadata.get("dataset_version") or "")) == normalize_key(dataset_version)]
        if split:
            scores = [score for score in scores if normalize_key(str(score.split or "")) == normalize_key(split)]
        if evaluation_protocol:
            scores = [score for score in scores if normalize_key(str(score.evaluation_protocol or "")) == normalize_key(evaluation_protocol)]
        claims = self.get_sota_claims(paper_id, actor_scope=actor_scope)
        return {
            "paperId": paper_id,
            "relations": relations,
            "scores": [score.model_dump(mode="json", exclude_none=True) for score in scores],
            "sotaClaims": claims,
        }

    def get_sota_claims(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if self._sota_claims is None:
            return []
        getter = getattr(self._sota_claims, "list_sota_claims", None)
        if not callable(getter):
            return []
        values = _scoped_call(
            getter,
            _required_id(paper_id, "paper_id"),
            actor_scope=dict(actor_scope or {}),
        )
        return [
            claim.model_dump(mode="json", exclude_none=True)
            for claim in values
            if isinstance(claim, ResearchSOTAClaim)
            and _value_scope_matches(claim, actor_scope)
        ]

    def upsert_relation(self, relation: ResearchPaperRelation) -> ResearchPaperRelation:
        if relation.status == "verified" and (not relation.source_snapshot_refs or not relation.evidence_refs):
            raise CatalogError("relation_evidence_required", "verified relation requires source and evidence refs")
        if self._relations is not None:
            self._relations.save(relation)
        entry = _scoped_call(
            self._catalog.get,
            relation.paper_id,
            actor_scope=_relation_scope(relation),
        )
        if entry is not None:
            self._catalog.save(entry.model_copy(update={"relations": _merge_relations(entry.relations, [relation]), "updated_at": datetime.now(UTC)}))
        return relation

    def verify_score(
        self,
        score: ResearchScore,
        *,
        benchmark: ResearchBenchmark | None = None,
        dataset: ResearchDataset | None = None,
        metric: ResearchMetric | None = None,
        expected_protocol: str | None = None,
    ) -> ResearchScore:
        reasons: list[str] = []
        if not score.source_refs:
            reasons.append("source_refs_missing")
        if not score.source_snapshot_refs:
            reasons.append("source_snapshot_refs_missing")
        if not score.evidence_refs:
            reasons.append("evidence_refs_missing")
        if benchmark is None:
            reasons.append("benchmark_definition_missing")
        elif normalize_key(score.benchmark_id) != normalize_key(benchmark.benchmark_id):
            reasons.append("benchmark_mismatch")
        if dataset is None:
            reasons.append("dataset_definition_missing")
        else:
            if normalize_key(score.dataset_id) != normalize_key(dataset.dataset_id):
                reasons.append("dataset_mismatch")
            elif benchmark is not None and benchmark.dataset_ids and normalize_key(score.dataset_id) not in {
                normalize_key(value) for value in benchmark.dataset_ids
            }:
                reasons.append("benchmark_dataset_mismatch")
            score_version = score.dataset_version or score.metadata.get("dataset_version")
            if not score_version or not dataset.version:
                reasons.append("dataset_version_missing")
            elif normalize_key(str(score_version)) != normalize_key(str(dataset.version)):
                reasons.append("dataset_version_mismatch")
        if metric is None:
            reasons.append("metric_definition_missing")
        else:
            if normalize_key(score.metric_id) != normalize_key(metric.metric_id):
                reasons.append("metric_mismatch")
            if not score.direction:
                reasons.append("metric_direction_missing")
            elif score.direction != metric.direction:
                reasons.append("metric_direction_mismatch")
            if not score.unit:
                reasons.append("metric_unit_missing")
            elif metric.unit and score.unit != metric.unit:
                reasons.append("metric_unit_mismatch")
        if not score.split:
            reasons.append("split_missing")
        if not score.evaluation_protocol:
            reasons.append("evaluation_protocol_missing")
        elif expected_protocol is not None and score.evaluation_protocol != expected_protocol:
            reasons.append("evaluation_protocol_mismatch")
        if score.metadata.get("protocol_contract_required"):
            for field_name in score.metadata.get("protocol_unknown_fields", []):
                reasons.append(f"protocol_{field_name}_missing")
        status = "verified" if not reasons else ("conflicting" if any("mismatch" in reason for reason in reasons) else "rejected")
        update = {
            "verification_status": status,
            "status": status,
            "direction": score.direction or (metric.direction if metric is not None else None),
            "unit": score.unit or (metric.unit if metric is not None else None),
            "metadata": {**dict(score.metadata), "verification_reasons": reasons},
        }
        updated = ResearchScore.model_validate({**score.model_dump(mode="python"), **update})
        self._save_score(updated)
        return updated

    def compare_scores(
        self,
        scores: Iterable[ResearchScore],
        *,
        benchmark_id: str | None = None,
        metric_id: str | None = None,
        dataset_id: str | None = None,
        dataset_version: str | None = None,
        split: str | None = None,
        evaluation_protocol: str | None = None,
    ) -> CatalogLeaderboardResult:
        excluded: list[dict[str, Any]] = []
        groups: dict[tuple[str, ...], list[ResearchScore]] = {}
        for score in scores:
            filter_reason = _score_filter_reason(
                score,
                benchmark_id=benchmark_id,
                metric_id=metric_id,
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                split=split,
                evaluation_protocol=evaluation_protocol,
            )
            if filter_reason is not None:
                excluded.append({"scoreId": score.score_id, "reason": filter_reason})
                continue
            if score.verification_status != "verified":
                excluded.append({"scoreId": score.score_id, "reason": f"status:{score.verification_status}"})
                continue
            missing = _verified_score_missing_reason(score)
            if missing is not None:
                excluded.append({"scoreId": score.score_id, "reason": missing})
                continue
            key = metric_compatibility_key(
                dataset_id=score.dataset_id,
                dataset_version=score.dataset_version or score.metadata.get("dataset_version"),
                metric_id=score.metric_id,
                metric_direction=score.direction or "higher_is_better",
                metric_unit=score.unit,
                split=score.split,
                evaluation_protocol=score.evaluation_protocol,
                protocol_fingerprint=score.protocol_fingerprint,
            )
            groups.setdefault(key, []).append(score)
        group_payloads: list[dict[str, Any]] = []
        for key, group in sorted(groups.items(), key=lambda item: item[0]):
            direction = group[0].direction or "higher_is_better"
            compatibility = _compatibility_key_payload(key)
            group_rows = _sort_score_rows(
                [_score_row(score, compatibility) for score in group],
                direction=direction,
            )
            group_payloads.append({"compatibilityKey": compatibility, "rows": group_rows})
        # ``rows`` is retained for callers that consume a single leaderboard.
        # When dimensions are incompatible there is no valid single ranking;
        # callers must consume the explicitly separated ``groups`` instead.
        rows = group_payloads[0]["rows"] if len(group_payloads) == 1 else []
        included = [row for group in group_payloads for row in group["rows"]]
        return CatalogLeaderboardResult(
            benchmark_id=benchmark_id,
            metric_id=metric_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            split=split,
            evaluation_protocol=evaluation_protocol,
            rows=rows,
            groups=group_payloads,
            observed_at=datetime.now(UTC),
            included_scores=included,
            excluded_scores=excluded,
        )

    def list_leaderboards(
        self,
        scores: Iterable[ResearchScore],
        *,
        benchmark_id: str | None = None,
        metric_id: str | None = None,
        dataset_id: str | None = None,
        dataset_version: str | None = None,
        split: str | None = None,
        evaluation_protocol: str | None = None,
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, tuple[str, ...]], list[ResearchScore]] = {}
        for score in scores:
            if benchmark_id is not None and normalize_key(score.benchmark_id) != normalize_key(benchmark_id):
                continue
            if metric_id is not None and normalize_key(score.metric_id) != normalize_key(metric_id):
                continue
            if dataset_id is not None and normalize_key(score.dataset_id) != normalize_key(dataset_id):
                continue
            if dataset_version is not None and normalize_key(str(score.dataset_version or score.metadata.get("dataset_version") or "")) != normalize_key(dataset_version):
                continue
            if split is not None and normalize_key(str(score.split or "")) != normalize_key(split):
                continue
            if evaluation_protocol is not None and normalize_key(str(score.evaluation_protocol or "")) != normalize_key(evaluation_protocol):
                continue
            key = metric_compatibility_key(
                dataset_id=score.dataset_id,
                dataset_version=score.dataset_version or score.metadata.get("dataset_version"),
                metric_id=score.metric_id,
                metric_direction=score.direction or "higher_is_better",
                metric_unit=score.unit,
                split=score.split,
                evaluation_protocol=score.evaluation_protocol,
                protocol_fingerprint=score.protocol_fingerprint,
            )
            grouped.setdefault((score.benchmark_id, score.metric_id, key), []).append(score)
        leaderboards: list[dict[str, Any]] = []
        for key, group in sorted(grouped.items(), key=lambda item: item[0]):
            result = self.compare_scores(
                group,
                benchmark_id=key[0],
                metric_id=key[1],
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                split=split,
                evaluation_protocol=evaluation_protocol,
            )
            # A leaderboard is a published comparison surface. Candidate,
            # rejected, and conflicting-only groups remain in diagnostics on
            # score APIs but must not materialize as empty leaderboards.
            if not result.included_scores:
                continue
            leaderboards.append(result.model_dump(mode="json", exclude_none=True))
        return leaderboards

    def all_scores(self, *, actor_scope: Mapping[str, str] | None = None) -> list[ResearchScore]:
        getter = getattr(self._catalog, "list_all_scores", None)
        if not callable(getter):
            return []
        values = _scoped_call(getter, actor_scope=dict(actor_scope or {}))
        return [
            score
            for score in values
            if isinstance(score, ResearchScore)
            and actor_scope_matches(score.metadata.get("actor_scope"), actor_scope)
        ]

    def _candidate_relations(
        self,
        *,
        paper: ResearchPaper,
        snapshot: ResearchSourceSnapshot,
        evidence_refs: list[str],
        document: ResearchDocument | None,
        score_candidates: list[ResearchScore] | None = None,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchPaperRelation]:
        metadata = dict(paper.metadata)
        candidates: list[tuple[str, str, str]] = []
        code_profiles_by_url: dict[str, Mapping[str, Any]] = {}
        for profile_key in ("code_profile", "code_repository_profile"):
            profile = metadata.get(profile_key)
            if isinstance(profile, Mapping):
                profile_url = profile.get("repo_url") or profile.get("repository_url")
                if profile_url:
                    code_profiles_by_url[normalize_key(str(profile_url))] = profile
        raw_profiles = metadata.get("code_profiles")
        if isinstance(raw_profiles, (list, tuple)):
            for profile in raw_profiles:
                if not isinstance(profile, Mapping):
                    continue
                profile_url = profile.get("repo_url") or profile.get("repository_url")
                if profile_url:
                    code_profiles_by_url[normalize_key(str(profile_url))] = profile
        for key, relation_type, target_type in (
            ("tasks", "paper_task", "task"),
            ("methods", "paper_method", "method"),
            ("dataset_ids", "paper_dataset", "dataset"),
            ("benchmark_ids", "paper_benchmark", "benchmark"),
            ("metric_ids", "paper_metric", "metric"),
        ):
            for target_id in _text_list(metadata.get(key)):
                candidates.append((relation_type, target_type, target_id))
        code_urls = _text_list(metadata.get("code_urls"))
        if paper.code_url:
            code_urls.append(paper.code_url)
        for url in _unique(code_urls):
            candidates.append(("paper_code_repository", "code_repository", normalize_key(url)))
        if document is not None and document.sections:
            # A document itself is evidence for a text-derived candidate; no
            # LLM routing is involved here.
            for key, relation_type, target_type in (("tasks", "paper_task", "task"), ("methods", "paper_method", "method")):
                if key not in metadata:
                    text = " ".join(section.text for section in document.sections[:3])
                    for token in _metadata_tokens(text, key):
                        candidates.append((relation_type, target_type, token))
        relations: list[ResearchPaperRelation] = []
        for relation_type, target_type, target_id in candidates:
            original_target_id = target_id
            relation_evidence_refs = list(evidence_refs)
            relation_metadata: dict[str, Any] = {"actor_scope": dict(actor_scope or {})}
            if not relation_evidence_refs:
                # A source locator proves where an observation came from, but
                # is not itself a claim/evidence ref. Keep the candidate
                # queryable and make the missing evidence explicit.
                relation_metadata["evidence_missing"] = True
            if target_type == "code_repository":
                profile = code_profiles_by_url.get(normalize_key(original_target_id))
                if isinstance(profile, Mapping):
                    repository_url = profile.get("repo_url") or profile.get("repository_url")
                    canonical_repo_id = profile.get("canonical_repo_id")
                    if repository_url:
                        relation_metadata["repository_url"] = str(repository_url)
                    if canonical_repo_id:
                        target_id = str(canonical_repo_id)
                        relation_metadata["canonical_repo_id"] = target_id
                    relation_metadata["profile"] = dict(profile)
                    profile_snapshot_refs = _text_values(
                        profile.get("source_snapshot_refs") or profile.get("sourceSnapshotRefs")
                    )
                    if profile_snapshot_refs:
                        relation_metadata["code_source_snapshot_refs"] = profile_snapshot_refs
            relations.append(ResearchPaperRelation(
                relation_id=stable_research_id("paper_relation", paper.paper_id, relation_type, target_id),
                paper_id=paper.paper_id,
                relation_type=relation_type,
                target_type=target_type,
                target_id=target_id,
                target_ref=(
                    str(relation_metadata.get("repository_url"))
                    if target_type == "code_repository" and relation_metadata.get("repository_url")
                    else original_target_id
                ),
                status="candidate",
                confidence=0.5,
                source_snapshot_refs=_unique([
                    snapshot.snapshot_id,
                    *(_text_values(relation_metadata.get("code_source_snapshot_refs")) if target_type == "code_repository" else []),
                ]),
                evidence_refs=relation_evidence_refs,
                observed_at=datetime.now(UTC),
                metadata=relation_metadata,
            ))
        for score in score_candidates or []:
            relation_evidence = _unique([*evidence_refs, *score.evidence_refs])
            relation_metadata: dict[str, Any] = {"actor_scope": dict(actor_scope or {})}
            if not relation_evidence:
                # Keep an auditable candidate relation even when the score
                # lacks evidence. Publication gates, not relation creation,
                # decide whether it can become verified or reach a leaderboard.
                relation_metadata["evidence_missing"] = True
            relations.append(ResearchPaperRelation(
                relation_id=stable_research_id("paper_relation", paper.paper_id, "paper_score", score.score_id),
                paper_id=paper.paper_id,
                relation_type="paper_score",
                target_type="score",
                target_id=score.score_id,
                status="candidate",
                confidence=0.6,
                source_snapshot_refs=[snapshot.snapshot_id],
                evidence_refs=relation_evidence,
                observed_at=datetime.now(UTC),
                metadata=relation_metadata,
            ))
        return relations

    def _persist_code_profiles(
        self,
        paper: ResearchPaper,
        *,
        actor_scope: Mapping[str, str],
    ) -> None:
        if self._code_profiles is None:
            return
        raw_profiles: list[Mapping[str, Any]] = []
        for key in ("code_profile", "code_repository_profile"):
            raw = paper.metadata.get(key)
            if isinstance(raw, Mapping):
                raw_profiles.append(raw)
        raw_collection = paper.metadata.get("code_profiles")
        if isinstance(raw_collection, (list, tuple)):
            raw_profiles.extend(item for item in raw_collection if isinstance(item, Mapping))
        for raw in raw_profiles:
            try:
                profile = CodeRepositoryProfile.model_validate(raw)
            except Exception:
                continue
            profile = profile.model_copy(update={
                "actor_scope": dict(actor_scope),
                "observations": [
                    observation.model_copy(update={"actor_scope": dict(actor_scope)})
                    for observation in profile.observations
                ],
                "metadata": {
                    **dict(profile.metadata),
                    "paper_id": paper.paper_id,
                    "actor_scope": dict(actor_scope),
                },
            })
            saver = getattr(self._code_profiles, "save_code_profile", None)
            if callable(saver):
                saver(profile)
            else:
                self._code_profiles.save(profile)  # type: ignore[attr-defined]

    def _enrich_code_profiles(
        self,
        paper: ResearchPaper,
        *,
        actor_scope: Mapping[str, str],
    ) -> tuple[ResearchPaper, list[dict[str, Any]]]:
        urls = _unique([
            *_text_list(paper.metadata.get("code_urls")),
            *( [paper.code_url] if paper.code_url else [] ),
        ])
        if self._github is None or not urls:
            return paper, []
        profiles: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for url in urls:
            try:
                profile = self._github.fetch_profile(url)
                profile = profile.model_copy(update={
                    "actor_scope": dict(actor_scope),
                    "observations": [
                        observation.model_copy(update={"actor_scope": dict(actor_scope)})
                        for observation in profile.observations
                    ],
                    "metadata": {
                        **dict(profile.metadata),
                        "paper_id": paper.paper_id,
                        "actor_scope": dict(actor_scope),
                    },
                })
                github_snapshot = self._github_snapshot(
                    paper=paper,
                    profile=profile,
                    actor_scope=actor_scope,
                )
                if github_snapshot is not None:
                    if self._snapshots is not None:
                        self._snapshots.save(github_snapshot)
                    profile = profile.model_copy(update={
                        "source_snapshot_refs": _unique([
                            *profile.source_snapshot_refs,
                            github_snapshot.snapshot_id,
                        ]),
                        "observations": [
                            observation.model_copy(update={
                                "source_snapshot_refs": _unique([
                                    *observation.source_snapshot_refs,
                                    github_snapshot.snapshot_id,
                                ]),
                            })
                            for observation in profile.observations
                        ],
                    })
                profiles.append(profile.model_dump(mode="json", exclude_none=True))
                if self._code_profiles is not None:
                    saver = getattr(self._code_profiles, "save_code_profile", None)
                    if callable(saver):
                        saver(profile)
            except Exception as exc:  # noqa: BLE001 - enrichment is optional
                diagnostics.append({
                    "code": "github_enrichment_failed",
                    "repo_url": url,
                    "error_type": type(exc).__name__,
                })
        if not profiles:
            return paper, diagnostics
        return paper.model_copy(update={
            "metadata": {
                **dict(paper.metadata),
                "code_profiles": profiles,
                "code_profile": profiles[0],
            },
        }), diagnostics

    def _github_snapshot(
        self,
        *,
        paper: ResearchPaper,
        profile: CodeRepositoryProfile,
        actor_scope: Mapping[str, str],
    ) -> ResearchSourceSnapshot | None:
        if not profile.repo_url:
            return None
        observed_at = profile.observed_at or (
            profile.observations[-1].observed_at if profile.observations else datetime.now(UTC)
        )
        observation_refs = _unique([
            *profile.source_snapshot_refs,
            *(
                ref
                for observation in profile.observations
                for ref in observation.source_snapshot_refs
            ),
        ])
        source_ref = f"github://{profile.repo_url.removeprefix('https://github.com/').removeprefix('http://github.com')}"
        snapshot_payload = {
            "repository_id": profile.canonical_repo_id,
            "branch": profile.default_branch,
            "commit_sha": profile.commit_sha,
            "release": profile.release,
            "observation_refs": observation_refs,
            "observed_at": observed_at.isoformat(),
        }
        source_hash = hashlib.sha256(
            str(sorted(snapshot_payload.items())).encode("utf-8")
        ).hexdigest()
        return ResearchSourceSnapshot(
            snapshot_id=stable_research_id(
                "github_source_snapshot",
                paper.paper_id,
                profile.canonical_repo_id or profile.repo_url,
                source_hash,
            ),
            paper_id=paper.paper_id,
            source_type="github",
            canonical_url=profile.repo_url,
            external_id=profile.canonical_repo_id,
            content_type="application/json",
            source_hash=source_hash,
            checksum=source_hash,
            fetched_at=observed_at,
            observed_at=observed_at,
            access_status="available",
            lineage={
                "source_refs": _unique([source_ref, profile.repo_url, *observation_refs]),
                "source_hash": source_hash,
                "metadata": {"actor_scope": dict(actor_scope)},
            },
            actor_scope=dict(actor_scope),
            metadata={
                "actor_scope": dict(actor_scope),
                "observation": snapshot_payload,
                "source": "github_repository_api",
            },
        )

    def _scores_for_paper(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> list[ResearchScore]:
        getter = getattr(self._catalog, "list_scores", None)
        if callable(getter):
            values = _scoped_call(getter, paper_id, actor_scope=dict(actor_scope or {}))
            return [
                score
                for score in values
                if isinstance(score, ResearchScore)
                and _value_scope_matches(score, actor_scope)
            ]
        return []

    def _save_score(self, score: ResearchScore) -> None:
        saver = getattr(self._catalog, "save_score", None)
        if callable(saver):
            saver(score)

    def _save_sota_claim(self, claim: ResearchSOTAClaim) -> None:
        saver = getattr(self._sota_claims, "save_sota_claim", None)
        if callable(saver):
            saver(claim)

    def _candidate_sota_claims(
        self,
        *,
        paper: ResearchPaper,
        snapshot: ResearchSourceSnapshot,
        evidence_refs: list[str],
        document: ResearchDocument | None,
        score_candidates: list[ResearchScore],
        actor_scope: Mapping[str, str],
    ) -> list[ResearchSOTAClaim]:
        """Extract explicit SOTA assertions as quarantined candidates.

        This intentionally uses deterministic metadata/table/text signals. It
        never promotes a claim or infers that a score is SOTA from ranking.
        """

        metadata = dict(paper.metadata)
        raw_values: list[tuple[Mapping[str, Any], str | None]] = []
        raw = metadata.get("sota_claims") or metadata.get("sotaClaims")
        if isinstance(raw, Mapping):
            raw_values.append((raw, None))
        elif isinstance(raw, (list, tuple)):
            raw_values.extend((item, None) for item in raw if isinstance(item, Mapping))
        if document is not None:
            for section in document.sections:
                text = str(section.text or "")
                if "sota" in text.casefold() or "state-of-the-art" in text.casefold() or "state of the art" in text.casefold():
                    raw_values.append(({}, section.source_ref))
        claims: list[ResearchSOTAClaim] = []
        seen: set[str] = set()
        for index, (item, section_source_ref) in enumerate(raw_values):
            benchmark_id = _candidate_text(item, "benchmark_id", "benchmarkId") or _candidate_text(metadata, "benchmark_id", "benchmarkId")
            dataset_id = _candidate_text(item, "dataset_id", "datasetId") or _candidate_text(metadata, "dataset_id", "datasetId")
            metric_id = _candidate_text(item, "metric_id", "metricId") or _candidate_text(metadata, "metric_id", "metricId")
            claim_text = _candidate_text(item, "claim_text", "claimText", "text") or (
                "The paper makes a state-of-the-art claim." if section_source_ref else None
            )
            if not claim_text:
                continue
            claim_id = _candidate_text(item, "claim_id", "claimId") or stable_research_id(
                "research_sota_claim", paper.paper_id, benchmark_id or "unresolved", dataset_id or "unresolved", metric_id or "unresolved", str(index), claim_text
            )
            if claim_id in seen:
                continue
            seen.add(claim_id)
            source_refs = _text_values(item.get("source_refs") or item.get("sourceRefs"))
            if section_source_ref:
                source_refs.append(section_source_ref)
            source_refs = _unique([*source_refs, *snapshot.lineage.source_refs])
            claim_evidence = _text_values(item.get("evidence_refs") or item.get("evidenceRefs")) or list(evidence_refs)
            claim_version = _candidate_text(item, "dataset_version", "datasetVersion") or _candidate_text(metadata, "dataset_version", "datasetVersion")
            claim_split = _candidate_text(item, "split") or _candidate_text(metadata, "split")
            claim_unit = _candidate_text(item, "unit") or _candidate_text(metadata, "unit")
            claim_direction = _normalize_direction(
                _candidate_text(item, "direction") or _candidate_text(metadata, "direction")
            )
            claim_protocol = _candidate_text(item, "evaluation_protocol", "evaluationProtocol") or _candidate_text(metadata, "evaluation_protocol", "evaluationProtocol")
            score_id = _candidate_text(item, "score_id", "scoreId")
            if not score_id:
                compatible_scores = [
                    score
                    for score in score_candidates
                    if _sota_score_dimensions_match(
                        score,
                        benchmark_id=benchmark_id or "",
                        dataset_id=dataset_id or "",
                        metric_id=metric_id or "",
                        dataset_version=claim_version,
                        split=claim_split,
                        unit=claim_unit,
                        direction=claim_direction,
                        evaluation_protocol=claim_protocol,
                    )
                ]
                if len(compatible_scores) == 1:
                    score_id = compatible_scores[0].score_id
            claims.append(
                ResearchSOTAClaim(
                    claim_id=claim_id,
                    paper_id=paper.paper_id,
                    benchmark_id=benchmark_id or "",
                    dataset_id=dataset_id or "",
                    metric_id=metric_id or "",
                    score_id=score_id,
                    claim_text=claim_text,
                    verification_status="candidate",
                    source_refs=source_refs,
                    source_snapshot_refs=[snapshot.snapshot_id],
                    evidence_refs=claim_evidence,
                    dataset_version=claim_version,
                    split=claim_split,
                    unit=claim_unit,
                    direction=claim_direction,
                    evaluation_protocol=claim_protocol,
                    observed_at=snapshot.observed_at or snapshot.fetched_at or datetime.now(UTC),
                    actor_scope=dict(actor_scope),
                    metadata={
                        **dict(item),
                        "actor_scope": dict(actor_scope),
                        "extraction": "metadata_or_body_sota_signal",
                        **({"source_locator": section_source_ref} if section_source_ref else {}),
                    },
                )
            )
        return claims

    def verify_sota_claim(
        self,
        claim: Any,
        *,
        score: ResearchScore | None = None,
        benchmark: ResearchBenchmark | None = None,
        dataset: ResearchDataset | None = None,
        metric: ResearchMetric | None = None,
    ) -> Any:
        """Promote a SOTA claim only when every typed dependency is proven."""

        reasons: list[str] = []
        if not getattr(claim, "source_refs", None):
            reasons.append("source_refs_missing")
        if not getattr(claim, "source_snapshot_refs", None):
            reasons.append("source_snapshot_refs_missing")
        if not getattr(claim, "evidence_refs", None):
            reasons.append("evidence_refs_missing")
        if score is None or not claim.score_id or score.score_id != claim.score_id:
            reasons.append("score_link_missing")
        elif score.verification_status != "verified":
            reasons.append("score_not_verified")
        elif score.paper_id != claim.paper_id:
            reasons.append("paper_link_mismatch")
        claim_scope = _scope_of(claim)
        if score is not None and not _scopes_equal(claim_scope, _scope_of(score)):
            reasons.append("actor_scope_mismatch")
        if benchmark is None or normalize_key(claim.benchmark_id) != normalize_key(benchmark.benchmark_id):
            reasons.append("benchmark_link_missing")
        if dataset is None or normalize_key(claim.dataset_id) != normalize_key(dataset.dataset_id):
            reasons.append("dataset_link_missing")
        if metric is None or normalize_key(claim.metric_id) != normalize_key(metric.metric_id):
            reasons.append("metric_link_missing")
        for dependency in (benchmark, dataset, metric):
            if dependency is not None and not _dependency_scope_compatible(
                claim_scope,
                _scope_of(dependency),
            ):
                reasons.append("actor_scope_mismatch")
                break
        if score is not None and not reasons:
            comparisons = (
                ("dataset_version", getattr(claim, "dataset_version", None), score.dataset_version),
                ("split", getattr(claim, "split", None), score.split),
                ("unit", getattr(claim, "unit", None), score.unit),
                ("direction", getattr(claim, "direction", None), score.direction),
                ("evaluation_protocol", getattr(claim, "evaluation_protocol", None), score.evaluation_protocol),
            )
            for field_name, claim_value, score_value in comparisons:
                if not claim_value or not score_value:
                    reasons.append(f"{field_name}_missing")
                elif normalize_key(str(claim_value)) != normalize_key(str(score_value)):
                    reasons.append(f"{field_name}_mismatch")
        status = "verified" if not reasons else (
            "conflicting" if any("mismatch" in reason or "link" in reason for reason in reasons) else "rejected"
        )
        payload = {
            **claim.model_dump(mode="python"),
            "verification_status": status,
            "status": status,
            "metadata": {**dict(claim.metadata), "verification_reasons": reasons},
        }
        updated = type(claim).model_validate(payload)
        if isinstance(updated, ResearchSOTAClaim):
            self._save_sota_claim(updated)
        return updated

    def _candidate_scores(
        self,
        *,
        paper: ResearchPaper,
        snapshot: ResearchSourceSnapshot,
        evidence_refs: list[str],
        document: ResearchDocument | None,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchScore]:
        metadata = dict(paper.metadata)
        raw_candidates: list[Mapping[str, Any]] = []
        for key in ("scores", "benchmark_scores", "score_candidates"):
            raw = metadata.get(key)
            if isinstance(raw, Mapping):
                raw_candidates.append(raw)
            elif isinstance(raw, (list, tuple)):
                raw_candidates.extend(item for item in raw if isinstance(item, Mapping))
        if document is not None:
            for table in document.tables:
                for row in table.rows:
                    if isinstance(row, Mapping):
                        raw_candidates.append({
                            **row,
                            "source_refs": [table.source_ref],
                            "table_caption": table.caption,
                        })
        result: list[ResearchScore] = []
        for index, item in enumerate(raw_candidates):
            benchmark_id = (
                _candidate_text(item, "benchmark_id", "benchmarkId")
                or _candidate_text(metadata, "benchmark_id", "benchmarkId")
                or _candidate_text(item, "table_caption")
            )
            dataset_id = _candidate_text(item, "dataset_id", "datasetId") or _candidate_text(metadata, "dataset_id", "datasetId")
            metric_id = _candidate_text(item, "metric_id", "metricId") or _candidate_text(metadata, "metric_id", "metricId")
            raw_display = _candidate_text(item, "raw_display_value", "rawDisplayValue", "value", "score", "result")
            value = _candidate_number(item, "normalized_value", "normalizedValue", "value", "score", "result")
            if not benchmark_id or not dataset_id or not metric_id or value is None:
                continue
            source_refs = _text_values(item.get("source_refs") or item.get("sourceRefs")) or list(snapshot.lineage.source_refs)
            item_evidence = _text_values(item.get("evidence_refs") or item.get("evidenceRefs")) or list(evidence_refs)
            direction = _candidate_text(item, "direction")
            if direction not in {"higher_is_better", "lower_is_better"}:
                direction = None
            result.append(ResearchScore(
                score_id=_candidate_text(item, "score_id", "scoreId") or stable_research_id("research_score", paper.paper_id, benchmark_id, dataset_id, metric_id, str(value), str(index)),
                paper_id=paper.paper_id,
                benchmark_id=benchmark_id,
                dataset_id=dataset_id,
                metric_id=metric_id,
                value=value,
                raw_display_value=raw_display,
                normalized_value=value,
                baseline_id=_candidate_text(item, "baseline_id", "baselineId"),
                baseline_ref=_candidate_text(item, "baseline_ref", "baselineRef", "baseline_id", "baselineId"),
                source_refs=source_refs,
                source_snapshot_refs=[snapshot.snapshot_id],
                evidence_refs=item_evidence,
                verification_status="candidate",
                split=_candidate_text(item, "split"),
                unit=_candidate_text(item, "unit") or ("%" if raw_display and raw_display.endswith("%") else None),
                direction=direction,
                dataset_version=_candidate_text(item, "dataset_version", "datasetVersion")
                or _candidate_text(metadata, "dataset_version", "datasetVersion"),
                evaluation_protocol=_candidate_text(item, "evaluation_protocol", "evaluationProtocol"),
                unit_conversion=_candidate_text(item, "unit_conversion", "unitConversion") or "identity",
                rounding_mode=_candidate_text(item, "rounding_mode", "roundingMode"),
                normalization_version=_candidate_text(item, "normalization_version", "normalizationVersion") or "research-score-normalization-v1",
                uncertainty=_candidate_number(item, "uncertainty", "std", "error", "margin_of_error"),
                sample_count=_candidate_int(item, "sample_count", "sampleCount"),
                seed_count=_candidate_int(item, "seed_count", "seedCount"),
                protocol_fingerprint=_candidate_text(item, "protocol_fingerprint", "protocolFingerprint"),
                selection_policy=_candidate_text(item, "selection_policy", "selectionPolicy") or "single_observation",
                checkpoint_ref=_candidate_text(item, "checkpoint_ref", "checkpointRef", "checkpoint"),
                observed_at=snapshot.observed_at or snapshot.fetched_at or datetime.now(UTC),
                actor_scope=dict(actor_scope or metadata.get("actor_scope") or {}),
                metadata={
                    **dict(item),
                    "actor_scope": dict(actor_scope or metadata.get("actor_scope") or {}),
                    "dataset_version": _candidate_text(item, "dataset_version", "datasetVersion")
                    or _candidate_text(metadata, "dataset_version", "datasetVersion"),
                    "protocol_contract_required": True,
                },
            ))
        return result


class InMemoryResearchCatalogRepository(
    ResearchPaperCatalogRepository,
    ResearchPaperIdentityRepository,
    ResearchPaperRelationRepository,
    ResearchSourceSnapshotRepository,
    ResearchPaperReadRepository,
    ResearchDocumentRepository,
    ResearchEvidencePackRepository,
    ResearchCodeRepositoryProfileRepository,
    ResearchSOTAClaimRepository,
):
    """Thread-safe repository used by local runs and contract tests."""

    def __init__(self) -> None:
        self._entries: dict[str, ResearchPaperCatalogEntry] = {}
        self._identities: dict[str, ResearchPaperIdentity] = {}
        self._papers: dict[str, ResearchPaper] = {}
        self._snapshots: dict[str, ResearchSourceSnapshot] = {}
        self._documents: dict[str, ResearchDocument] = {}
        self._evidence: dict[str, ResearchEvidencePack] = {}
        self._relations: dict[str, ResearchPaperRelation] = {}
        self._scores: dict[str, ResearchScore] = {}
        self._code_profiles: dict[str, CodeRepositoryProfile] = {}
        self._sota_claims: dict[str, ResearchSOTAClaim] = {}
        self._lock = RLock()

    def get(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> ResearchPaperCatalogEntry | None:
        with self._lock:
            value = self._entries.get(_scoped_key(paper_id, actor_scope))
            if value is None and actor_scope is None:
                value = self._entries.get(paper_id)
            return value

    def save(self, value: Any) -> None:
        with self._lock:
            if isinstance(value, ResearchPaperCatalogEntry):
                self._entries[_scoped_key(value.paper_id, value.metadata.get("actor_scope"))] = value
            elif isinstance(value, ResearchPaperIdentity):
                self._identities[_scoped_key(value.paper_id, value.metadata.get("actor_scope"))] = value
            elif isinstance(value, ResearchPaperRelation):
                self._relations[_scoped_key(value.relation_id, value.metadata.get("actor_scope"))] = value
            elif isinstance(value, ResearchSourceSnapshot):
                key = _scoped_key(value.snapshot_id, _snapshot_scope(value))
                existing_snapshot = self._snapshots.get(key)
                if existing_snapshot is not None and existing_snapshot != value:
                    raise ValueError(
                        "source snapshot is immutable and conflicts with an existing snapshot_id"
                    )
                self._snapshots[key] = value
            elif isinstance(value, ResearchPaper):
                self._papers[_scoped_key(value.paper_id, value.metadata.get("actor_scope"))] = value
            elif isinstance(value, ResearchDocument):
                self._documents[_scoped_key(value.paper_id, value.lineage.metadata)] = value
            elif isinstance(value, ResearchEvidencePack):
                self._evidence[_scoped_key(value.paper_id, value.metadata)] = value
            elif isinstance(value, CodeRepositoryProfile):
                key = value.canonical_repo_id or value.repo_url
                self._code_profiles[_scoped_key(key, value.metadata)] = value
            elif isinstance(value, ResearchSOTAClaim):
                self._sota_claims[_scoped_key(value.claim_id, value.metadata)] = value
            else:
                raise TypeError(f"unsupported catalog value: {type(value).__name__}")

    def search(
        self,
        query: str = "",
        *,
        limit: int = 50,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchPaperCatalogEntry]:
        normalized = str(query or "").casefold()
        with self._lock:
            values = list(self._entries.values())
            values = [
                entry
                for entry in values
                if actor_scope_matches(entry.metadata.get("actor_scope"), actor_scope)
            ]
            if normalized:
                values = [entry for entry in values if normalized in entry.identity.title.casefold() or normalized in entry.paper_id.casefold()]
            return values[:limit]

    def get_identity(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchPaperIdentity | None:
        with self._lock:
            value = self._identities.get(_scoped_key(paper_id, actor_scope)) or (
                self._identities.get(paper_id) if actor_scope is None else None
            )
            return value if value is None or _value_scope_matches(value, actor_scope) else None

    def get_paper(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchPaper | None:
        with self._lock:
            value = self._papers.get(_scoped_key(paper_id, actor_scope)) or (
                self._papers.get(paper_id) if actor_scope is None else None
            )
            return value if value is None or _value_scope_matches(value, actor_scope) else None

    def get_snapshot(self, snapshot_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchSourceSnapshot | None:
        with self._lock:
            value = self._snapshots.get(_scoped_key(snapshot_id, actor_scope)) or (
                self._snapshots.get(snapshot_id) if actor_scope is None else None
            )
            return value if value is None or _value_scope_matches(value, actor_scope) else None

    def get_document(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchDocument | None:
        with self._lock:
            value = self._documents.get(_scoped_key(paper_id, actor_scope)) or (
                self._documents.get(paper_id) if actor_scope is None else None
            )
            return value if value is None or _value_scope_matches(value, actor_scope) else None

    def get_evidence(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchEvidencePack | None:
        with self._lock:
            value = self._evidence.get(_scoped_key(paper_id, actor_scope)) or (
                self._evidence.get(paper_id) if actor_scope is None else None
            )
            return value if value is None or _value_scope_matches(value, actor_scope) else None

    def find_by_external_id(self, external_id: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchPaperIdentity | None:
        needle = str(external_id or "").strip().casefold()
        if not needle:
            return None
        with self._lock:
            return next(
                (
                    identity
                    for identity in self._identities.values()
                    if actor_scope_matches(identity.metadata.get("actor_scope"), actor_scope)
                    and any(
                        str(value).strip().casefold() == needle
                        for value in (identity.arxiv_id, identity.doi, identity.openreview_id, identity.canonical_url)
                        if value
                    )
                ),
                None,
            )

    def find_by_fingerprint(self, fingerprint: str, *, actor_scope: Mapping[str, str] | None = None) -> ResearchPaperIdentity | None:
        needle = str(fingerprint or "").strip().casefold()
        if not needle:
            return None
        with self._lock:
            return next(
                (
                    identity
                    for identity in self._identities.values()
                    if identity.fingerprint
                    and identity.fingerprint.casefold() == needle
                    and actor_scope_matches(identity.metadata.get("actor_scope"), actor_scope)
                ),
                None,
            )

    def list_for_paper(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> list[ResearchSourceSnapshot]:
        with self._lock:
            return [snapshot for snapshot in self._snapshots.values() if snapshot.paper_id == paper_id and actor_scope_matches(_snapshot_scope(snapshot), actor_scope)]

    def list_relations(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> list[ResearchPaperRelation]:
        with self._lock:
            return [relation for relation in self._relations.values() if relation.paper_id == paper_id and actor_scope_matches(relation.metadata.get("actor_scope"), actor_scope)]

    def save_score(self, score: ResearchScore) -> None:
        with self._lock:
            self._scores[_scoped_key(score.score_id, score.metadata.get("actor_scope"))] = score

    def list_scores(self, paper_id: str, *, actor_scope: Mapping[str, str] | None = None) -> list[ResearchScore]:
        with self._lock:
            return [score for score in self._scores.values() if score.paper_id == paper_id and actor_scope_matches(score.metadata.get("actor_scope"), actor_scope)]

    def list_all_scores(self, *, actor_scope: Mapping[str, str] | None = None) -> list[ResearchScore]:
        with self._lock:
            return [score for score in self._scores.values() if actor_scope_matches(score.metadata.get("actor_scope"), actor_scope)]

    def save_code_profile(self, profile: CodeRepositoryProfile) -> None:
        self.save(profile)

    def save_sota_claim(self, claim: ResearchSOTAClaim) -> None:
        self.save(claim)

    def list_sota_claims(
        self,
        paper_id: str,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[ResearchSOTAClaim]:
        with self._lock:
            return [
                claim
                for claim in self._sota_claims.values()
                if claim.paper_id == paper_id
                and actor_scope_matches(claim.metadata.get("actor_scope"), actor_scope)
            ]

    def list_code_profiles(
        self,
        paper_id: str | None = None,
        *,
        actor_scope: Mapping[str, str] | None = None,
    ) -> list[CodeRepositoryProfile]:
        with self._lock:
            return [
                profile
                for profile in self._code_profiles.values()
                if actor_scope_matches(profile.metadata.get("actor_scope"), actor_scope)
                and (paper_id is None or profile.metadata.get("paper_id") == paper_id)
            ]


def _required_id(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CatalogError("invalid_request", f"{label} is required", status_code=400)
    return normalized


def _scoped_call(method, *args, actor_scope: Mapping[str, str] | None = None, **kwargs):
    """Call a scope-aware port while keeping older test adapters compatible."""

    try:
        return method(*args, actor_scope=actor_scope, **kwargs)
    except TypeError as exc:
        if "actor_scope" not in str(exc):
            raise
        if actor_scope:
            raise TypeError("scope-aware repository is required for actor-scoped research data") from exc
        return method(*args, **kwargs)


def _scoped_key(identifier: str, scope: Mapping[str, Any] | None) -> str:
    raw_scope: Mapping[str, Any] = scope or {}
    nested_scope = raw_scope.get("actor_scope") if isinstance(raw_scope, Mapping) else None
    if isinstance(nested_scope, Mapping):
        raw_scope = {**dict(raw_scope), **dict(nested_scope)}
    values = {
        str(key): str(value).strip()
        for key, value in raw_scope.items()
        if str(key) in {"tenant_id", "user_id", "memory_namespace"} and str(value).strip()
    }
    return identifier if not values else f"{actor_scope_ref(values)}::{identifier}"


def _snapshot_scope(snapshot: ResearchSourceSnapshot) -> Mapping[str, Any]:
    scope: dict[str, Any] = {}
    typed = getattr(snapshot, "actor_scope", None)
    if isinstance(typed, Mapping):
        scope.update(typed)
    for source in (snapshot.metadata, snapshot.lineage.metadata):
        if not isinstance(source, Mapping):
            continue
        nested = source.get("actor_scope")
        if isinstance(nested, Mapping):
            scope.update(nested)
        for key in ("tenant_id", "user_id", "memory_namespace"):
            if source.get(key) is not None and str(source.get(key)).strip():
                scope[key] = str(source[key]).strip()
    return scope


def _value_scope_matches(value: Any, actor_scope: Mapping[str, Any] | None) -> bool:
    typed = getattr(value, "actor_scope", None)
    if isinstance(typed, Mapping) and typed:
        return actor_scope_matches(typed, actor_scope)
    metadata = getattr(value, "metadata", None)
    if isinstance(metadata, Mapping):
        nested = metadata.get("actor_scope")
        if isinstance(nested, Mapping):
            return actor_scope_matches(nested, actor_scope)
    lineage = getattr(value, "lineage", None)
    lineage_metadata = getattr(lineage, "metadata", None)
    if isinstance(lineage_metadata, Mapping):
        nested = lineage_metadata.get("actor_scope")
        if isinstance(nested, Mapping):
            return actor_scope_matches(nested, actor_scope)
    return actor_scope_matches({}, actor_scope)


def _scope_of(value: Any) -> dict[str, str]:
    typed = getattr(value, "actor_scope", None)
    if isinstance(typed, Mapping) and typed:
        return {str(key): str(raw).strip() for key, raw in typed.items() if str(raw).strip()}
    metadata = getattr(value, "metadata", None)
    if isinstance(metadata, Mapping):
        nested = metadata.get("actor_scope")
        if isinstance(nested, Mapping):
            return {str(key): str(raw).strip() for key, raw in nested.items() if str(raw).strip()}
    return {}


def _scopes_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    normalized_left = {str(key): str(value).strip() for key, value in left.items() if str(value).strip()}
    normalized_right = {str(key): str(value).strip() for key, value in right.items() if str(value).strip()}
    return normalized_left == normalized_right


def _dependency_scope_compatible(
    claim_scope: Mapping[str, Any],
    dependency_scope: Mapping[str, Any],
) -> bool:
    """Allow global definitions, but never widen a scoped claim.

    Scores are observations made inside the same actor namespace and are
    checked with exact equality above. Benchmark/dataset/metric definitions
    may be global (empty scope), while a non-empty dependency scope must match
    the claim exactly.
    """

    normalized_claim = {
        str(key): str(value).strip()
        for key, value in claim_scope.items()
        if str(value).strip()
    }
    normalized_dependency = {
        str(key): str(value).strip()
        for key, value in dependency_scope.items()
        if str(value).strip()
    }
    return not normalized_dependency or normalized_claim == normalized_dependency


def _sota_score_dimensions_match(
    score: ResearchScore,
    *,
    benchmark_id: str,
    dataset_id: str,
    metric_id: str,
    dataset_version: str | None,
    split: str | None,
    unit: str | None,
    direction: str | None,
    evaluation_protocol: str | None,
) -> bool:
    def same(left: Any, right: Any) -> bool:
        if right is None or str(right).strip() == "":
            return True
        return normalize_key(str(left or "")) == normalize_key(str(right))

    return (
        normalize_key(score.benchmark_id) == normalize_key(benchmark_id)
        and normalize_key(score.dataset_id) == normalize_key(dataset_id)
        and normalize_key(score.metric_id) == normalize_key(metric_id)
        and same(score.dataset_version or score.metadata.get("dataset_version"), dataset_version)
        and same(score.split, split)
        and same(score.unit, unit)
        and same(score.direction, direction)
        and same(score.evaluation_protocol, evaluation_protocol)
    )


def _relation_scope(relation: ResearchPaperRelation) -> Mapping[str, Any]:
    value = relation.metadata.get("actor_scope")
    return value if isinstance(value, Mapping) else {}


def _score_row(score: ResearchScore, compatibility: Mapping[str, str]) -> dict[str, Any]:
    return {
        "scoreId": score.score_id,
        "paperId": score.paper_id,
        "benchmarkId": score.benchmark_id,
        "datasetId": score.dataset_id,
        "metricId": score.metric_id,
        "value": score.value,
        "rawDisplayValue": score.raw_display_value,
        "normalizedValue": score.normalized_value,
        "normalizationVersion": score.normalization_version or score.metadata.get("normalization_version"),
        "unitConversion": score.unit_conversion,
        "roundingMode": score.rounding_mode,
        "uncertainty": score.uncertainty,
        "sampleCount": score.sample_count,
        "seedCount": score.seed_count,
        "protocolFingerprint": score.protocol_fingerprint,
        "selectionPolicy": score.selection_policy,
        "checkpointRef": score.checkpoint_ref,
        "baselineRef": score.baseline_ref or score.baseline_id,
        "sourceSnapshotRefs": list(score.source_snapshot_refs),
        "evidenceRefs": list(score.evidence_refs),
        "observedAt": score.observed_at.isoformat() if score.observed_at else None,
        "actorScope": dict(score.actor_scope),
        "datasetVersion": score.dataset_version or score.metadata.get("dataset_version"),
        "split": score.split,
        "unit": score.unit,
        "direction": score.direction or "higher_is_better",
        "evaluationProtocol": score.evaluation_protocol,
        "status": score.verification_status,
        "compatibilityKey": dict(compatibility),
    }


def _score_filter_reason(
    score: ResearchScore,
    *,
    benchmark_id: str | None,
    metric_id: str | None,
    dataset_id: str | None,
    dataset_version: str | None,
    split: str | None,
    evaluation_protocol: str | None,
) -> str | None:
    checks = (
        ("benchmark_id", benchmark_id, score.benchmark_id),
        ("metric_id", metric_id, score.metric_id),
        ("dataset_id", dataset_id, score.dataset_id),
        ("dataset_version", dataset_version, score.dataset_version or score.metadata.get("dataset_version")),
        ("split", split, score.split),
        ("evaluation_protocol", evaluation_protocol, score.evaluation_protocol),
    )
    for field_name, expected, actual in checks:
        if expected is not None and normalize_key(str(actual or "")) != normalize_key(str(expected)):
            return f"filter:{field_name}"
    return None


def _verified_score_missing_reason(score: ResearchScore) -> str | None:
    required = (
        ("source_snapshot_refs", score.source_snapshot_refs),
        ("evidence_refs", score.evidence_refs),
        ("dataset_version", score.dataset_version or score.metadata.get("dataset_version")),
        ("split", score.split),
        ("unit", score.unit),
        ("direction", score.direction),
        ("evaluation_protocol", score.evaluation_protocol),
    )
    for field_name, value in required:
        if value is None or (isinstance(value, (list, tuple, set)) and not value) or not str(value).strip():
            return f"{field_name}_missing"
    if score.metadata.get("protocol_contract_required"):
        unknown = score.metadata.get("protocol_unknown_fields")
        if isinstance(unknown, (list, tuple, set)) and unknown:
            return "protocol_dimensions_missing"
    return None


def _sort_score_rows(
    rows: list[dict[str, Any]],
    *,
    direction: str,
) -> list[dict[str, Any]]:
    """Sort one compatible leaderboard deterministically.

    Numeric value is the primary ranking dimension and score id is an
    ascending tie-breaker so equal values do not depend on input order.
    """
    if direction == "lower_is_better":
        ordered = sorted(rows, key=lambda row: (float(row["normalizedValue"]), str(row["scoreId"])))
    else:
        ordered = sorted(rows, key=lambda row: (-float(row["normalizedValue"]), str(row["scoreId"])))
    previous: float | None = None
    rank = 0
    for row in ordered:
        value = float(row["normalizedValue"])
        if previous is None or value != previous:
            rank += 1
            previous = value
        row["rank"] = rank
        row["tieGroup"] = f"{direction}:{value:.12g}"
    return ordered


def _compatibility_key_payload(key: tuple[str, ...]) -> dict[str, str]:
    labels = (
        "datasetId",
        "datasetVersion",
        "metricId",
        "direction",
        "unit",
        "split",
        "evaluationProtocol",
        "protocolFingerprint",
    )
    return {label: str(value) for label, value in zip(labels, key)}


def _candidate_text(value: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        raw = value.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _normalize_direction(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_key(str(value))
    aliases = {
        "higher": "higher_is_better",
        "higherisbetter": "higher_is_better",
        "max": "higher_is_better",
        "lower": "lower_is_better",
        "lowerisbetter": "lower_is_better",
        "min": "lower_is_better",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"higher_is_better", "lower_is_better"} else None


def _candidate_number(value: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        raw = value.get(key)
        if raw is None:
            continue
        text = str(raw).strip().replace(",", "")
        match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text)
        if match is not None:
            try:
                return float(match.group(0))
            except ValueError:
                continue
    return None


def _candidate_int(value: Mapping[str, Any], *keys: str) -> int | None:
    number = _candidate_number(value, *keys)
    if number is None or int(number) != number or number < 0:
        return None
    return int(number)


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return _unique(part.strip() for part in value.split(","))
    if isinstance(value, (list, tuple, set)):
        return _unique(str(item) for item in value)
    return []


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return _unique(part.strip() for part in value.split(","))
    if isinstance(value, (list, tuple, set)):
        return _unique(str(item) for item in value)
    return []


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result


def _merge_relations(existing: Iterable[ResearchPaperRelation], incoming: Iterable[ResearchPaperRelation]) -> list[ResearchPaperRelation]:
    merged: dict[str, ResearchPaperRelation] = {relation.relation_id: relation for relation in existing}
    for relation in incoming:
        old = merged.get(relation.relation_id)
        if old is None:
            merged[relation.relation_id] = relation
            continue
        winner = relation if old.status != "verified" and relation.status == "verified" else old
        merged[relation.relation_id] = winner.model_copy(update={
            "source_snapshot_refs": _unique([
                *old.source_snapshot_refs,
                *relation.source_snapshot_refs,
            ]),
            "evidence_refs": _unique([
                *old.evidence_refs,
                *relation.evidence_refs,
            ]),
            "confidence": max(old.confidence, relation.confidence),
            "metadata": {**dict(old.metadata), **dict(relation.metadata)},
            "observed_at": max(
                (value for value in (old.observed_at, relation.observed_at) if value is not None),
                default=None,
            ),
        })
    return list(merged.values())


def _metadata_tokens(text: str, key: str) -> list[str]:
    # Extraction remains a conservative candidate source. It does not promote
    # a token to a verified Catalog entity.
    markers = {"tasks": ("task", "benchmark"), "methods": ("method", "approach")}.get(key, ())
    normalized = str(text).casefold()
    return [marker for marker in markers if marker in normalized]


__all__ = [
    "CatalogError",
    "CatalogLeaderboardResult",
    "InMemoryResearchCatalogRepository",
    "ResearchPaperCatalogService",
]
