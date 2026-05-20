"""Shared framework primitives and helpers."""

from framework.shared.errors import (
    BoundaryViolationError,
    ConfigurationError,
    DependencyError,
    FrameworkError,
    RuntimeExecutionError,
    ValidationError,
)
from framework.shared.hashing import hash_bytes, hash_text, short_hash, stable_hash
from framework.shared.ids import RunId, StepId, TaskId, generate_id, normalize_id, stable_id
from framework.shared.json import canonical_json, json_loads, stable_json_dumps, to_jsonable
from framework.shared.pagination import PageRequest, PageResult
from framework.shared.redaction import (
    DEFAULT_SENSITIVE_KEY_TOKENS,
    REDACTED_VALUE,
    RedactionRule,
    Redactor,
    contains_redacted_value,
    redact_sensitive_values,
)
from framework.shared.result import ErrorDetail, Result
from framework.shared.serialization import JsonDataclassSerializer, Serializable, Serializer
from framework.shared.status import RuntimeStatus
from framework.shared.time import duration_ms, ensure_utc, format_datetime, parse_datetime, utc_now
from framework.shared.typing import JsonDict, JsonValue, Metadata, ensure_dict, ensure_list, optional_str

__all__ = [
    "BoundaryViolationError",
    "ConfigurationError",
    "DEFAULT_SENSITIVE_KEY_TOKENS",
    "DependencyError",
    "ErrorDetail",
    "FrameworkError",
    "JsonDataclassSerializer",
    "JsonDict",
    "JsonValue",
    "Metadata",
    "PageRequest",
    "PageResult",
    "REDACTED_VALUE",
    "RedactionRule",
    "Redactor",
    "Result",
    "RunId",
    "RuntimeExecutionError",
    "RuntimeStatus",
    "Serializable",
    "Serializer",
    "StepId",
    "TaskId",
    "ValidationError",
    "canonical_json",
    "contains_redacted_value",
    "duration_ms",
    "ensure_dict",
    "ensure_list",
    "ensure_utc",
    "format_datetime",
    "generate_id",
    "hash_bytes",
    "hash_text",
    "json_loads",
    "normalize_id",
    "optional_str",
    "parse_datetime",
    "redact_sensitive_values",
    "short_hash",
    "stable_hash",
    "stable_id",
    "stable_json_dumps",
    "to_jsonable",
    "utc_now",
]
