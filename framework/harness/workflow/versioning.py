from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.canonical import required_text


HARNESS_GRAPH_RUNTIME_VERSION = "newsroom.harness-graph-runtime/v2"
HARNESS_GRAPH_DSL_SCHEMA = "newsroom.harness-workflow-graph/v1"
NORMALIZED_HARNESS_GRAPH_SCHEMA = "newsroom.harness-normalized-graph/v1"
HARNESS_GRAPH_STATE_SCHEMA = "newsroom.harness-graph-state/v1"
HARNESS_GRAPH_DECISION_SCHEMA = "newsroom.harness-graph-decision/v1"
HARNESS_GRAPH_CHECKPOINT_SCHEMA = "newsroom.harness-graph-checkpoint/v1"
HARNESS_GRAPH_INSPECTION_SCHEMA = "newsroom.harness-graph-inspection/v1"
HARNESS_CONDITION_POLICY_VERSION = "newsroom.harness-graph-condition-policy/v1"
HARNESS_GRAPH_COMPILER_VERSION = "newsroom.harness-graph-compiler/v1"
HARNESS_GRAPH_EVALUATOR_VERSION = "newsroom.harness-graph-evaluator/v1"
HARNESS_STEP_LIFECYCLE_VERSION = "newsroom.harness-step-lifecycle/v1"
HARNESS_GRAPH_REDUCER_VERSION = "newsroom.harness-graph-state-reducer/v1"
HARNESS_GRAPH_CONTROL_POLICY_VERSION = "newsroom.harness-graph-control-policy/v1"
HARNESS_GRAPH_MERGE_VERSION = "newsroom.harness-graph-merge/v1"
HARNESS_WORKER_ACTIVITY_SCHEMA = "newsroom.harness-worker-activity/v1"

LEGACY_WORKFLOW_SCHEMA = "newsroom.harness-workflow-legacy/v1"
LEGACY_STATE_SCHEMA = "newsroom.harness-state-legacy/v1"
LEGACY_DECISION_SCHEMA = "newsroom.harness-decision-legacy/v1"
LEGACY_CHECKPOINT_SCHEMA = "newsroom.harness-checkpoint-legacy/v1"
LEGACY_EVENT_SCHEMA = "newsroom.harness-event/v1"

HARNESS_GRAPH_EVENT_SCHEMAS: Mapping[str, str] = MappingProxyType(
    {
        "harness_graph_created": "newsroom.harness-graph-created/v1",
        "harness_graph_decision_committed": HARNESS_GRAPH_DECISION_SCHEMA,
        "harness_graph_node_activated": "newsroom.harness-graph-node-activated/v1",
        "harness_graph_node_terminal": "newsroom.harness-graph-node-terminal/v1",
        "harness_graph_choice_selected": "newsroom.harness-graph-choice-selected/v1",
        "harness_graph_fork_opened": "newsroom.harness-graph-fork-opened/v1",
        "harness_graph_join_satisfied": "newsroom.harness-graph-join-satisfied/v1",
        "harness_graph_loop_transitioned": "newsroom.harness-graph-loop-transition/v1",
        "harness_graph_wait_transitioned": "newsroom.harness-graph-wait-transition/v1",
        "harness_graph_winner_selected": "newsroom.harness-graph-winner-selected/v1",
        "harness_graph_cancellation_transitioned": "newsroom.harness-graph-cancellation-transition/v1",
        "harness_graph_compensation_transitioned": "newsroom.harness-graph-compensation-transition/v1",
        "harness_graph_budget_transitioned": "newsroom.harness-graph-budget-transition/v1",
        "harness_graph_run_lifecycle_transitioned": "newsroom.harness-graph-run-lifecycle-transition/v1",
    }
)
HARNESS_GRAPH_EVENT_SCHEMA = HARNESS_GRAPH_EVENT_SCHEMAS["harness_graph_created"]


