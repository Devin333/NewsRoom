from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import HarnessSideEffectHandlerReference
from framework.harness.graph.dsl import HarnessGraphSpec
from framework.harness.workflow.spec import HarnessRoutingRule, HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessRetryPolicy, HarnessStepSpec
from framework.harness.graph.versioning import (
    HARNESS_GRAPH_DSL_SCHEMA,
)
from framework.harness.workflow.versioning import (
    DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY,
    LEGACY_WORKFLOW_SCHEMA,
    HarnessGraphContractKind,
    HarnessGraphSchemaRegistry,
)


class HarnessWorkflowContractReader:
    def __init__(
        self,
        registry: HarnessGraphSchemaRegistry = DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY,
    ) -> None:
        if not isinstance(registry, HarnessGraphSchemaRegistry):
            raise TypeError("registry must be HarnessGraphSchemaRegistry")
        self._registry = registry

    def read(
        self,
        payload: Mapping[str, Any],
        *,
        source_schema: str,
    ) -> HarnessWorkflowSpec:
        self._registry.require_readable(HarnessGraphContractKind.WORKFLOW, source_schema)
        if source_schema == LEGACY_WORKFLOW_SCHEMA:
            return self._read_legacy(payload)
        if source_schema == HARNESS_GRAPH_DSL_SCHEMA:
            return self._read_graph(payload)
        raise HarnessValidationError(
            "workflow reader has no exact reader for schema",
            code="unsupported_graph_schema",
            details={"schema": str(source_schema)},
        )

    def read_for_execution(
        self,
        payload: Mapping[str, Any],
        *,
        source_schema: str,
    ) -> HarnessWorkflowSpec:
        self._registry.require_executable(HarnessGraphContractKind.WORKFLOW, source_schema)
        workflow = self.read(payload, source_schema=source_schema)
        if workflow.graph is None:
            raise HarnessValidationError(
                "legacy workflow must be compiled before graph execution",
                code="legacy_workflow_not_compiled",
            )
        return workflow

    def _read_legacy(self, payload: Mapping[str, Any]) -> HarnessWorkflowSpec:
        _exact_keys(
            payload,
            {
                "workflow_id",
                "steps",
                "entry_step_id",
                "terminal_policies",
                "routing_rules",
                "metadata",
            },
            "legacy workflow",
        )
        metadata = _mapping(payload["metadata"], "workflow.metadata")
        return HarnessWorkflowSpec(
            workflow_id=payload["workflow_id"],
            workflow_version=metadata.get("version", "1"),
            steps=tuple(
                _read_step(item)
                for item in _array(payload["steps"], "workflow.steps")
            ),
            entry_step_id=payload["entry_step_id"],
            terminal_policies=dict(
                _mapping(payload["terminal_policies"], "workflow.terminal_policies")
            ),
            routing_rules=tuple(
                _read_route(item)
                for item in _array(payload["routing_rules"], "workflow.routing_rules")
            ),
            metadata=dict(metadata),
        )

    def _read_graph(self, payload: Mapping[str, Any]) -> HarnessWorkflowSpec:
        _exact_keys(
            payload,
            {
                "workflow_id",
                "workflow_version",
                "schema_version",
                "steps",
                "entry_step_id",
                "terminal_policies",
                "routing_rules",
                "metadata",
                "graph",
            },
            "graph workflow",
        )
        if payload["schema_version"] != HARNESS_GRAPH_DSL_SCHEMA:
            raise HarnessValidationError(
                "graph workflow payload schema does not match reader schema",
                code="graph_schema_mismatch",
            )
        routes = _array(payload["routing_rules"], "workflow.routing_rules")
        if routes:
            raise HarnessValidationError(
                "graph workflow cannot contain legacy routing rules",
                code="ambiguous_workflow_declaration",
            )
        return HarnessWorkflowSpec(
            workflow_id=payload["workflow_id"],
            workflow_version=payload["workflow_version"],
            steps=tuple(
                _read_step(item)
                for item in _array(payload["steps"], "workflow.steps")
            ),
            entry_step_id=payload["entry_step_id"],
            terminal_policies=dict(
                _mapping(payload["terminal_policies"], "workflow.terminal_policies")
            ),
            routing_rules=(),
            metadata=dict(_mapping(payload["metadata"], "workflow.metadata")),
            graph=HarnessGraphSpec.from_dict(_mapping(payload["graph"], "workflow.graph")),
        )


