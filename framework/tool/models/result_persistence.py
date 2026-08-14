from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for

from framework.shared.redaction import DEFAULT_SENSITIVE_KEY_TOKENS
from framework.tool.runtime.errors import ToolDefinitionError, ToolRuntimeError


_MEDIA_TYPE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/"
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z"
)
_CONTROL_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_ARTIFACT_CLASSES = frozenset(
    {"control", "evidence", "transcript", "intermediate", "report", "debug"}
)
_RETENTION_CLASSES = frozenset({"ephemeral", "run", "evidence", "report", "cache"})
_SENSITIVITY_CLASSES = frozenset({"public", "internal", "restricted"})
_CONTEXT_POLICIES = frozenset({"summary_only", "sample_allowed", "ref_load_allowed"})
_RESERVED_CONTROL_FIELDS = frozenset(
    {
        "candidate",
        "call_id",
        "gate_decision",
        "gate_checksum",
        "materialized_refs",
        "memory_write",
        "policy_trace_checksum",
        "persistence_decision",
        "publication",
        "raw_prompt",
        "route",
        "response_checksum",
        "retry_count",
        "routing",
        "side_effect_receipt",
        "status",
        "timeout",
        "tool_id",
        "tool_status",
        "tool_call_id",
        "tool_authorization",
    }
)