class HarnessGraphContractKind(StrEnum):
    WORKFLOW = "workflow"
    GRAPH_DSL = "graph_dsl"
    NORMALIZED_GRAPH = "normalized_graph"
    GRAPH_STATE = "graph_state"
    GRAPH_DECISION = "graph_decision"
    GRAPH_CHECKPOINT = "graph_checkpoint"
    GRAPH_EVENT = "graph_event"
    GRAPH_INSPECTION = "graph_inspection"


@dataclass(frozen=True, slots=True)
class HarnessGraphSchemaRegistration:
    contract_kind: HarnessGraphContractKind | str
    writer_schema: str
    readable_schemas: tuple[str, ...]
    executable_schemas: tuple[str, ...]
    legacy_upcast_sources: tuple[str, ...] = ()
    additional_writer_schemas: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        kind = HarnessGraphContractKind(self.contract_kind)
        writer = required_text(self.writer_schema, "writer_schema")
        readable = tuple(
            required_text(item, "readable_schemas") for item in self.readable_schemas
        )
        executable = tuple(
            required_text(item, "executable_schemas")
            for item in self.executable_schemas
        )
        upcast_sources = tuple(
            required_text(item, "legacy_upcast_sources")
            for item in self.legacy_upcast_sources
        )
        additional_writers = tuple(
            required_text(item, "additional_writer_schemas")
            for item in self.additional_writer_schemas
        )
        if len(set(readable)) != len(readable):
            raise HarnessValidationError(
                "readable_schemas must not contain duplicates",
                code="duplicate_graph_schema_registration",
            )
        if len(set(executable)) != len(executable):
            raise HarnessValidationError(
                "executable_schemas must not contain duplicates",
                code="duplicate_graph_schema_registration",
            )
        writers = (writer, *additional_writers)
        if len(set(writers)) != len(writers):
            raise HarnessValidationError(
                "writer schemas must not contain duplicates",
                code="duplicate_graph_schema_registration",
            )
        if not set(writers).issubset(readable) or not set(writers).issubset(executable):
            raise HarnessValidationError(
                "writer schemas must be both readable and executable",
                code="invalid_graph_writer_schema",
                details={"contract_kind": kind.value, "writer_schemas": list(writers)},
            )
        if not set(executable).issubset(readable):
            raise HarnessValidationError(
                "every executable schema must also be readable",
                code="invalid_graph_executable_schema",
                details={"contract_kind": kind.value},
            )
        if not set(upcast_sources).issubset(readable):
            raise HarnessValidationError(
                "legacy upcast sources must be readable",
                code="invalid_graph_upcast_source",
                details={"contract_kind": kind.value},
            )
        object.__setattr__(self, "contract_kind", kind)
        object.__setattr__(self, "writer_schema", writer)
        object.__setattr__(self, "readable_schemas", readable)
        object.__setattr__(self, "executable_schemas", executable)
        object.__setattr__(self, "legacy_upcast_sources", upcast_sources)
        object.__setattr__(self, "additional_writer_schemas", additional_writers)

    @property
    def writer_schemas(self) -> tuple[str, ...]:
        return (self.writer_schema, *self.additional_writer_schemas)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_kind": self.contract_kind.value,
            "writer_schema": self.writer_schema,
            "writer_schemas": list(self.writer_schemas),
            "readable_schemas": list(self.readable_schemas),
            "executable_schemas": list(self.executable_schemas),
            "legacy_upcast_sources": list(self.legacy_upcast_sources),
        }


