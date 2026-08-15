from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from framework.harness.workflow.compiler import (
    HarnessGraphCompileResult,
    HarnessWorkflowGraphCompiler,
)
from framework.harness.graph.model import HarnessExecutableNode, NormalizedHarnessGraph
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessWorkerType
from framework.harness.workflow.validation.dataflow import validate_dataflow
from framework.harness.workflow.validation.models import (
    HarnessGraphDiagnostic,
    HarnessGraphValidationPhase,
    HarnessGraphValidationResult,
)
from framework.harness.workflow.validation.policy import (
    HarnessGraphPreflightPolicy,
    validate_policy,
)
from framework.harness.workflow.validation.registry import (
    HarnessGraphRegistrySnapshot,
    validate_registry,
)
from framework.harness.workflow.validation.semantic import validate_semantics
from framework.harness.workflow.validation.structural import validate_structure
from framework.harness.graph.versioning import (
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)
from framework.harness.workflow.versioning import (
    DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY,
    HarnessGraphContractKind,
)
@dataclass(frozen=True, slots=True)
class HarnessPreparedGraph:
    compile_result: HarnessGraphCompileResult
    validation: HarnessGraphValidationResult

    @property
    def graph(self) -> NormalizedHarnessGraph:
        return self.compile_result.graph

    @property
    def is_valid(self) -> bool:
        return self.validation.is_valid

    def require_valid(self) -> NormalizedHarnessGraph:
        self.validation.raise_if_invalid()
        return self.graph


class HarnessGraphPreflight:
    def __init__(
        self,
        *,
        compiler: HarnessWorkflowGraphCompiler | None = None,
        policy: HarnessGraphPreflightPolicy | None = None,
    ) -> None:
        self.compiler = compiler or HarnessWorkflowGraphCompiler()
        self.policy = policy or HarnessGraphPreflightPolicy()

    def prepare(
        self,
        workflow: HarnessWorkflowSpec,
        *,
        registry: HarnessGraphRegistrySnapshot,
    ) -> HarnessPreparedGraph:
        compile_result = self.compiler.compile(workflow)
        validation = self.validate(compile_result.graph, registry=registry)
        return HarnessPreparedGraph(compile_result=compile_result, validation=validation)

    def validate(
        self,
        graph: NormalizedHarnessGraph,
        *,
        registry: HarnessGraphRegistrySnapshot,
    ) -> HarnessGraphValidationResult:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if not isinstance(registry, HarnessGraphRegistrySnapshot):
            raise TypeError("registry must be HarnessGraphRegistrySnapshot")
        self._require_executable_schema(graph)
        diagnostics: list[HarnessGraphDiagnostic] = []
        diagnostics.extend(validate_structure(graph))
        diagnostics.extend(validate_semantics(graph))
        diagnostics.extend(validate_dataflow(graph))
        diagnostics.extend(validate_registry(graph, registry, self.policy))
        diagnostics.extend(validate_policy(graph, self.policy))
        diagnostics.extend(_validate_dynamic_task_plan_declarations(graph))
        return self._result(graph, diagnostics)

    def validate_static(
        self,
        graph: NormalizedHarnessGraph,
    ) -> HarnessGraphValidationResult:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        self._require_executable_schema(graph)
        diagnostics: list[HarnessGraphDiagnostic] = []
        diagnostics.extend(validate_structure(graph))
        diagnostics.extend(validate_semantics(graph))
        diagnostics.extend(validate_dataflow(graph))
        diagnostics.extend(validate_policy(graph, self.policy))
        diagnostics.extend(_validate_dynamic_task_plan_declarations(graph))
        return self._result(graph, diagnostics)

    @staticmethod
    def _require_executable_schema(graph: NormalizedHarnessGraph) -> None:
        DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY.require_executable(
            HarnessGraphContractKind.NORMALIZED_GRAPH,
            graph.schema_version,
        )
        if graph.schema_version != NORMALIZED_HARNESS_GRAPH_SCHEMA:
            raise AssertionError(
                "schema registry accepted an unexpected normalized graph schema"
            )

    def _result(
        self,
        graph: NormalizedHarnessGraph,
        diagnostics: list[HarnessGraphDiagnostic],
    ) -> HarnessGraphValidationResult:
        ordered = tuple(sorted(diagnostics, key=lambda item: item.sort_key))
        truncated = len(ordered) > self.policy.max_diagnostics
        if truncated:
            ordered = ordered[: self.policy.max_diagnostics]
        return HarnessGraphValidationResult(
            graph_checksum=graph.checksum or "",
            diagnostics=ordered,
            truncated=truncated,
        )


__all__ = ["HarnessGraphPreflight", "HarnessPreparedGraph"]


_EXACT_REFERENCE_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:/+-]*@[A-Za-z0-9][A-Za-z0-9._+-]*\Z"
)
_EXACT_SCHEMA_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:/+-]*/v[1-9][0-9]*\Z"
)
_MOVING_VERSION_ALIASES = frozenset({"current", "default", "latest", "stable"})
_TASK_PLAN_SUPPORT_REFS = (
    "candidate_builder_ref",
    "capability_registry_ref",
    "gate_registry_ref",
    "aggregator_ref",
    "checkpoint_ref",
    "result_store_ref",
)


