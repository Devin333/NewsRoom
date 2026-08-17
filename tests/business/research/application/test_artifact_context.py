from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from business.research.application.artifact_context import (
    ResearchGraphArtifactContextProvider,
)
from business.research.domain import research_event_tenant_id
from framework.events.canonical import checksum_for
from framework.harness.artifacts.catalog import ArtifactCatalogRegistrationRequest
from framework.harness.artifacts import GraphArtifactUsageFact
from framework.harness.graph.result_lineage import (
    HarnessGraphArtifactRefProjection,
    HarnessGraphResultLineage,
    HarnessGraphResultSummary,
)
from framework.harness.control_plane.graph_runtime import HarnessGraphCommitKind
from framework.harness.control_plane.harness import InMemoryHarnessEventPort
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    ContextPolicy,
    GraphArtifactPersistenceConfig,
    ResultSensitivity,
    RetentionClass,
)
from framework.harness.runtime.result_canonical import (
    estimated_tokens,
    serialize_candidate,
    sha256_checksum,
)
from infrastructure.storage.artifacts import LocalJsonArtifactCatalog


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


@dataclass
class RejectingGraphResultReader:
    reads: int = 0

    def read_graph_result_artifact(self, ref: str, *, expected_run_id: str):
        del ref, expected_run_id
        self.reads += 1
        raise AssertionError("summary-only recovery must not read artifact bytes")


@dataclass
class RecordingUsage:
    facts: dict[str, GraphArtifactUsageFact] = field(default_factory=dict)

    def record_usage(self, fact: GraphArtifactUsageFact) -> GraphArtifactUsageFact:
        return self.facts.setdefault(fact.fact_id, fact)

    def list_usage(self, *, tenant_id, window_start, window_end, watermark=None):
        del watermark
        return tuple(
            fact
            for fact in self.facts.values()
            if fact.tenant_id == tenant_id
            and window_start <= fact.occurred_at < window_end
        )

    def usage_watermark(self, *, tenant_id):
        return sum(fact.tenant_id == tenant_id for fact in self.facts.values())


