from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import pytest

from framework.harness.artifacts.catalog import ArtifactCatalogRegistrationRequest
from framework.harness.context import ContextAssembler
from framework.harness.control_plane.graph_result_lineage import (
    HarnessGraphArtifactRefProjection,
    HarnessGraphResultLineage,
    HarnessGraphResultSummary,
)
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactContextLoadResult,
    ArtifactContextLoader,
    ArtifactContextLoadPlanner,
    ArtifactRecord,
    ContextAssemblyRequest,
    ContextLoadMode,
    ContextPolicy,
    ContextPurpose,
    GraphArtifactPersistenceConfig,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    ResultSensitivity,
    RetentionClass,
)
from framework.harness.runtime.materializer import RESULT_PAYLOAD_SCHEMA
from framework.harness.runtime.result_canonical import (
    estimated_tokens,
    serialize_candidate,
    sha256_checksum,
)
from framework.shared.json import stable_json_dumps
from framework.harness.workflow.canonical import thaw_json
from infrastructure.storage.artifacts import LocalJsonArtifactCatalog


NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
TENANT_SCOPE = "sha256:" + "d" * 64


@dataclass
class RecordingGraphResultReader:
    payloads: dict[str, dict[str, Any]]
    reads: list[str] = field(default_factory=list)
    expected_run_ids: list[str] = field(default_factory=list)

    def read_graph_result_artifact(
        self,
        ref: str,
        *,
        expected_run_id: str,
    ) -> dict[str, Any]:
        self.reads.append(ref)
        self.expected_run_ids.append(expected_run_id)
        return self.payloads[ref]


@dataclass
class StaticArtifactContextProvider:
    result: ArtifactContextLoadResult
    calls: int = 0

    def load_artifact_context(self, request):
        self.calls += 1
        return self.result


def _bundle(
    tmp_path,
    *,
    candidate: Any | None = None,
    media_type: str = "application/json",
    sensitivity: ResultSensitivity = ResultSensitivity.INTERNAL,
    context_policy: ContextPolicy = ContextPolicy.REF_LOAD_ALLOWED,
    projection_byte_size: int | None = None,
):
    candidate = candidate if candidate is not None else {"payload": "evidence"}
    normalized, candidate_bytes = serialize_candidate(candidate, media_type)
    content_checksum = sha256_checksum(candidate_bytes)
    identity = sha256(content_checksum.encode("ascii")).hexdigest()
    artifact_type = f"graph-result-{identity}"
    ref = f"artifact://run-1/{artifact_type}"
    record = ArtifactRecord(
        ref=ref,
        artifact_id=f"result-{identity}",
        artifact_type=artifact_type,
        content_checksum=content_checksum,
        byte_size=len(candidate_bytes),
        media_type=media_type,
        artifact_class=ArtifactClass.EVIDENCE,
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        node_id="source-node",
        attempt_id="attempt-1",
        producer_revision="producer@1",
        sensitivity=sensitivity,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.EVIDENCE,
        expires_at=NOW + timedelta(days=30),
        required_for_replay=True,
        required_for_publication=False,
        created_at=NOW,
    )
    catalog = LocalJsonArtifactCatalog(tmp_path / f"catalog-{identity}")
    catalog.register(
        ArtifactCatalogRegistrationRequest.from_verified_record(
            record,
            verified_at=NOW,
        )
    )
    summary = HarnessGraphResultSummary(
        text="summary",
        byte_size=len("summary".encode("utf-8")),
        token_estimate=estimated_tokens(len("summary".encode("utf-8"))),
        complete=False,
    )
    projection = HarnessGraphArtifactRefProjection(
        ref=ref,
        artifact_id=record.artifact_id,
        artifact_type=artifact_type,
        content_checksum=content_checksum,
        byte_size=(
            len(candidate_bytes)
            if projection_byte_size is None
            else projection_byte_size
        ),
        media_type=media_type,
        artifact_class=ArtifactClass.EVIDENCE.value,
        retention_class=RetentionClass.EVIDENCE.value,
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        node_id="source-node",
        attempt_id="attempt-1",
        sensitivity=sensitivity.value,
        context_policy=context_policy.value,
        required_for_replay=True,
        required_for_publication=False,
    )
    lineage = HarnessGraphResultLineage(
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        graph_version="graph-1@1",
        node_id="source-node",
        node_instance_id="source-node:1",
        attempt_id="attempt-1",
        attempt=1,
        parent_checkpoint_ref="checkpoint://run-1/1",
        status="succeeded",
        output_schema_ref="result@1",
        output_schema_digest="sha256:" + "a" * 64,
        candidate_checksum=content_checksum,
        envelope_checksum="sha256:" + "b" * 64,
        candidate_bytes=len(candidate_bytes),
        candidate_tokens=estimated_tokens(len(candidate_bytes)),
        summary=summary,
        inline_projection={},
        artifact_refs=(projection,),
        persistence_mode="artifact",
        policy_version="graph-artifact-policy@1",
        required=True,
        tenant_scope_ref=TENANT_SCOPE,
        producer_ref="producer@1",
        producer_revision="producer@1",
        source_refs=("source://one",),
        inline_bytes=0,
    )
    if media_type == "application/json" or media_type.endswith("+json"):
        value = thaw_json(normalized)
        encoding = "json"
    elif media_type.startswith("text/"):
        value = normalized
        encoding = "text"
    else:
        raise AssertionError("test helper only needs JSON and text candidates")
    stored = {
        "artifact_type": artifact_type,
        "payload": {
            "schema": RESULT_PAYLOAD_SCHEMA,
            "candidate_checksum": content_checksum,
            "candidate_bytes": len(candidate_bytes),
            "media_type": media_type,
            "encoding": encoding,
            "value": value,
        },
        "media_type": "application/json",
        "metadata": {
            "tenant_id": "tenant-1",
            "run_id": "run-1",
            "graph_id": "graph-1",
            "node_id": "source-node",
            "attempt_id": "attempt-1",
            "candidate_checksum": content_checksum,
            "graph_result_ref_only": True,
            "identity_checksum": f"sha256:{identity}",
        },
    }
    return catalog, lineage, ref, stored, normalized, candidate_bytes


