from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from business.research.domain import research_event_tenant_id
from framework.harness.artifacts.ports import (
    ArtifactCatalogPort,
    GraphResultArtifactReadPort,
)
from framework.harness.artifacts.governance import GraphArtifactUsagePort
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphCommitKind
from framework.harness.ports import HarnessTransitionPort
from framework.harness.runtime.artifact_context import (
    ArtifactContextLoadResult,
    ArtifactContextLoadPlanner,
    ArtifactContextLoader,
)
from framework.harness.runtime.result_models import (
    ArtifactClass,
    ContextAssemblyRequest,
    ContextLoadMode,
    ContextPurpose,
    ResultSensitivity,
)
from framework.harness.runtime.result_policy import GraphArtifactPersistenceConfig


@dataclass(frozen=True, slots=True)
class ResearchArtifactContextContract:
    node_id: str
    required_source_node_ids: tuple[str, ...]
    purpose: ContextPurpose
    load_mode: ContextLoadMode
    allowed_artifact_classes: tuple[ArtifactClass, ...]
    allowed_sensitivities: tuple[ResultSensitivity, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TypeError("node_id must be a non-blank string")
        source_node_ids = tuple(self.required_source_node_ids)
        if (
            not source_node_ids
            or not all(
                isinstance(item, str) and item and item == item.strip()
                for item in source_node_ids
            )
            or len(set(source_node_ids)) != len(source_node_ids)
        ):
            raise TypeError(
                "required_source_node_ids must contain unique non-blank node ids"
            )
        object.__setattr__(
            self,
            "required_source_node_ids",
            tuple(sorted(source_node_ids)),
        )
        if not isinstance(self.purpose, ContextPurpose):
            raise TypeError("purpose must be ContextPurpose")
        if not isinstance(self.load_mode, ContextLoadMode):
            raise TypeError("load_mode must be ContextLoadMode")
        if not self.allowed_artifact_classes or not all(
            isinstance(item, ArtifactClass) for item in self.allowed_artifact_classes
        ):
            raise TypeError("allowed_artifact_classes must contain ArtifactClass values")
        if not self.allowed_sensitivities or not all(
            isinstance(item, ResultSensitivity) for item in self.allowed_sensitivities
        ):
            raise TypeError("allowed_sensitivities must contain ResultSensitivity values")


RESEARCH_ARTIFACT_CONTEXT_CONTRACTS: Mapping[
    str,
    ResearchArtifactContextContract,
] = MappingProxyType(
    {
        "publish_artifacts": ResearchArtifactContextContract(
            node_id="publish_artifacts",
            required_source_node_ids=(
                "build_reader_payload",
                "build_paper_card",
                "quality_gate",
            ),
            purpose=ContextPurpose.VERIFY,
            load_mode=ContextLoadMode.SUMMARY_ONLY,
            allowed_artifact_classes=(
                ArtifactClass.EVIDENCE,
                ArtifactClass.INTERMEDIATE,
            ),
            allowed_sensitivities=(
                ResultSensitivity.PUBLIC,
                ResultSensitivity.INTERNAL,
            ),
        )
    }
)


class ResearchGraphArtifactContextProvider:
    """Build context only from projected, durable Research graph result commits."""

    def __init__(
        self,
        *,
        event_port: HarnessTransitionPort,
        catalog: ArtifactCatalogPort,
        reader: GraphResultArtifactReadPort,
        usage: GraphArtifactUsagePort,
        config: GraphArtifactPersistenceConfig,
        contracts: Mapping[str, ResearchArtifactContextContract] = (
            RESEARCH_ARTIFACT_CONTEXT_CONTRACTS
        ),
    ) -> None:
        if not isinstance(event_port, HarnessTransitionPort):
            raise TypeError("event_port must implement HarnessTransitionPort")
        normalized = dict(contracts)
        if not normalized or any(
            node_id != contract.node_id
            or not isinstance(contract, ResearchArtifactContextContract)
            for node_id, contract in normalized.items()
        ):
            raise TypeError("contracts must map node ids to context contracts")
        self._event_port = event_port
        self._config = config
        self._contracts = MappingProxyType(dict(sorted(normalized.items())))
        self._planner = ArtifactContextLoadPlanner(catalog=catalog, config=config)
        self._loader = ArtifactContextLoader(
            reader=reader,
            usage=usage,
            config=config,
        )

    def load_artifact_context(
        self,
        request: Mapping[str, Any],
    ) -> ArtifactContextLoadResult:
        run_id = _required_text(request.get("run_id"), "run_id")
        node_id = _required_text(request.get("step_id"), "step_id")
        contract = self._contracts.get(node_id)
        if contract is None:
            raise HarnessValidationError(
                "Research node has no approved artifact context contract",
                code="research_artifact_context_contract_missing",
                details={"node_id": node_id},
            )
        metadata = request.get("metadata")
        if not isinstance(metadata, Mapping):
            raise HarnessValidationError(
                "Research artifact context requires actor metadata",
                code="research_artifact_context_scope_missing",
            )
        tenant_id = research_event_tenant_id(metadata)
        recover_graph = getattr(self._event_port, "recover_graph", None)
        if not callable(recover_graph):
            raise HarnessValidationError(
                "Research artifact context requires graph recovery",
                code="research_artifact_context_recovery_unavailable",
            )
        recovery = recover_graph(run_id)
        if recovery.graph is None or recovery.state is None:
            raise HarnessValidationError(
                "Research artifact context graph is not initialized",
                code="research_artifact_context_recovery_incomplete",
            )
        projected_results = {
            projection.cause_checksum
            for projection in recovery.projection_commits
            if projection.commit_kind
            is HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION
        }
        latest_by_node = {}
        for commit in recovery.activity_result_commits:
            lineage = commit.result.result_lineage
            if (
                commit.result.result_checksum not in projected_results
                or lineage is None
                or lineage.node_id not in contract.required_source_node_ids
            ):
                continue
            latest_by_node[lineage.node_id] = (commit.sequence, lineage)
        missing_source_nodes = sorted(
            set(contract.required_source_node_ids).difference(latest_by_node)
        )
        if missing_source_nodes:
            raise HarnessValidationError(
                "Research artifact context is missing required source results",
                code="research_artifact_context_source_missing",
                details={
                    "node_id": node_id,
                    "missing_source_node_ids": missing_source_nodes,
                },
            )
        lineages = tuple(
            sorted(
                (item[1] for item in latest_by_node.values()),
                key=lambda item: item.lineage_checksum,
            )
        )
        artifact_refs = tuple(
            sorted(
                {
                    ref.ref
                    for lineage in lineages
                    for ref in lineage.artifact_refs
                    if ArtifactClass(ref.artifact_class)
                    in contract.allowed_artifact_classes
                }
            )
        )
        typed_request = ContextAssemblyRequest(
            tenant_id=tenant_id,
            run_id=run_id,
            graph_id=recovery.graph.graph_id,
            node_id=node_id,
            purpose=contract.purpose,
            allowed_artifact_classes=contract.allowed_artifact_classes,
            allowed_sensitivities=contract.allowed_sensitivities,
            artifact_refs=artifact_refs,
            max_refs=self._config.max_context_artifact_refs,
            max_bytes=self._config.max_context_loaded_bytes,
            max_tokens=self._config.max_context_loaded_tokens,
            load_mode=contract.load_mode,
        )
        plan = self._planner.plan(
            typed_request,
            accepted_lineages=lineages,
        )
        return self._loader.load(plan)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HarnessValidationError(
            f"Research artifact context {field_name} is required",
            code="research_artifact_context_request_invalid",
            details={"field": field_name},
        )
    return value


__all__ = [
    "RESEARCH_ARTIFACT_CONTEXT_CONTRACTS",
    "ResearchArtifactContextContract",
    "ResearchGraphArtifactContextProvider",
]
