from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Self

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.activity import (
    HarnessRetryPolicy,
    HarnessStepSpec,
)
from framework.harness.graph.canonical import (
    canonical_checksum,
    freeze_json,
)
from framework.harness.graph.dsl import HarnessGraphSpec
from framework.harness.graph.versioning import (
    HARNESS_GRAPH_DEFINITION_SCHEMA,
)
from framework.harness.side_effects.models import (
    HarnessSideEffectHandlerReference,
    HarnessTerminalSideEffectPolicy,
)


MAX_GRAPH_DEFINITION_ACTIVITIES = 10_000
_GRAPH_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*\Z")
_GRAPH_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})


@dataclass(frozen=True, slots=True)
class HarnessGraphDefinition:
    """Immutable, canonical Graph declaration before compiler preflight."""

    graph_id: str
    graph_version: str
    root: HarnessGraphSpec | Mapping[str, Any]
    activities: tuple[HarnessStepSpec, ...]
    terminal_side_effect_policy: (
        HarnessTerminalSideEffectPolicy | Mapping[str, Any]
    )
    schema_version: str = HARNESS_GRAPH_DEFINITION_SCHEMA
    definition_checksum: str | None = field(default=None, compare=True)

    def __post_init__(self) -> None:
        graph_id = _identifier(self.graph_id, "graph_id")
        graph_version = _exact_version(self.graph_version, "graph_version")
        root = self.root
        if not isinstance(root, HarnessGraphSpec):
            if not isinstance(root, Mapping):
                raise HarnessValidationError(
                    "root must be a HarnessGraphSpec",
                    code="invalid_graph_definition",
                )
            root = HarnessGraphSpec.from_dict(root)
        if root.graph_id != graph_id:
            raise HarnessValidationError(
                "Graph definition identity must match its root Graph",
                code="graph_definition_identity_mismatch",
                details={
                    "definition_graph_id": graph_id,
                    "root_graph_id": root.graph_id,
                },
            )
        activities = _activities(self.activities)
        policy = self.terminal_side_effect_policy
        if not isinstance(policy, HarnessTerminalSideEffectPolicy):
            if not isinstance(policy, Mapping):
                raise HarnessValidationError(
                    "terminal_side_effect_policy must be a Harness policy",
                    code="invalid_graph_definition",
                )
            policy = HarnessTerminalSideEffectPolicy.from_dict(policy)
        if self.schema_version != HARNESS_GRAPH_DEFINITION_SCHEMA:
            raise HarnessValidationError(
                "unsupported Graph definition schema",
                code="unsupported_graph_definition_schema",
                details={"schema_version": str(self.schema_version)},
            )
        object.__setattr__(self, "graph_id", graph_id)
        object.__setattr__(self, "graph_version", graph_version)
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "activities", activities)
        object.__setattr__(self, "terminal_side_effect_policy", policy)
        expected = canonical_checksum(self.checksum_projection())
        if self.definition_checksum is not None:
            supplied = _checksum(
                self.definition_checksum,
                "definition_checksum",
            )
            if supplied != expected:
                raise HarnessValidationError(
                    "Graph definition checksum does not match canonical content",
                    code="graph_definition_checksum_mismatch",
                )
        object.__setattr__(self, "definition_checksum", expected)

    @property
    def activity_ids(self) -> tuple[str, ...]:
        return tuple(activity.step_id for activity in self.activities)

    def activity(self, activity_id: str) -> HarnessStepSpec | None:
        normalized = _identifier(activity_id, "activity_id")
        for activity in self.activities:
            if activity.step_id == normalized:
                return activity
        return None

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "root": self.root.to_dict(),
            "activities": [activity.to_dict() for activity in self.activities],
            "terminal_side_effect_policy": (
                self.terminal_side_effect_policy.to_dict()
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "definition_checksum": self.definition_checksum,
        }

    def verify_integrity(self) -> None:
        if self.definition_checksum != canonical_checksum(
            self.checksum_projection()
        ):
            raise HarnessValidationError(
                "Graph definition checksum does not match canonical content",
                code="graph_definition_checksum_mismatch",
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "graph_id",
                "graph_version",
                "root",
                "activities",
                "terminal_side_effect_policy",
                "definition_checksum",
            },
            "Graph definition",
        )
        return cls(
            schema_version=payload["schema_version"],
            graph_id=payload["graph_id"],
            graph_version=payload["graph_version"],
            root=_mapping(payload["root"], "root"),
            activities=tuple(
                _activity_from_dict(item)
                for item in _mapping_array(
                    payload["activities"],
                    "activities",
                )
            ),
            terminal_side_effect_policy=_mapping(
                payload["terminal_side_effect_policy"],
                "terminal_side_effect_policy",
            ),
            definition_checksum=payload["definition_checksum"],
        )


class HarnessGraphDefinitionReader:
    """Strict Graph-only reader with no legacy declaration upcast path."""

    def read(
        self,
        payload: Mapping[str, Any],
        *,
        source_schema: str,
    ) -> HarnessGraphDefinition:
        if source_schema != HARNESS_GRAPH_DEFINITION_SCHEMA:
            raise HarnessValidationError(
                "unsupported Graph definition schema",
                code="unsupported_graph_definition_schema",
                details={"schema_version": str(source_schema)},
            )
        definition = HarnessGraphDefinition.from_dict(payload)
        if definition.schema_version != source_schema:
            raise HarnessValidationError(
                "Graph definition payload schema does not match reader schema",
                code="graph_definition_schema_mismatch",
            )
        return definition

    def read_for_execution(
        self,
        payload: Mapping[str, Any],
        *,
        source_schema: str,
    ) -> HarnessGraphDefinition:
        return self.read(payload, source_schema=source_schema)


