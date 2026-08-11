from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from framework.llm.structured_output.contracts import (
    LLMStructuredOutputSchemaError,
    StructuredOutputContract,
    StructuredOutputDiagnostic,
    StructuredOutputLimits,
)


_ALLOWED_SCHEMA_KEYWORDS = {
    "$anchor",
    "$comment",
    "$defs",
    "$id",
    "$ref",
    "$schema",
    "additionalProperties",
    "allOf",
    "anyOf",
    "const",
    "contains",
    "contentEncoding",
    "contentMediaType",
    "contentSchema",
    "default",
    "definitions",
    "dependentRequired",
    "dependentSchemas",
    "deprecated",
    "description",
    "else",
    "enum",
    "examples",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "format",
    "if",
    "items",
    "maxContains",
    "maximum",
    "maxItems",
    "maxLength",
    "maxProperties",
    "minContains",
    "minimum",
    "minItems",
    "minLength",
    "minProperties",
    "multipleOf",
    "not",
    "oneOf",
    "pattern",
    "patternProperties",
    "prefixItems",
    "properties",
    "propertyNames",
    "readOnly",
    "required",
    "then",
    "title",
    "type",
    "unevaluatedItems",
    "unevaluatedProperties",
    "uniqueItems",
    "writeOnly",
}
_SCHEMA_VALUE_KEYWORDS = {
    "additionalProperties",
    "contains",
    "contentSchema",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
    "unevaluatedItems",
    "unevaluatedProperties",
}
_SCHEMA_ARRAY_KEYWORDS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_SCHEMA_MAP_KEYWORDS = {
    "$defs",
    "definitions",
    "dependentSchemas",
    "patternProperties",
    "properties",
}
_PORTABILITY_FORBIDDEN_PATTERN_PARTS = (
    "(?P<",
    "(?P=",
    "(?<=",
    "(?<!",
    "(?>",
    "\\A",
    "\\Z",
    "\\g<",
    "\\N{",
)


@dataclass(frozen=True)
class PydanticStructuredOutputAdapter:
    model: Any
    revision: str

    def validate(self, value: dict[str, Any]) -> dict[str, Any]:
        validated = self.model.model_validate(deepcopy(value))
        dumped = validated.model_dump(mode="json", round_trip=True)
        if not isinstance(dumped, dict):
            raise TypeError("Pydantic structured output must serialize to an object")
        return dumped