def _register_logical_duplicate(
    catalog: LocalJsonArtifactCatalog,
    lineage: HarnessGraphResultLineage,
    *,
    run_id: str,
    graph_id: str,
    node_id: str,
    attempt_id: str,
) -> HarnessGraphResultLineage:
    canonical = catalog.get_by_ref(
        tenant_id=lineage.tenant_id,
        ref=lineage.artifact_refs[0].ref,
    )
    identity = sha256(
        f"{run_id}:{graph_id}:{node_id}:{attempt_id}".encode("utf-8")
    ).hexdigest()
    artifact_type = f"graph-result-{identity}"
    record = replace(
        canonical.record,
        ref=f"artifact://{run_id}/{artifact_type}",
        artifact_id=f"result-{identity}",
        artifact_type=artifact_type,
        run_id=run_id,
        graph_id=graph_id,
        node_id=node_id,
        attempt_id=attempt_id,
    )
    registration = catalog.register(
        ArtifactCatalogRegistrationRequest.from_verified_record(
            record,
            verified_at=NOW,
        )
    )
    assert registration.claim.record.ref == canonical.record.ref
    projection = replace(
        lineage.artifact_refs[0],
        ref=canonical.record.ref,
        artifact_id=record.artifact_id,
        artifact_type=record.artifact_type,
        run_id=run_id,
        graph_id=graph_id,
        node_id=node_id,
        attempt_id=attempt_id,
    )
    return replace(
        lineage,
        run_id=run_id,
        graph_id=graph_id,
        graph_version=f"{graph_id}@1",
        node_id=node_id,
        node_instance_id=f"{node_id}:1",
        attempt_id=attempt_id,
        parent_checkpoint_ref=f"checkpoint://{run_id}/1",
        envelope_checksum="sha256:" + identity,
        artifact_refs=(projection,),
    )


def _request(
    ref: str,
    *,
    mode: ContextLoadMode,
    max_bytes: int = 4 * 1024 * 1024,
    max_tokens: int = 1_048_576,
    allowed_sensitivities=(ResultSensitivity.INTERNAL,),
) -> ContextAssemblyRequest:
    return ContextAssemblyRequest(
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        node_id="consumer-node",
        purpose=ContextPurpose.VERIFY,
        allowed_artifact_classes=(ArtifactClass.EVIDENCE,),
        allowed_sensitivities=allowed_sensitivities,
        artifact_refs=(ref, ref),
        max_refs=12,
        max_bytes=max_bytes,
        max_tokens=max_tokens,
        load_mode=mode,
    )