def _activities(values: Sequence[HarnessStepSpec]) -> tuple[HarnessStepSpec, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values,
        Sequence,
    ):
        raise HarnessValidationError(
            "activities must be an array",
            code="invalid_graph_definition",
        )
    if not values or len(values) > MAX_GRAPH_DEFINITION_ACTIVITIES:
        raise HarnessValidationError(
            "Graph definition activity count is outside its bound",
            code="invalid_graph_definition",
        )
    if any(not isinstance(value, HarnessStepSpec) for value in values):
        raise HarnessValidationError(
            "activities must contain HarnessStepSpec values",
            code="invalid_graph_definition",
        )
    snapshots = tuple(
        sorted(
            (_activity_snapshot(value) for value in values),
            key=lambda item: item.step_id,
        )
    )
    identities = tuple(activity.step_id for activity in snapshots)
    if len(identities) != len(set(identities)):
        raise HarnessValidationError(
            "Graph definition activity identities must be unique",
            code="graph_duplicate_identity",
            details={"field": "activities"},
        )
    return snapshots


def _activity_snapshot(activity: HarnessStepSpec) -> HarnessStepSpec:
    snapshot = HarnessStepSpec(
        step_id=activity.step_id,
        worker_type=activity.worker_type,
        input_keys=tuple(activity.input_keys),
        output_key=activity.output_key,
        retry_policy=activity.retry_policy,
        quality_gate=activity.quality_gate,
        metadata={},
        side_effect_handler=activity.side_effect_handler,
    )
    object.__setattr__(
        snapshot,
        "metadata",
        freeze_json(activity.metadata, f"activity.{activity.step_id}.metadata"),
    )
    return snapshot


def _activity_from_dict(value: Mapping[str, Any]) -> HarnessStepSpec:
    payload = _exact_mapping(
        value,
        {
            "step_id",
            "worker_type",
            "input_keys",
            "output_key",
            "retry_policy",
            "quality_gate",
            "metadata",
        }
        | ({"side_effect_handler"} if "side_effect_handler" in value else set()),
        "Graph activity",
    )
    retry_payload = _exact_mapping(
        payload["retry_policy"],
        {
            "max_retries",
            "max_attempts",
            "effective_max_attempts",
            "retry_on_statuses",
            "backoff_seconds",
            "repair_step_id",
            "fail_fast_error_types",
        },
        "Graph activity retry policy",
    )
    retry_policy = HarnessRetryPolicy(
        max_retries=retry_payload["max_retries"],
        max_attempts=retry_payload["max_attempts"],
        retry_on_statuses=tuple(
            _text_array(retry_payload["retry_on_statuses"], "retry_on_statuses")
        ),
        backoff_seconds=retry_payload["backoff_seconds"],
        repair_step_id=retry_payload["repair_step_id"],
        fail_fast_error_types=tuple(
            _text_array(
                retry_payload["fail_fast_error_types"],
                "fail_fast_error_types",
            )
        ),
    )
    if retry_payload["effective_max_attempts"] != retry_policy.effective_max_attempts:
        raise HarnessValidationError(
            "Graph activity retry projection is inconsistent",
            code="invalid_graph_definition",
        )
    side_effect = payload.get("side_effect_handler")
    return HarnessStepSpec(
        step_id=payload["step_id"],
        worker_type=payload["worker_type"],
        input_keys=tuple(_text_array(payload["input_keys"], "input_keys")),
        output_key=payload["output_key"],
        retry_policy=retry_policy,
        quality_gate=payload["quality_gate"],
        metadata=dict(_mapping(payload["metadata"], "metadata")),
        side_effect_handler=(
            None
            if side_effect is None
            else HarnessSideEffectHandlerReference.parse(side_effect)
        ),
    )


def _identifier(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if _GRAPH_ID_PATTERN.fullmatch(text) is None:
        raise HarnessValidationError(
            f"{field_name} has an invalid format",
            code="invalid_graph_definition",
            details={"field": field_name},
        )
    return text


def _exact_version(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if (
        _GRAPH_VERSION_PATTERN.fullmatch(text) is None
        or text.casefold() in _MOVING_VERSIONS
    ):
        raise HarnessValidationError(
            f"{field_name} must be an exact version",
            code="graph_inexact_version_reference",
            details={"field": field_name, "version": text},
        )
    return text


def _checksum(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    digest = text.removeprefix("sha256:")
    if (
        not text.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise HarnessValidationError(
            f"{field_name} must be a sha256 checksum",
            code="invalid_graph_definition",
        )
    return text


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HarnessValidationError(
            f"{field_name} must be non-empty trimmed text",
            code="invalid_graph_definition",
            details={"field": field_name},
        )
    return value


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_graph_definition",
        )
    return value


def _mapping_array(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="invalid_graph_definition",
        )
    normalized = tuple(value)
    if any(not isinstance(item, Mapping) for item in normalized):
        raise HarnessValidationError(
            f"{field_name} must contain objects",
            code="invalid_graph_definition",
        )
    return normalized


def _text_array(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="invalid_graph_definition",
        )
    return tuple(_required_text(item, field_name) for item in value)


def _exact_mapping(
    value: Any,
    expected: set[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        actual = set(value) if isinstance(value, Mapping) else set()
        raise HarnessValidationError(
            f"{model} fields are invalid",
            code="invalid_graph_definition",
            details={
                "missing": sorted(expected.difference(actual)),
                "unexpected": sorted(actual.difference(expected)),
            },
        )
    return dict(value)


__all__ = [
    "HarnessGraphDefinition",
    "HarnessGraphDefinitionReader",
    "MAX_GRAPH_DEFINITION_ACTIVITIES",
]