def compile_structured_output_contract(
    schema: Any,
    *,
    schema_name: str = "structured_output",
    schema_revision: str | None = None,
    limits: StructuredOutputLimits | None = None,
) -> StructuredOutputContract:
    if isinstance(schema, StructuredOutputContract):
        return schema

    resolved_limits = limits or StructuredOutputLimits()
    exported_schema, typed_adapter = _schema_source(schema)
    try:
        encoded = json.dumps(
            exported_schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError) as exc:
        raise _schema_error(
            "schema_preflight_error",
            "structured output schema must be a finite JSON object",
        ) from exc
    if len(encoded) > resolved_limits.max_schema_bytes:
        raise _schema_error(
            "structured_output_limit_exceeded",
            "structured output schema exceeds the configured byte limit",
        )
    canonical_schema = json.loads(encoded.decode("utf-8"))
    if not isinstance(canonical_schema, dict):
        raise _schema_error(
            "schema_preflight_error",
            "structured output schema must be an object",
        )
    _normalize_root_object(canonical_schema)
    canonical_bytes = json.dumps(
        canonical_schema,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(canonical_bytes) > resolved_limits.max_schema_bytes:
        raise _schema_error(
            "structured_output_limit_exceeded",
            "structured output canonical schema exceeds the configured byte limit",
        )
    digest = f"sha256:{sha256(canonical_bytes).hexdigest()}"
    _validate_tree_limits(canonical_schema, limits=resolved_limits, digest=digest)
    _validate_local_dialect(canonical_schema, limits=resolved_limits, digest=digest)
    try:
        Draft202012Validator.check_schema(canonical_schema)
    except SchemaError as exc:
        raise _schema_error(
            "schema_preflight_error",
            "structured output schema is not valid Draft 2020-12",
            digest=digest,
            validator=str(exc.validator) if exc.validator is not None else None,
        ) from exc
    _validate_reference_targets(canonical_schema, limits=resolved_limits, digest=digest)
    return StructuredOutputContract(
        schema_name=schema_name,
        schema_revision=schema_revision or digest,
        canonical_schema=canonical_schema,
        schema_digest=digest,
        limits=resolved_limits,
        typed_adapter=typed_adapter,
    )


def schema_for_provider(schema: Any) -> dict[str, Any]:
    return deepcopy(compile_structured_output_contract(schema).canonical_schema)


def _schema_source(
    schema: Any,
) -> tuple[dict[str, Any], PydanticStructuredOutputAdapter | None]:
    if isinstance(schema, Mapping):
        return deepcopy(dict(schema)), None
    model_json_schema = getattr(schema, "model_json_schema", None)
    if callable(model_json_schema):
        exported = model_json_schema()
        if not isinstance(exported, Mapping):
            raise _schema_error(
                "schema_preflight_error",
                "model_json_schema() must return an object",
            )
        model_validate = getattr(schema, "model_validate", None)
        typed_adapter = None
        if callable(model_validate):
            module_name = getattr(schema, "__module__", "unknown")
            qualified_name = getattr(schema, "__qualname__", getattr(schema, "__name__", "model"))
            model_name = f"{module_name}.{qualified_name}"
            typed_adapter = PydanticStructuredOutputAdapter(
                model=schema,
                revision=f"pydantic-v2:{model_name}",
            )
        return deepcopy(dict(exported)), typed_adapter
    legacy_schema = getattr(schema, "schema", None)
    if callable(legacy_schema):
        exported = legacy_schema()
        if isinstance(exported, Mapping):
            return deepcopy(dict(exported)), None
    raise _schema_error(
        "schema_preflight_error",
        "structured output schema must be an object or Pydantic model class",
    )


def _normalize_root_object(schema: dict[str, Any]) -> None:
    root_type = schema.get("type")
    if root_type is None:
        schema["type"] = "object"
        return
    if root_type != "object":
        raise _schema_error(
            "structured_output_root_type_error",
            "structured output schema root type must be object",
        )


def _validate_tree_limits(
    value: Any,
    *,
    limits: StructuredOutputLimits,
    digest: str,
) -> None:
    nodes = 0

    def visit(current: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > limits.max_schema_nodes:
            raise _schema_error(
                "structured_output_limit_exceeded",
                "structured output schema exceeds the configured node limit",
                digest=digest,
            )
        if depth > limits.max_schema_depth:
            raise _schema_error(
                "structured_output_limit_exceeded",
                "structured output schema exceeds the configured depth limit",
                digest=digest,
            )
        if isinstance(current, dict):
            for item in current.values():
                visit(item, depth + 1)
        elif isinstance(current, list):
            for item in current:
                visit(item, depth + 1)

    visit(value, 0)


def _validate_local_dialect(
    schema: dict[str, Any],
    *,
    limits: StructuredOutputLimits,
    digest: str,
) -> None:
    def visit(current: Any, path: tuple[str | int, ...]) -> None:
        if isinstance(current, bool):
            return
        if not isinstance(current, dict):
            raise _schema_error(
                "schema_preflight_error",
                "structured output subschema must be an object or boolean",
                digest=digest,
                schema_path=path,
            )
        unknown = sorted(set(current) - _ALLOWED_SCHEMA_KEYWORDS)
        if unknown:
            raise _schema_error(
                "schema_preflight_error",
                "structured output schema uses an unapproved keyword",
                digest=digest,
                schema_path=path + (unknown[0],),
            )
        reference = current.get("$ref")
        if reference is not None:
            if not isinstance(reference, str) or not (
                reference == "#" or reference.startswith("#/")
            ):
                raise _schema_error(
                    "schema_reference_forbidden",
                    "structured output schema references must use same-document JSON Pointers",
                    digest=digest,
                    schema_path=path + ("$ref",),
                    validator="$ref",
                )
        enum = current.get("enum")
        if isinstance(enum, list) and len(enum) > limits.max_enum_items:
            raise _schema_error(
                "structured_output_limit_exceeded",
                "structured output schema enum exceeds the configured item limit",
                digest=digest,
                schema_path=path + ("enum",),
                validator="enum",
            )
        pattern = current.get("pattern")
        if pattern is not None:
            _validate_pattern(
                pattern,
                limits=limits,
                digest=digest,
                schema_path=path + ("pattern",),
            )
        pattern_properties = current.get("patternProperties")
        if isinstance(pattern_properties, dict):
            for property_pattern in pattern_properties:
                _validate_pattern(
                    property_pattern,
                    limits=limits,
                    digest=digest,
                    schema_path=path + ("patternProperties", property_pattern),
                )
        for keyword in _SCHEMA_VALUE_KEYWORDS:
            if keyword in current:
                visit(current[keyword], path + (keyword,))
        for keyword in _SCHEMA_ARRAY_KEYWORDS:
            values = current.get(keyword)
            if isinstance(values, list):
                for index, item in enumerate(values):
                    visit(item, path + (keyword, index))
        for keyword in _SCHEMA_MAP_KEYWORDS:
            values = current.get(keyword)
            if isinstance(values, dict):
                for name, item in values.items():
                    visit(item, path + (keyword, name))

    visit(schema, ())


def _validate_pattern(
    pattern: Any,
    *,
    limits: StructuredOutputLimits,
    digest: str,
    schema_path: tuple[str | int, ...],
) -> None:
    if not isinstance(pattern, str):
        return
    if len(pattern) > limits.max_pattern_length:
        raise _schema_error(
            "structured_output_limit_exceeded",
            "structured output schema pattern exceeds the configured length limit",
            digest=digest,
            schema_path=schema_path,
            validator="pattern",
        )
    if any(part in pattern for part in _PORTABILITY_FORBIDDEN_PATTERN_PARTS):
        raise _schema_error(
            "schema_preflight_error",
            "structured output schema pattern is outside the portable regex profile",
            digest=digest,
            schema_path=schema_path,
            validator="pattern",
        )
    try:
        re.compile(pattern)
    except re.error as exc:
        raise _schema_error(
            "schema_preflight_error",
            "structured output schema pattern is invalid",
            digest=digest,
            schema_path=schema_path,
            validator="pattern",
        ) from exc


def _validate_reference_targets(
    schema: dict[str, Any],
    *,
    limits: StructuredOutputLimits,
    digest: str,
) -> None:
    references: list[tuple[str, tuple[str | int, ...]]] = []

    def collect(current: Any, path: tuple[str | int, ...]) -> None:
        if isinstance(current, dict):
            reference = current.get("$ref")
            if isinstance(reference, str):
                references.append((reference, path + ("$ref",)))
            for key, item in current.items():
                if key not in {"const", "default", "enum", "examples"}:
                    collect(item, path + (key,))
        elif isinstance(current, list):
            for index, item in enumerate(current):
                collect(item, path + (index,))

    collect(schema, ())
    for reference, schema_path in references:
        _resolve_json_pointer(schema, reference, digest=digest, schema_path=schema_path)

    for reference, schema_path in references:
        depth = 0
        current_reference = reference
        seen: set[str] = set()
        while True:
            if current_reference in seen:
                raise _schema_error(
                    "schema_reference_forbidden",
                    "structured output schema contains a cyclic direct reference chain",
                    digest=digest,
                    schema_path=schema_path,
                    validator="$ref",
                )
            seen.add(current_reference)
            depth += 1
            if depth > limits.max_schema_ref_depth:
                raise _schema_error(
                    "structured_output_limit_exceeded",
                    "structured output schema reference chain exceeds the configured limit",
                    digest=digest,
                    schema_path=schema_path,
                    validator="$ref",
                )
            target = _resolve_json_pointer(
                schema,
                current_reference,
                digest=digest,
                schema_path=schema_path,
            )
            if not isinstance(target, dict) or not isinstance(target.get("$ref"), str):
                break
            current_reference = target["$ref"]


def _resolve_json_pointer(
    schema: dict[str, Any],
    reference: str,
    *,
    digest: str,
    schema_path: tuple[str | int, ...],
) -> Any:
    if reference == "#":
        return schema
    current: Any = schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                current = current[int(part)]
            else:
                current = current[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise _schema_error(
                "schema_preflight_error",
                "structured output schema contains an unresolved local reference",
                digest=digest,
                schema_path=schema_path,
                validator="$ref",
            ) from exc
    return current


def _schema_error(
    code: str,
    message: str,
    *,
    digest: str | None = None,
    schema_path: tuple[str | int, ...] = (),
    validator: str | None = None,
) -> LLMStructuredOutputSchemaError:
    diagnostic = StructuredOutputDiagnostic(
        code=code,
        message=message,
        schema_path=schema_path,
        validator=validator,
        contract_digest=digest,
    )
    return LLMStructuredOutputSchemaError(message, diagnostics=(diagnostic,))