def _read_step(value: Mapping[str, Any]) -> HarnessStepSpec:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            "workflow step must be an object",
            code="invalid_workflow_contract",
        )
    allowed = {
        "step_id",
        "worker_type",
        "input_keys",
        "output_key",
        "retry_policy",
        "quality_gate",
        "metadata",
        "side_effect_handler",
    }
    unknown = set(value).difference(allowed)
    required = allowed.difference({"side_effect_handler"})
    missing = required.difference(value)
    if missing or unknown:
        raise HarnessValidationError(
            "workflow step fields do not match its schema",
            code="invalid_workflow_contract",
            details={"missing": sorted(missing), "unknown": sorted(str(item) for item in unknown)},
        )
    retry = _mapping(value["retry_policy"], "step.retry_policy")
    _exact_keys(
        retry,
        {
            "max_retries",
            "max_attempts",
            "effective_max_attempts",
            "retry_on_statuses",
            "backoff_seconds",
            "repair_step_id",
            "fail_fast_error_types",
        },
        "retry policy",
    )
    policy = HarnessRetryPolicy(
        max_retries=retry["max_retries"],
        max_attempts=retry["max_attempts"],
        retry_on_statuses=tuple(_array(retry["retry_on_statuses"], "retry.retry_on_statuses")),
        backoff_seconds=retry["backoff_seconds"],
        repair_step_id=retry["repair_step_id"],
        fail_fast_error_types=tuple(
            _array(retry["fail_fast_error_types"], "retry.fail_fast_error_types")
        ),
    )
    if policy.effective_max_attempts != retry["effective_max_attempts"]:
        raise HarnessValidationError(
            "retry policy effective_max_attempts is inconsistent",
            code="retry_policy_projection_mismatch",
            details={"step_id": str(value["step_id"])},
        )
    side_effect = value.get("side_effect_handler")
    return HarnessStepSpec(
        step_id=value["step_id"],
        worker_type=value["worker_type"],
        input_keys=tuple(_array(value["input_keys"], "step.input_keys")),
        output_key=value["output_key"],
        retry_policy=policy,
        quality_gate=value["quality_gate"],
        metadata=dict(_mapping(value["metadata"], "step.metadata")),
        side_effect_handler=(
            None
            if side_effect is None
            else HarnessSideEffectHandlerReference.parse(side_effect)
        ),
    )


def _read_route(value: Mapping[str, Any]) -> HarnessRoutingRule:
    _exact_keys(value, {"from_step", "to_step", "kind", "condition"}, "routing rule")
    return HarnessRoutingRule(
        from_step=value["from_step"],
        to_step=value["to_step"],
        kind=value["kind"],
        condition=dict(_mapping(value["condition"], "routing_rule.condition")),
    )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_workflow_contract",
        )
    return value


def _array(value: Any, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="invalid_workflow_contract",
        )
    return tuple(value)


def _exact_keys(value: Mapping[str, Any], expected: set[str], field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_workflow_contract",
        )
    actual = set(value)
    if actual != expected:
        raise HarnessValidationError(
            f"{field_name} fields do not match its schema",
            code="invalid_workflow_contract",
            details={
                "missing": sorted(expected.difference(actual)),
                "unknown": sorted(str(item) for item in actual.difference(expected)),
            },
        )


__all__ = ["HarnessWorkflowContractReader"]
