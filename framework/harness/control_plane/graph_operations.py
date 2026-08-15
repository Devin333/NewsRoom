from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError


HARNESS_GRAPH_RUN_OPERATION_SCHEMA = "newsroom.harness-graph-run-operation/v1"
HARNESS_GRAPH_RUN_OPERATION_NODE_ID = "__graph_run_operation__"
HARNESS_GRAPH_RUN_OPERATION_CONTRACT_ID = "graph-run-operation"
HARNESS_GRAPH_RUN_OPERATION_CONTRACT_VERSION = "1"

_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class HarnessGraphRunOperationType(StrEnum):
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class HarnessGraphRunOperation:
    operation_type: HarnessGraphRunOperationType | str
    operation_id: str
    run_id: str
    actor_identity_scope_ref: str
    reason_code: str
    accepted_sequence: int
    schema_version: str = HARNESS_GRAPH_RUN_OPERATION_SCHEMA
    operation_identity_ref: str = field(init=False)
    operation_ref: str = field(init=False)

    def __post_init__(self) -> None:
        operation_type = HarnessGraphRunOperationType(self.operation_type)
        operation_id = _required_text(
            self.operation_id,
            "graph_run_operation.operation_id",
        )
        run_id = _required_text(self.run_id, "graph_run_operation.run_id")
        actor_ref = _checksum(
            self.actor_identity_scope_ref,
            "graph_run_operation.actor_identity_scope_ref",
        )
        reason_code = _required_text(
            self.reason_code,
            "graph_run_operation.reason_code",
        )
        if len(reason_code) > 128:
            raise HarnessValidationError(
                "graph run operation reason code is too long",
                code="graph_run_operation_reason_invalid",
            )
        if (
            not isinstance(self.accepted_sequence, int)
            or isinstance(self.accepted_sequence, bool)
            or self.accepted_sequence < 0
        ):
            raise HarnessValidationError(
                "graph run operation sequence must be a non-negative integer",
                code="graph_run_operation_sequence_invalid",
            )
        if self.schema_version != HARNESS_GRAPH_RUN_OPERATION_SCHEMA:
            raise HarnessValidationError(
                "unsupported graph run operation schema",
                code="unsupported_graph_run_operation_schema",
            )
        object.__setattr__(self, "operation_type", operation_type)
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "actor_identity_scope_ref", actor_ref)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(
            self,
            "operation_identity_ref",
            checksum_for(self.identity_projection()),
        )
        object.__setattr__(
            self,
            "operation_ref",
            checksum_for(self.checksum_projection()),
        )

    def identity_projection(self) -> dict[str, str]:
        return {
            "operation_type": self.operation_type.value,
            "operation_id": self.operation_id,
            "run_id": self.run_id,
        }

    def idempotency_projection(self) -> dict[str, Any]:
        projection = self.checksum_projection()
        projection.pop("accepted_sequence")
        return projection

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation_type": self.operation_type.value,
            "operation_id": self.operation_id,
            "run_id": self.run_id,
            "actor_identity_scope_ref": self.actor_identity_scope_ref,
            "reason_code": self.reason_code,
            "accepted_sequence": self.accepted_sequence,
            "operation_identity_ref": self.operation_identity_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "operation_ref": self.operation_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessGraphRunOperation:
        if not isinstance(value, Mapping):
            raise TypeError("graph run operation must be an object")
        expected = {
            "schema_version",
            "operation_type",
            "operation_id",
            "run_id",
            "actor_identity_scope_ref",
            "reason_code",
            "accepted_sequence",
            "operation_identity_ref",
            "operation_ref",
        }
        if set(value) != expected:
            raise HarnessValidationError(
                "graph run operation fields do not match its schema",
                code="invalid_graph_run_operation",
            )
        operation = cls(
            operation_type=value["operation_type"],
            operation_id=value["operation_id"],
            run_id=value["run_id"],
            actor_identity_scope_ref=value["actor_identity_scope_ref"],
            reason_code=value["reason_code"],
            accepted_sequence=value["accepted_sequence"],
            schema_version=value["schema_version"],
        )
        if (
            value["operation_identity_ref"] != operation.operation_identity_ref
            or value["operation_ref"] != operation.operation_ref
        ):
            raise HarnessValidationError(
                "graph run operation checksum is invalid",
                code="invalid_graph_run_operation_checksum",
            )
        return operation


def _checksum(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _CHECKSUM_PATTERN.fullmatch(value):
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="invalid_graph_run_operation_reference",
        )
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HarnessValidationError(
            f"{field_name} is required",
            code="graph_required_field",
            details={"field": field_name},
        )
    return value.strip()


__all__ = [
    "HARNESS_GRAPH_RUN_OPERATION_CONTRACT_ID",
    "HARNESS_GRAPH_RUN_OPERATION_CONTRACT_VERSION",
    "HARNESS_GRAPH_RUN_OPERATION_NODE_ID",
    "HARNESS_GRAPH_RUN_OPERATION_SCHEMA",
    "HarnessGraphRunOperation",
    "HarnessGraphRunOperationType",
]