def _plan_and_loader(tmp_path, *, mode, **bundle_options):
    catalog, lineage, ref, stored, normalized, candidate_bytes = _bundle(
        tmp_path,
        **bundle_options,
    )
    config = GraphArtifactPersistenceConfig(
        summary_max_bytes=16,
        summary_max_tokens=4,
        sample_max_bytes=16,
    )
    reader = RecordingGraphResultReader({ref: stored})
    planner = ArtifactContextLoadPlanner(catalog=catalog, config=config)
    loader = ArtifactContextLoader(reader=reader, config=config)
    plan = planner.plan(_request(ref, mode=mode), accepted_lineages=(lineage,))
    return plan, loader, reader, normalized, candidate_bytes, lineage, ref


def test_summary_only_uses_lineage_without_physical_read_and_replays(tmp_path) -> None:
    plan, loader, reader, _, _, _, _ = _plan_and_loader(
        tmp_path,
        mode=ContextLoadMode.SUMMARY_ONLY,
    )

    result = loader.load(plan)
    restarted_plan = type(plan).from_dict(plan.to_dict())
    restarted_result = ArtifactContextLoadResult.from_dict(result.to_dict())

    assert reader.reads == []
    assert result.items[0].encoding == "summary"
    assert result.items[0].complete is False
    assert restarted_plan.plan_checksum == plan.plan_checksum
    assert restarted_result.result_checksum == result.result_checksum
    assert restarted_result.context_fingerprint == result.context_fingerprint
    assert stable_json_dumps(restarted_result.to_dict()) == stable_json_dumps(
        result.to_dict()
    )


def test_sample_is_deterministic_bounded_and_incomplete(tmp_path) -> None:
    plan, loader, reader, _, candidate_bytes, _, ref = _plan_and_loader(
        tmp_path,
        mode=ContextLoadMode.SAMPLE,
        candidate="sample-value-" * 20,
        media_type="text/plain",
        context_policy=ContextPolicy.SAMPLE_ALLOWED,
    )

    first = loader.load(plan)
    second = loader.load(plan)

    assert reader.reads == [ref, ref]
    assert first == second
    assert first.items[0].complete is False
    assert first.items[0].loaded_bytes == 16
    assert first.items[0].loaded_bytes < len(candidate_bytes)
    assert first.items[0].content == candidate_bytes[:16].decode("utf-8")


def test_full_load_returns_verified_complete_candidate(tmp_path) -> None:
    plan, loader, reader, normalized, candidate_bytes, _, ref = _plan_and_loader(
        tmp_path,
        mode=ContextLoadMode.FULL,
        candidate={"payload": ["one", "two", "three"]},
    )

    result = loader.load(plan)

    assert reader.reads == [ref]
    assert result.items[0].complete is True
    assert result.items[0].content == normalized
    assert result.items[0].loaded_bytes == len(candidate_bytes)
    assert result.items[0].loaded_checksum == result.items[0].content_checksum


def test_duplicate_logical_claims_charge_and_read_canonical_content_once(
    tmp_path,
) -> None:
    catalog, first, ref, stored, _, candidate_bytes = _bundle(tmp_path)
    second = _register_logical_duplicate(
        catalog,
        first,
        run_id="run-1",
        graph_id="graph-1",
        node_id="second-source-node",
        attempt_id="attempt-2",
    )
    config = GraphArtifactPersistenceConfig()
    reader = RecordingGraphResultReader({ref: stored})
    plan = ArtifactContextLoadPlanner(catalog=catalog, config=config).plan(
        _request(ref, mode=ContextLoadMode.FULL),
        accepted_lineages=(second, first),
    )

    result = ArtifactContextLoader(reader=reader, config=config).load(plan)

    assert len(plan.items) == 1
    assert plan.planned_loaded_bytes == len(candidate_bytes)
    assert len(result.items) == 1
    assert result.total_loaded_bytes == len(candidate_bytes)
    assert reader.reads == [ref]
    assert reader.expected_run_ids == ["run-1"]