def _validate_dynamic_task_plan_declarations(
    graph: NormalizedHarnessGraph,
) -> list[HarnessGraphDiagnostic]:
    required_support = (*_TASK_PLAN_SUPPORT_REFS, "event_schema")
    diagnostics: list[HarnessGraphDiagnostic] = []
    for node in graph.nodes:
        if not isinstance(node, HarnessExecutableNode):
            continue
        declaration = _task_plan_step_metadata(node)
        worker_type = node.metadata.get("worker_type")
        is_task_plan_worker = worker_type == HarnessWorkerType.TASK_PLAN.value
        is_dynamic_stage = declaration.get("dynamic_stage") is True
        if not is_task_plan_worker and not is_dynamic_stage:
            continue
        if not is_task_plan_worker:
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_worker_type_mismatch",
                    "dynamic TaskPlan stage must use HarnessWorkerType.TASK_PLAN",
                    node=node,
                    path="metadata.worker_type",
                )
            )
        if not is_dynamic_stage:
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_stage_marker_missing",
                    "TASK_PLAN worker must be explicitly declared as a dynamic stage",
                    node=node,
                    path="metadata.step_metadata.dynamic_stage",
                )
            )
        if node.side_effect_ref is not None:
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_side_effect_forbidden",
                    "dynamic TaskPlan stage cannot own a side-effect handler",
                    node=node,
                    path="side_effect_ref",
                )
            )

        policy_ref = declaration.get("task_plan_policy_ref")
        if not _is_exact_reference(policy_ref):
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_policy_missing_or_inexact",
                    "dynamic TaskPlan stage requires an exact policy ref",
                    node=node,
                    path="metadata.step_metadata.task_plan_policy_ref",
                )
            )

        task_plan_schema = declaration.get("task_plan_schema")
        if not _is_exact_schema(task_plan_schema):
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_schema_missing_or_inexact",
                    "dynamic TaskPlan stage requires an exact executable schema",
                    node=node,
                    path="metadata.step_metadata.task_plan_schema",
                )
            )

        roles = declaration.get("required_output_roles")
        if (
            not isinstance(roles, (tuple, list))
            or not roles
            or any(not isinstance(item, str) or not item.strip() for item in roles)
            or len(set(roles)) != len(roles)
        ):
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_required_roles_invalid",
                    "dynamic TaskPlan stage requires a non-empty unique output-role set",
                    node=node,
                    path="metadata.step_metadata.required_output_roles",
                )
            )

        support = declaration.get("task_plan_support")
        if not isinstance(support, Mapping):
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_support_missing",
                    "dynamic TaskPlan stage must declare builder, binding, gate, aggregation, event, checkpoint and result support",
                    node=node,
                    path="metadata.step_metadata.task_plan_support",
                )
            )
            continue
        missing = tuple(
            key
            for key in required_support
            if not isinstance(support.get(key), str) or not support[key].strip()
        )
        if missing:
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_support_incomplete",
                    "dynamic TaskPlan support declarations are incomplete",
                    node=node,
                    details={"missing": missing},
                )
            )
        inexact = tuple(
            key
            for key in _TASK_PLAN_SUPPORT_REFS
            if key not in missing and not _is_exact_reference(support.get(key))
        )
        if inexact:
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_support_inexact",
                    "dynamic TaskPlan support references must pin exact versions",
                    node=node,
                    details={"inexact": inexact},
                )
            )
        if "event_schema" not in missing and not _is_exact_schema(
            support.get("event_schema")
        ):
            diagnostics.append(
                _task_plan_diagnostic(
                    "dynamic_task_plan_event_schema_inexact",
                    "dynamic TaskPlan event support must pin one exact schema version",
                    node=node,
                    path="metadata.step_metadata.task_plan_support.event_schema",
                )
            )
    return diagnostics


def _task_plan_step_metadata(node: HarnessExecutableNode) -> Mapping[str, object]:
    value = node.metadata.get("step_metadata")
    if isinstance(value, Mapping):
        return value
    # Accept the early normalized-graph shape for read compatibility. New
    # compiler output always nests HarnessStepSpec.metadata under step_metadata.
    return node.metadata


def _is_exact_reference(value: object) -> bool:
    if not isinstance(value, str) or _EXACT_REFERENCE_PATTERN.fullmatch(value) is None:
        return False
    return value.rsplit("@", 1)[-1].casefold() not in _MOVING_VERSION_ALIASES


def _is_exact_schema(value: object) -> bool:
    return isinstance(value, str) and _EXACT_SCHEMA_PATTERN.fullmatch(value) is not None


def _task_plan_diagnostic(
    code: str,
    message: str,
    *,
    node: HarnessExecutableNode,
    path: str | None = None,
    details: Mapping[str, object] | None = None,
) -> HarnessGraphDiagnostic:
    return HarnessGraphDiagnostic(
        HarnessGraphValidationPhase.CONTRACT,
        code,
        message,
        node_id=node.node_id,
        path=path,
        details={} if details is None else details,
    )
