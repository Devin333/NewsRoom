from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from framework.llm.structured_output.contracts import (
    LLMStructuredOutputParseError,
    StructuredOutputDiagnostic,
    StructuredOutputLimits,
)


class _DuplicateKeyError(ValueError):
    pass


class _NonFiniteConstantError(ValueError):
    pass


@dataclass(frozen=True)
class StrictStructuredOutputDecoder:
    limits: StructuredOutputLimits = StructuredOutputLimits()

    def decode(self, content: str) -> dict[str, Any]:
        return decode_structured_output(content, limits=self.limits)


def decode_structured_output(
    content: str,
    *,
    limits: StructuredOutputLimits | None = None,
) -> dict[str, Any]:
    resolved_limits = limits or StructuredOutputLimits()
    if not isinstance(content, str):
        raise _parse_error(
            "structured_output_parse_error",
            "structured output content must be text",
        )
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _parse_error(
            "structured_output_parse_error",
            "structured output content is not valid UTF-8 text",
        ) from exc
    if len(encoded) > resolved_limits.max_response_bytes:
        raise _parse_error(
            "structured_output_limit_exceeded",
            "structured output exceeds the configured byte limit",
        )
    try:
        value = json.loads(
            content,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except _NonFiniteConstantError as exc:
        raise _parse_error(
            "structured_output_non_finite_number",
            "structured output contains a non-finite JSON number",
        ) from exc
    except _DuplicateKeyError as exc:
        raise _parse_error(
            "structured_output_duplicate_key",
            "structured output contains a duplicate object key",
        ) from exc
    except (json.JSONDecodeError, RecursionError) as exc:
        raise _parse_error(
            "structured_output_parse_error",
            "structured output is not valid JSON",
        ) from exc
    return validate_structured_output_object(value, limits=resolved_limits)


def validate_structured_output_object(
    value: Any,
    *,
    limits: StructuredOutputLimits | None = None,
    contract_digest: str | None = None,
) -> dict[str, Any]:
    resolved_limits = limits or StructuredOutputLimits()
    if not isinstance(value, dict):
        raise _parse_error(
            "structured_output_root_type_error",
            "structured output root must be an object",
            contract_digest=contract_digest,
        )
    node_count = 0

    def visit(current: Any, depth: int, path: tuple[str | int, ...]) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > resolved_limits.max_instance_nodes:
            raise _parse_error(
                "structured_output_limit_exceeded",
                "structured output exceeds the configured node limit",
                instance_path=path,
                contract_digest=contract_digest,
            )
        if depth > resolved_limits.max_instance_depth:
            raise _parse_error(
                "structured_output_limit_exceeded",
                "structured output exceeds the configured depth limit",
                instance_path=path,
                contract_digest=contract_digest,
            )
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise _parse_error(
                        "structured_output_parse_error",
                        "structured output object keys must be strings",
                        instance_path=path,
                        contract_digest=contract_digest,
                    )
                visit(item, depth + 1, path + (key,))
            return
        if isinstance(current, list):
            for index, item in enumerate(current):
                visit(item, depth + 1, path + (index,))
            return
        if isinstance(current, float) and not math.isfinite(current):
            raise _parse_error(
                "structured_output_non_finite_number",
                "structured output contains a non-finite JSON number",
                instance_path=path,
                contract_digest=contract_digest,
            )
        if current is not None and not isinstance(current, (str, int, float, bool)):
            raise _parse_error(
                "structured_output_parse_error",
                "structured output contains a non-JSON value",
                instance_path=path,
                contract_digest=contract_digest,
            )

    visit(value, 0, ())
    return value


def _reject_constant(value: str) -> None:
    raise _NonFiniteConstantError(value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError(key)
        value[key] = item
    return value


def _parse_error(
    code: str,
    message: str,
    *,
    instance_path: tuple[str | int, ...] = (),
    contract_digest: str | None = None,
) -> LLMStructuredOutputParseError:
    diagnostic = StructuredOutputDiagnostic(
        code=code,
        message=message,
        instance_path=instance_path,
        contract_digest=contract_digest,
    )
    return LLMStructuredOutputParseError(message, diagnostics=(diagnostic,))