def test_current_run_claim_can_load_a_cross_run_canonical_physical_object(
    tmp_path,
) -> None:
    catalog, first, ref, stored, _, _ = _bundle(tmp_path)
    current = _register_logical_duplicate(
        catalog,
        first,
        run_id="run-2",
        graph_id="graph-2",
        node_id="source-node",
        attempt_id="attempt-2",
    )
    request = replace(
        _request(ref, mode=ContextLoadMode.FULL),
        run_id="run-2",
        graph_id="graph-2",
    )
    config = GraphArtifactPersistenceConfig()
    reader = RecordingGraphResultReader({ref: stored})
    plan = ArtifactContextLoadPlanner(catalog=catalog, config=config).plan(
        request,
        accepted_lineages=(current,),
    )

    result = ArtifactContextLoader(reader=reader, config=config).load(plan)

    assert result.items[0].complete is True
    assert plan.items[0].run_id == "run-2"
    assert plan.items[0].physical_run_id == "run-1"
    assert reader.expected_run_ids == ["run-1"]


def test_planning_rejects_budget_arbitrary_scope_and_catalog_mismatch_before_read(
    tmp_path,
) -> None:
    catalog, lineage, ref, stored, _, candidate_bytes = _bundle(tmp_path)
    config = GraphArtifactPersistenceConfig()
    reader = RecordingGraphResultReader({ref: stored})
    planner = ArtifactContextLoadPlanner(catalog=catalog, config=config)

    with pytest.raises(GraphArtifactResultError) as budget:
        planner.plan(
            _request(
                ref,
                mode=ContextLoadMode.FULL,
                max_bytes=len(candidate_bytes) - 1,
            ),
            accepted_lineages=(lineage,),
        )
    assert budget.value.error_code is GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED

    with pytest.raises(GraphArtifactResultError) as arbitrary:
        planner.plan(
            replace(
                _request(ref, mode=ContextLoadMode.SUMMARY_ONLY),
                artifact_refs=("artifact://run-1/not-accepted",),
            ),
            accepted_lineages=(lineage,),
        )
    assert arbitrary.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH

    bad_projection = replace(lineage.artifact_refs[0], byte_size=len(candidate_bytes) + 1)
    bad_lineage = replace(lineage, artifact_refs=(bad_projection,))
    with pytest.raises(GraphArtifactResultError) as corrupt:
        planner.plan(
            _request(ref, mode=ContextLoadMode.SUMMARY_ONLY),
            accepted_lineages=(bad_lineage,),
        )
    assert corrupt.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_CATALOG_CORRUPT
    assert reader.reads == []


def test_planning_enforces_ref_token_and_accepted_scope_bounds(tmp_path) -> None:
    catalog, lineage, ref, stored, _, _ = _bundle(
        tmp_path,
        candidate={"payload": "large-enough-for-token-budget"},
    )
    reader = RecordingGraphResultReader({ref: stored})
    strict_refs = GraphArtifactPersistenceConfig(max_context_artifact_refs=1)
    planner = ArtifactContextLoadPlanner(catalog=catalog, config=strict_refs)

    with pytest.raises(GraphArtifactResultError) as refs:
        planner.plan(
            _request(ref, mode=ContextLoadMode.SUMMARY_ONLY),
            accepted_lineages=(lineage,),
        )
    assert refs.value.error_code is GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED

    planner = ArtifactContextLoadPlanner(
        catalog=catalog,
        config=GraphArtifactPersistenceConfig(),
    )
    with pytest.raises(GraphArtifactResultError) as tokens:
        planner.plan(
            _request(
                ref,
                mode=ContextLoadMode.FULL,
                max_tokens=lineage.candidate_tokens - 1,
            ),
            accepted_lineages=(lineage,),
        )
    assert tokens.value.error_code is GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED

    foreign_run_projection = replace(lineage.artifact_refs[0], run_id="run-foreign")
    foreign_run = replace(
        lineage,
        run_id="run-foreign",
        artifact_refs=(foreign_run_projection,),
    )
    with pytest.raises(GraphArtifactResultError) as run_scope:
        planner.plan(
            _request(ref, mode=ContextLoadMode.SUMMARY_ONLY),
            accepted_lineages=(foreign_run,),
        )
    assert run_scope.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH

    foreign_tenant_projection = replace(
        lineage.artifact_refs[0],
        tenant_id="tenant-foreign",
    )
    foreign_tenant = replace(
        lineage,
        tenant_id="tenant-foreign",
        artifact_refs=(foreign_tenant_projection,),
    )
    with pytest.raises(GraphArtifactResultError) as tenant_scope:
        planner.plan(
            _request(ref, mode=ContextLoadMode.SUMMARY_ONLY),
            accepted_lineages=(foreign_tenant,),
        )
    assert tenant_scope.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH
    assert reader.reads == []