class HarnessGraphSchemaRegistry:
    def __init__(
        self, registrations: tuple[HarnessGraphSchemaRegistration, ...]
    ) -> None:
        by_kind: dict[HarnessGraphContractKind, HarnessGraphSchemaRegistration] = {}
        for registration in registrations:
            if not isinstance(registration, HarnessGraphSchemaRegistration):
                raise TypeError(
                    "registrations must contain HarnessGraphSchemaRegistration values"
                )
            if registration.contract_kind in by_kind:
                raise HarnessValidationError(
                    "graph schema contract kind is already registered",
                    code="duplicate_graph_contract_kind",
                    details={"contract_kind": registration.contract_kind.value},
                )
            by_kind[registration.contract_kind] = registration
        expected = frozenset(HarnessGraphContractKind)
        if frozenset(by_kind) != expected:
            missing = sorted(kind.value for kind in expected.difference(by_kind))
            raise HarnessValidationError(
                "graph schema registry is incomplete",
                code="incomplete_graph_schema_registry",
                details={"missing": missing},
            )
        self._by_kind: Mapping[
            HarnessGraphContractKind, HarnessGraphSchemaRegistration
        ] = MappingProxyType(by_kind)

    @property
    def registrations(self) -> tuple[HarnessGraphSchemaRegistration, ...]:
        return tuple(self._by_kind[kind] for kind in HarnessGraphContractKind)

    def registration_for(
        self,
        contract_kind: HarnessGraphContractKind | str,
    ) -> HarnessGraphSchemaRegistration:
        return self._by_kind[HarnessGraphContractKind(contract_kind)]

    def require_readable(
        self,
        contract_kind: HarnessGraphContractKind | str,
        schema: str,
    ) -> HarnessGraphSchemaRegistration:
        registration = self.registration_for(contract_kind)
        if schema not in registration.readable_schemas:
            raise HarnessValidationError(
                "unsupported graph contract schema",
                code="unsupported_graph_schema",
                details={
                    "contract_kind": registration.contract_kind.value,
                    "schema": str(schema),
                },
            )
        return registration

    def require_executable(
        self,
        contract_kind: HarnessGraphContractKind | str,
        schema: str,
    ) -> HarnessGraphSchemaRegistration:
        registration = self.require_readable(contract_kind, schema)
        if schema not in registration.executable_schemas:
            raise HarnessValidationError(
                "graph contract schema is read-only and cannot execute",
                code="graph_schema_not_executable",
                details={
                    "contract_kind": registration.contract_kind.value,
                    "schema": str(schema),
                },
            )
        return registration

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_version": HARNESS_GRAPH_RUNTIME_VERSION,
            "registrations": [
                registration.to_dict() for registration in self.registrations
            ],
        }


DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY = HarnessGraphSchemaRegistry(
    (
        HarnessGraphSchemaRegistration(
            contract_kind=HarnessGraphContractKind.WORKFLOW,
            writer_schema=HARNESS_GRAPH_DSL_SCHEMA,
            readable_schemas=(LEGACY_WORKFLOW_SCHEMA, HARNESS_GRAPH_DSL_SCHEMA),
            executable_schemas=(HARNESS_GRAPH_DSL_SCHEMA,),
            legacy_upcast_sources=(LEGACY_WORKFLOW_SCHEMA,),
        ),
        HarnessGraphSchemaRegistration(
            contract_kind=HarnessGraphContractKind.GRAPH_DSL,
            writer_schema=HARNESS_GRAPH_DSL_SCHEMA,
            readable_schemas=(HARNESS_GRAPH_DSL_SCHEMA,),
            executable_schemas=(HARNESS_GRAPH_DSL_SCHEMA,),
        ),
        HarnessGraphSchemaRegistration(
            contract_kind=HarnessGraphContractKind.NORMALIZED_GRAPH,
            writer_schema=NORMALIZED_HARNESS_GRAPH_SCHEMA,
            readable_schemas=(NORMALIZED_HARNESS_GRAPH_SCHEMA,),
            executable_schemas=(NORMALIZED_HARNESS_GRAPH_SCHEMA,),
        ),
        HarnessGraphSchemaRegistration(
            contract_kind=HarnessGraphContractKind.GRAPH_STATE,
            writer_schema=HARNESS_GRAPH_STATE_SCHEMA,
            readable_schemas=(LEGACY_STATE_SCHEMA, HARNESS_GRAPH_STATE_SCHEMA),
            executable_schemas=(HARNESS_GRAPH_STATE_SCHEMA,),
            legacy_upcast_sources=(LEGACY_STATE_SCHEMA,),
        ),
        HarnessGraphSchemaRegistration(
            contract_kind=HarnessGraphContractKind.GRAPH_DECISION,
            writer_schema=HARNESS_GRAPH_DECISION_SCHEMA,
            readable_schemas=(LEGACY_DECISION_SCHEMA, HARNESS_GRAPH_DECISION_SCHEMA),
            executable_schemas=(HARNESS_GRAPH_DECISION_SCHEMA,),
            legacy_upcast_sources=(LEGACY_DECISION_SCHEMA,),
        ),
        HarnessGraphSchemaRegistration(
            contract_kind=HarnessGraphContractKind.GRAPH_CHECKPOINT,
            writer_schema=HARNESS_GRAPH_CHECKPOINT_SCHEMA,
            readable_schemas=(
                LEGACY_CHECKPOINT_SCHEMA,
                HARNESS_GRAPH_CHECKPOINT_SCHEMA,
            ),
            executable_schemas=(HARNESS_GRAPH_CHECKPOINT_SCHEMA,),
            legacy_upcast_sources=(LEGACY_CHECKPOINT_SCHEMA,),
        ),
        HarnessGraphSchemaRegistration(
            contract_kind=HarnessGraphContractKind.GRAPH_EVENT,
            writer_schema=HARNESS_GRAPH_EVENT_SCHEMA,
            additional_writer_schemas=tuple(HARNESS_GRAPH_EVENT_SCHEMAS.values())[1:],
            readable_schemas=(
                LEGACY_EVENT_SCHEMA,
                *tuple(HARNESS_GRAPH_EVENT_SCHEMAS.values()),
            ),
            executable_schemas=tuple(HARNESS_GRAPH_EVENT_SCHEMAS.values()),
            legacy_upcast_sources=(LEGACY_EVENT_SCHEMA,),
        ),
        HarnessGraphSchemaRegistration(
            contract_kind=HarnessGraphContractKind.GRAPH_INSPECTION,
            writer_schema=HARNESS_GRAPH_INSPECTION_SCHEMA,
            readable_schemas=(HARNESS_GRAPH_INSPECTION_SCHEMA,),
            executable_schemas=(HARNESS_GRAPH_INSPECTION_SCHEMA,),
        ),
    )
)


__all__ = [
    "DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY",
    "HARNESS_CONDITION_POLICY_VERSION",
    "HARNESS_GRAPH_CHECKPOINT_SCHEMA",
    "HARNESS_GRAPH_COMPILER_VERSION",
    "HARNESS_GRAPH_CONTROL_POLICY_VERSION",
    "HARNESS_GRAPH_DECISION_SCHEMA",
    "HARNESS_GRAPH_DSL_SCHEMA",
    "HARNESS_GRAPH_EVALUATOR_VERSION",
    "HARNESS_GRAPH_EVENT_SCHEMA",
    "HARNESS_GRAPH_EVENT_SCHEMAS",
    "HARNESS_GRAPH_INSPECTION_SCHEMA",
    "HARNESS_GRAPH_MERGE_VERSION",
    "HARNESS_GRAPH_REDUCER_VERSION",
    "HARNESS_GRAPH_RUNTIME_VERSION",
    "HARNESS_GRAPH_STATE_SCHEMA",
    "HARNESS_STEP_LIFECYCLE_VERSION",
    "HARNESS_WORKER_ACTIVITY_SCHEMA",
    "LEGACY_CHECKPOINT_SCHEMA",
    "LEGACY_DECISION_SCHEMA",
    "LEGACY_EVENT_SCHEMA",
    "LEGACY_STATE_SCHEMA",
    "LEGACY_WORKFLOW_SCHEMA",
    "NORMALIZED_HARNESS_GRAPH_SCHEMA",
    "HarnessGraphContractKind",
    "HarnessGraphSchemaRegistration",
    "HarnessGraphSchemaRegistry",
]