@dataclass(frozen=True, slots=True)
class ToolResultPersistenceContract:
    """Tool-owned declaration consumed by the Harness result adapter."""

    media_type: str = "application/json"
    control_fields: tuple[str, ...] = ()
    artifact_class: str = "intermediate"
    retention_class: str = "run"
    sensitivity: str = "internal"
    required_for_replay: bool = False
    required_for_publication: bool = False
    reusable: bool = False
    dependency_digest: str | None = None
    context_policy: str = "summary_only"

    def __post_init__(self) -> None:
        normalized_media = str(self.media_type).strip().casefold()
        if _MEDIA_TYPE.fullmatch(normalized_media) is None:
            raise ToolDefinitionError("tool result media_type is invalid")
        fields = _unique_strings(self.control_fields, "control_fields")
        if any(
            _CONTROL_FIELD.fullmatch(field) is None
            or field.casefold() in _RESERVED_CONTROL_FIELDS
            or any(
                token in field.casefold().replace("-", "_")
                for token in DEFAULT_SENSITIVE_KEY_TOKENS
            )
            for field in fields
        ):
            raise ToolDefinitionError("tool result control_fields contain an invalid field")
        artifact_class = _choice(
            self.artifact_class,
            _ARTIFACT_CLASSES,
            "artifact_class",
        )
        retention_class = _choice(
            self.retention_class,
            _RETENTION_CLASSES,
            "retention_class",
        )
        sensitivity = _choice(
            self.sensitivity,
            _SENSITIVITY_CLASSES,
            "sensitivity",
        )
        context_policy = _choice(
            self.context_policy,
            _CONTEXT_POLICIES,
            "context_policy",
        )
        for field_name in (
            "required_for_replay",
            "required_for_publication",
            "reusable",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ToolDefinitionError(f"tool result {field_name} must be boolean")
        dependency = self.dependency_digest
        if dependency is not None:
            dependency = str(dependency).strip()
            if re.fullmatch(r"sha256:[0-9a-f]{64}", dependency) is None:
                raise ToolDefinitionError("tool result dependency_digest is invalid")
        if self.reusable and dependency is None:
            raise ToolDefinitionError(
                "reusable tool results require an exact dependency_digest"
            )
        if self.reusable and (
            self.required_for_replay
            or self.required_for_publication
            or artifact_class in {"evidence", "transcript", "report"}
        ):
            raise ToolDefinitionError("required tool evidence cannot be cache reusable")
        if fields and not (
            normalized_media == "application/json"
            or normalized_media.endswith("+json")
        ):
            raise ToolDefinitionError("control_fields require a JSON result media_type")
        if (
            not (
                normalized_media == "application/json"
                or normalized_media.endswith("+json")
                or normalized_media.startswith("text/")
            )
            and sensitivity != "restricted"
        ):
            raise ToolDefinitionError(
                "binary tool results must use restricted sensitivity"
            )
        object.__setattr__(self, "media_type", normalized_media)
        object.__setattr__(self, "control_fields", fields)
        object.__setattr__(self, "artifact_class", artifact_class)
        object.__setattr__(self, "retention_class", retention_class)
        object.__setattr__(self, "sensitivity", sensitivity)
        object.__setattr__(self, "dependency_digest", dependency)
        object.__setattr__(self, "context_policy", context_policy)

    @property
    def is_json(self) -> bool:
        return self.media_type == "application/json" or self.media_type.endswith(
            "+json"
        )

    def validate_definition(self, *, tool_name: str, output_schema: Any) -> None:
        if output_schema is not None and not self.is_json:
            raise ToolDefinitionError(
                f"non-JSON tool result cannot declare output_schema: {tool_name}"
            )
        if output_schema is not None:
            if not isinstance(output_schema, Mapping):
                raise ToolDefinitionError(
                    f"output_schema must be an object for tool {tool_name}"
                )
            schema = dict(output_schema)
            try:
                validator_for(schema).check_schema(schema)
            except SchemaError as exc:
                raise ToolDefinitionError(
                    f"output_schema is invalid for tool {tool_name}"
                ) from exc
        if not self.control_fields:
            return
        if output_schema is None:
            raise ToolDefinitionError(
                f"tool result control_fields require output_schema: {tool_name}"
            )
        schema = dict(output_schema)
        if schema.get("type") != "object" or not isinstance(
            schema.get("properties"), Mapping
        ):
            raise ToolDefinitionError(
                f"tool result control_fields require object output_schema: {tool_name}"
            )
        missing = sorted(set(self.control_fields) - set(schema["properties"]))
        if missing:
            raise ToolDefinitionError(
                f"tool result control_fields are absent from output_schema for "
                f"{tool_name}: {', '.join(missing)}"
            )

    def validate_output(self, output: Any, *, tool_name: str, output_schema: Any) -> None:
        if not self.is_json:
            if self.media_type.startswith("text/") and not isinstance(output, str):
                raise ToolRuntimeError(
                    f"tool {tool_name} must return text for {self.media_type}"
                )
            if not self.media_type.startswith("text/") and not isinstance(
                output, (bytes, bytearray)
            ):
                raise ToolRuntimeError(
                    f"tool {tool_name} must return bytes for {self.media_type}"
                )
            return
        if output_schema is None:
            return
        schema = dict(output_schema)
        validator_type = validator_for(schema)
        validator_type.check_schema(schema)
        errors = sorted(
            validator_type(schema).iter_errors(output),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            raise ToolRuntimeError(
                f"tool output does not satisfy output_schema for {tool_name}: "
                f"{errors[0].message}"
            )

    def control_projection(self, output: Any) -> dict[str, Any]:
        if not self.control_fields:
            return {}
        if not isinstance(output, Mapping):
            raise ToolRuntimeError("tool control projection requires an object output")
        return {
            field_name: output[field_name]
            for field_name in self.control_fields
            if field_name in output
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_type": self.media_type,
            "control_fields": list(self.control_fields),
            "artifact_class": self.artifact_class,
            "retention_class": self.retention_class,
            "sensitivity": self.sensitivity,
            "required_for_replay": self.required_for_replay,
            "required_for_publication": self.required_for_publication,
            "reusable": self.reusable,
            "dependency_digest": self.dependency_digest,
            "context_policy": self.context_policy,
        }

    @classmethod
    def from_any(cls, value: Any) -> "ToolResultPersistenceContract":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ToolDefinitionError("tool result_persistence must be an object")
        expected = {
            "media_type",
            "control_fields",
            "artifact_class",
            "retention_class",
            "sensitivity",
            "required_for_replay",
            "required_for_publication",
            "reusable",
            "dependency_digest",
            "context_policy",
        }
        unknown = sorted(set(value) - expected)
        if unknown:
            raise ToolDefinitionError(
                "tool result_persistence has unknown fields: " + ", ".join(unknown)
            )
        return cls(
            media_type=value.get("media_type", "application/json"),
            control_fields=value.get("control_fields", ()),
            artifact_class=value.get("artifact_class", "intermediate"),
            retention_class=value.get("retention_class", "run"),
            sensitivity=value.get("sensitivity", "internal"),
            required_for_replay=value.get("required_for_replay", False),
            required_for_publication=value.get("required_for_publication", False),
            reusable=value.get("reusable", False),
            dependency_digest=value.get("dependency_digest"),
            context_policy=value.get("context_policy", "summary_only"),
        )


def _unique_strings(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ToolDefinitionError(f"tool result {field_name} must be an array")
    normalized = tuple(str(item).strip() for item in value)
    if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
        raise ToolDefinitionError(
            f"tool result {field_name} must contain unique non-empty strings"
        )
    return tuple(sorted(normalized))


def _choice(value: Any, allowed: frozenset[str], field_name: str) -> str:
    normalized = str(value).strip().casefold()
    if normalized not in allowed:
        raise ToolDefinitionError(f"tool result {field_name} is invalid")
    return normalized


__all__ = ["ToolResultPersistenceContract"]
