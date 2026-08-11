from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol


LOCAL_STRUCTURED_OUTPUT_DIALECT = "draft2020-12-local-v1"


@dataclass(frozen=True)
class StructuredOutputLimits:
    max_schema_bytes: int = 262_144
    max_schema_nodes: int = 4_096
    max_schema_depth: int = 64
    max_schema_ref_depth: int = 32
    max_enum_items: int = 1_024
    max_pattern_length: int = 2_048
    max_response_bytes: int = 262_144
    max_instance_nodes: int = 16_384
    max_instance_depth: int = 64
    max_diagnostics: int = 20

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class StructuredOutputDiagnostic:
    code: str
    message: str
    instance_path: tuple[str | int, ...] = ()
    schema_path: tuple[str | int, ...] = ()
    validator: str | None = None
    contract_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("diagnostic code must be a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("diagnostic message must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "instance_path": list(self.instance_path),
            "schema_path": list(self.schema_path),
            "validator": self.validator,
            "contract_digest": self.contract_digest,
        }


class StructuredOutputTypedAdapter(Protocol):
    revision: str

    def validate(self, value: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class StructuredOutputContract:
    schema_name: str
    schema_revision: str
    canonical_schema: dict[str, Any]
    schema_digest: str
    limits: StructuredOutputLimits = field(default_factory=StructuredOutputLimits)
    dialect: str = LOCAL_STRUCTURED_OUTPUT_DIALECT
    root_kind: str = "object"
    typed_adapter: StructuredOutputTypedAdapter | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.schema_name, str) or not self.schema_name.strip():
            raise ValueError("schema_name must be a non-empty string")
        if not isinstance(self.schema_revision, str) or not self.schema_revision.strip():
            raise ValueError("schema_revision must be a non-empty string")
        if not isinstance(self.canonical_schema, dict):
            raise ValueError("canonical_schema must be an object")
        if not self.schema_digest.startswith("sha256:") or len(self.schema_digest) != 71:
            raise ValueError("schema_digest must be a sha256 digest")
        if self.dialect != LOCAL_STRUCTURED_OUTPUT_DIALECT:
            raise ValueError("unsupported structured-output dialect")
        if self.root_kind != "object":
            raise ValueError("structured output root_kind must be object")
        object.__setattr__(self, "schema_name", self.schema_name.strip())
        object.__setattr__(self, "schema_revision", self.schema_revision.strip())
        object.__setattr__(self, "canonical_schema", deepcopy(self.canonical_schema))

    @property
    def typed_adapter_revision(self) -> str | None:
        return self.typed_adapter.revision if self.typed_adapter is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "schema_revision": self.schema_revision,
            "schema_digest": self.schema_digest,
            "dialect": self.dialect,
            "root_kind": self.root_kind,
            "typed_adapter_revision": self.typed_adapter_revision,
        }


@dataclass(frozen=True)
class StructuredOutputValidationResult:
    accepted: bool
    value: dict[str, Any] | None = None
    diagnostics: tuple[StructuredOutputDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if self.accepted != (self.value is not None and not self.diagnostics):
            raise ValueError("accepted result must have a value and no diagnostics")
        object.__setattr__(self, "value", deepcopy(self.value))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


class LLMStructuredOutputError(ValueError):
    """Base class for deterministic structured-output contract failures."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: tuple[StructuredOutputDiagnostic, ...] = (),
    ) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)
        self.code = self.diagnostics[0].code if self.diagnostics else "structured_output_error"


class LLMStructuredOutputValidationError(LLMStructuredOutputError):
    """Raised when parsed structured output violates its local contract."""


class LLMStructuredOutputSchemaError(LLMStructuredOutputValidationError):
    """Raised when an output schema cannot be compiled safely."""


class LLMStructuredOutputParseError(LLMStructuredOutputValidationError):
    """Raised when provider content is not a strict JSON object."""