def test_research_provider_rebuilds_stable_context_from_durable_recovery(
    tmp_path,
) -> None:
    actor = {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "memory_namespace": "research-context",
    }
    tenant_id = research_event_tenant_id(actor)
    candidate, candidate_bytes = serialize_candidate(
        {"evidence": "durable"},
        "application/json",
    )
    del candidate
    candidate_checksum = sha256_checksum(candidate_bytes)
    identity = candidate_checksum.removeprefix("sha256:")
    artifact_type = f"graph-result-{identity}"
    ref = f"artifact://run-1/{artifact_type}"
    record = ArtifactRecord(
        ref=ref,
        artifact_id=f"result-{identity}",
        artifact_type=artifact_type,
        content_checksum=candidate_checksum,
        byte_size=len(candidate_bytes),
        media_type="application/json",
        artifact_class=ArtifactClass.EVIDENCE,
        tenant_id=tenant_id,
        run_id="run-1",
        graph_id="graph-1",
        node_id="build_reader_payload",
        attempt_id="attempt-1",
        producer_revision="research-source@1",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.EVIDENCE,
        expires_at=NOW + timedelta(days=30),
        required_for_replay=True,
        required_for_publication=False,
        created_at=NOW,
    )
    catalog = LocalJsonArtifactCatalog(tmp_path / "catalog")
    catalog.register(
        ArtifactCatalogRegistrationRequest.from_verified_record(
            record,
            verified_at=NOW,
        )
    )
    summary_text = "durable evidence summary"
    summary_bytes = len(summary_text.encode("utf-8"))
    lineage = HarnessGraphResultLineage(
        tenant_id=tenant_id,
        run_id="run-1",
        graph_id="graph-1",
        graph_version="graph-1@1",
        node_id="build_reader_payload",
        node_instance_id="build_reader_payload:1",
        attempt_id="attempt-1",
        attempt=1,
        parent_checkpoint_ref="checkpoint://run-1/1",
        status="succeeded",
        output_schema_ref="research-source@1",
        output_schema_digest="sha256:" + "a" * 64,
        candidate_checksum=candidate_checksum,
        envelope_checksum="sha256:" + "b" * 64,
        candidate_bytes=len(candidate_bytes),
        candidate_tokens=estimated_tokens(len(candidate_bytes)),
        summary=HarnessGraphResultSummary(
            text=summary_text,
            byte_size=summary_bytes,
            token_estimate=estimated_tokens(summary_bytes),
            complete=False,
        ),
        inline_projection={},
        artifact_refs=(
            HarnessGraphArtifactRefProjection(
                ref=ref,
                artifact_id=record.artifact_id,
                artifact_type=artifact_type,
                content_checksum=candidate_checksum,
                byte_size=len(candidate_bytes),
                media_type="application/json",
                artifact_class=ArtifactClass.EVIDENCE.value,
                retention_class=RetentionClass.EVIDENCE.value,
                tenant_id=tenant_id,
                run_id="run-1",
                graph_id="graph-1",
                node_id="build_reader_payload",
                attempt_id="attempt-1",
                sensitivity=ResultSensitivity.INTERNAL.value,
                context_policy=ContextPolicy.REF_LOAD_ALLOWED.value,
                required_for_replay=True,
                required_for_publication=False,
            ),
        ),
        persistence_mode="artifact",
        policy_version="graph-artifact-policy@1",
        required=True,
        tenant_scope_ref=checksum_for(tenant_id),
        producer_ref="research-source@1",
        producer_revision="research-source@1",
        source_refs=("source://one",),
        inline_bytes=0,
    )

    def logical_duplicate(
        source: HarnessGraphResultLineage,
        *,
        node_id: str,
        attempt_id: str,
        digest_char: str,
    ) -> HarnessGraphResultLineage:
        logical_identity = digest_char * 64
        logical_type = f"graph-result-{logical_identity}"
        logical_record = replace(
            record,
            ref=f"artifact://run-1/{logical_type}",
            artifact_id=f"result-{logical_identity}",
            artifact_type=logical_type,
            node_id=node_id,
            attempt_id=attempt_id,
        )
        registration = catalog.register(
            ArtifactCatalogRegistrationRequest.from_verified_record(
                logical_record,
                verified_at=NOW,
            )
        )
        logical_projection = replace(
            source.artifact_refs[0],
            ref=registration.claim.record.ref,
            artifact_id=logical_record.artifact_id,
            artifact_type=logical_type,
            node_id=node_id,
            attempt_id=attempt_id,
        )
        return replace(
            source,
            node_id=node_id,
            node_instance_id=f"{node_id}:1",
            attempt_id=attempt_id,
            envelope_checksum=f"sha256:{logical_identity}",
            artifact_refs=(logical_projection,),
        )

    lineages = (
        lineage,
        logical_duplicate(
            lineage,
            node_id="build_paper_card",
            attempt_id="attempt-2",
            digest_char="d",
        ),
        logical_duplicate(
            lineage,
            node_id="quality_gate",
            attempt_id="attempt-3",
            digest_char="e",
        ),
    )
    result_checksums = tuple(
        f"sha256:{character * 64}" for character in ("7", "8", "9")
    )
    recovery = SimpleNamespace(
        graph=SimpleNamespace(graph_id="graph-1"),
        state=object(),
        projection_commits=tuple(
            SimpleNamespace(
                commit_kind=HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION,
                cause_checksum=result_checksum,
            )
            for result_checksum in result_checksums
        ),
        activity_result_commits=tuple(
            SimpleNamespace(
                sequence=sequence,
                result=SimpleNamespace(
                    result_checksum=result_checksum,
                    result_lineage=result_lineage,
                )
            )
            for sequence, (result_checksum, result_lineage) in enumerate(
                zip(result_checksums, lineages, strict=True),
                start=1,
            )
        ),
    )
    event_port = InMemoryHarnessEventPort()
    recovery_calls: list[str] = []

    def recover_graph(run_id: str):
        recovery_calls.append(run_id)
        return recovery

    event_port.recover_graph = recover_graph
    reader = RejectingGraphResultReader()
    provider = ResearchGraphArtifactContextProvider(
        event_port=event_port,
        catalog=catalog,
        reader=reader,
        usage=RecordingUsage(),
        config=GraphArtifactPersistenceConfig(),
    )
    request = {
        "run_id": "run-1",
        "step_id": "publish_artifacts",
        "metadata": actor,
    }

    first = provider.load_artifact_context(request)
    restarted = provider.load_artifact_context(request)

    assert first == restarted
    assert first.context_fingerprint == restarted.context_fingerprint
    assert len(first.items) == 1
    assert first.items[0].content == summary_text
    assert recovery_calls == ["run-1", "run-1"]
    assert reader.reads == 0