def test_sensitivity_and_context_policy_fail_closed_before_read(tmp_path) -> None:
    catalog, lineage, ref, stored, _, _ = _bundle(
        tmp_path,
        sensitivity=ResultSensitivity.RESTRICTED,
    )
    config = GraphArtifactPersistenceConfig()
    reader = RecordingGraphResultReader({ref: stored})
    planner = ArtifactContextLoadPlanner(catalog=catalog, config=config)

    with pytest.raises(GraphArtifactResultError) as restricted:
        planner.plan(
            _request(ref, mode=ContextLoadMode.FULL),
            accepted_lineages=(lineage,),
        )
    assert restricted.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH

    allowed = planner.plan(
        _request(
            ref,
            mode=ContextLoadMode.FULL,
            allowed_sensitivities=(ResultSensitivity.RESTRICTED,),
        ),
        accepted_lineages=(lineage,),
    )
    assert allowed.request.purpose is ContextPurpose.VERIFY

    summary_catalog, summary_lineage, summary_ref, summary_stored, _, _ = _bundle(
        tmp_path / "summary",
        context_policy=ContextPolicy.SUMMARY_ONLY,
    )
    summary_planner = ArtifactContextLoadPlanner(catalog=summary_catalog, config=config)
    with pytest.raises(GraphArtifactResultError) as policy:
        summary_planner.plan(
            _request(summary_ref, mode=ContextLoadMode.FULL),
            accepted_lineages=(summary_lineage,),
        )
    assert policy.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH

    secret_catalog, secret_lineage, secret_ref, secret_stored, _, _ = _bundle(
        tmp_path / "secret",
        sensitivity=ResultSensitivity.SECRET,
    )
    secret_reader = RecordingGraphResultReader({secret_ref: secret_stored})
    secret_planner = ArtifactContextLoadPlanner(catalog=secret_catalog, config=config)
    with pytest.raises(GraphArtifactResultError) as secret:
        secret_planner.plan(
            _request(
                secret_ref,
                mode=ContextLoadMode.SUMMARY_ONLY,
                allowed_sensitivities=(ResultSensitivity.SECRET,),
            ),
            accepted_lineages=(secret_lineage,),
        )
    assert secret.value.error_code is GraphArtifactResultErrorCode.SENSITIVE_PAYLOAD_REJECTED
    assert reader.reads == []
    assert secret_reader.reads == []


def test_tampered_physical_payload_returns_no_authorized_result(tmp_path) -> None:
    plan, loader, reader, _, _, _, ref = _plan_and_loader(
        tmp_path,
        mode=ContextLoadMode.FULL,
    )
    reader.payloads[ref]["payload"]["value"] = {"payload": "tampered"}

    with pytest.raises(GraphArtifactResultError) as exc_info:
        loader.load(plan)

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED
    assert reader.reads == [ref]


def test_context_assembler_accepts_only_provider_projection(tmp_path) -> None:
    plan, loader, _, _, _, _, ref = _plan_and_loader(
        tmp_path,
        mode=ContextLoadMode.SUMMARY_ONLY,
    )
    provider = StaticArtifactContextProvider(loader.load(plan))
    assembler = ContextAssembler(artifact_context_provider=provider)

    with pytest.raises(GraphArtifactResultError) as arbitrary:
        assembler.assemble({"artifact_refs": ("artifact://arbitrary",)})
    assert arbitrary.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH
    assert provider.calls == 0

    envelope = assembler.assemble(
        {
            "run_id": "run-1",
            "step_id": "consumer-node",
            "artifact_refs": (),
            "metadata": {},
        }
    )

    assert provider.calls == 1
    assert envelope.artifact_refs == (ref,)
    assert envelope.metadata["artifact_context_fingerprint"] == provider.result.context_fingerprint
    evidence_segment = next(
        segment for segment in envelope.segments if segment.segment_id == "evidence-memory"
    )
    assert evidence_segment.metadata["artifact_context"]["plan_checksum"] == plan.plan_checksum
    projection = provider.result.to_context_projection()
    assert evidence_segment.metadata["artifact_context"] == projection
    assert "source_byte_size" not in projection["items"][0]
    assert "media_type" not in projection["items"][0]
    assert evidence_segment.token_estimate > provider.result.total_loaded_tokens
