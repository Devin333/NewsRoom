from __future__ import annotations

from dataclasses import dataclass

from framework.harness.workflow.compiler import (
    HarnessGraphCompileResult,
    HarnessWorkflowGraphCompiler,
)
from framework.harness.workflow.graph import NormalizedHarnessGraph
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workflow.validation.dataflow import validate_dataflow
from framework.harness.workflow.validation.models import (
    HarnessGraphDiagnostic,
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
from framework.harness.workflow.versioning import (
    DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
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
