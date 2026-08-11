from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError as PydanticValidationError

from framework.llm.structured_output.contracts import (
    LLMStructuredOutputParseError,
    LLMStructuredOutputValidationError,
    StructuredOutputContract,
    StructuredOutputDiagnostic,
    StructuredOutputLimits,
    StructuredOutputValidationResult,
)
from framework.llm.structured_output.decoder import validate_structured_output_object
from framework.llm.structured_output.preflight import compile_structured_output_contract


def validate_structured_output(
    value: Any,
    schema: Any,
    *,
    schema_name: str = "structured_output",
    limits: StructuredOutputLimits | None = None,
) -> dict[str, Any]:
    contract = compile_structured_output_contract(
        schema,
        schema_name=schema_name,
        limits=limits,
    )
    return validate_compiled_structured_output(value, contract)


def validate_compiled_structured_output(
    value: Any,
    contract: StructuredOutputContract,
) -> dict[str, Any]:
    try:
        object_value = validate_structured_output_object(
            value,
            limits=contract.limits,
            contract_digest=contract.schema_digest,
        )
    except LLMStructuredOutputParseError:
        raise

    validator = Draft202012Validator(contract.canonical_schema)
    errors = sorted(
        validator.iter_errors(object_value),
        key=_validation_error_sort_key,
    )
    if errors:
        diagnostics = tuple(
            _jsonschema_diagnostic(error, contract=contract)
            for error in errors[: contract.limits.max_diagnostics]
        )
        raise LLMStructuredOutputValidationError(
            _diagnostic_summary(diagnostics),
            diagnostics=diagnostics,
        )

    validated = deepcopy(object_value)
    if contract.typed_adapter is not None:
        try:
            validated = contract.typed_adapter.validate(validated)
        except PydanticValidationError as exc:
            diagnostics = _pydantic_diagnostics(exc, contract=contract)
            raise LLMStructuredOutputValidationError(
                _diagnostic_summary(diagnostics),
                diagnostics=diagnostics,
            ) from exc
        except (TypeError, ValueError) as exc:
            diagnostic = StructuredOutputDiagnostic(
                code="structured_output_typed_validation_error",
                message="structured output failed typed model validation",
                contract_digest=contract.schema_digest,
                validator="pydantic",
            )
            raise LLMStructuredOutputValidationError(
                diagnostic.message,
                diagnostics=(diagnostic,),
            ) from exc
        validated = validate_structured_output_object(
            validated,
            limits=contract.limits,
            contract_digest=contract.schema_digest,
        )
    return deepcopy(validated)


def validate_structured_output_result(
    value: Any,
    schema: Any,
    *,
    schema_name: str = "structured_output",
    limits: StructuredOutputLimits | None = None,
) -> StructuredOutputValidationResult:
    try:
        validated = validate_structured_output(
            value,
            schema,
            schema_name=schema_name,
            limits=limits,
        )
    except LLMStructuredOutputValidationError as exc:
        return StructuredOutputValidationResult(
            accepted=False,
            diagnostics=exc.diagnostics,
        )
    return StructuredOutputValidationResult(accepted=True, value=validated)


def _validation_error_sort_key(error: Any) -> tuple[Any, ...]:
    return (
        tuple(str(item) for item in error.absolute_path),
        tuple(str(item) for item in error.absolute_schema_path),
        str(error.validator or ""),
        str(error.message),
    )


def _jsonschema_diagnostic(
    error: Any,
    *,
    contract: StructuredOutputContract,
) -> StructuredOutputDiagnostic:
    validator = str(error.validator) if error.validator is not None else None
    path = tuple(error.absolute_path)
    location = _json_pointer(path)
    message = (
        f"structured output at {location} failed {validator} validation"
        if validator
        else f"structured output at {location} failed schema validation"
    )
    return StructuredOutputDiagnostic(
        code="structured_output_validation_error",
        message=message,
        instance_path=path,
        schema_path=tuple(error.absolute_schema_path),
        validator=validator,
        contract_digest=contract.schema_digest,
    )


def _pydantic_diagnostics(
    error: PydanticValidationError,
    *,
    contract: StructuredOutputContract,
) -> tuple[StructuredOutputDiagnostic, ...]:
    diagnostics: list[StructuredOutputDiagnostic] = []
    for item in error.errors(include_url=False)[: contract.limits.max_diagnostics]:
        location = tuple(part for part in item.get("loc", ()) if isinstance(part, (str, int)))
        diagnostics.append(
            StructuredOutputDiagnostic(
                code="structured_output_typed_validation_error",
                message=f"structured output at {_json_pointer(location)} failed typed validation",
                instance_path=location,
                validator=str(item.get("type") or "pydantic"),
                contract_digest=contract.schema_digest,
            )
        )
    if not diagnostics:
        diagnostics.append(
            StructuredOutputDiagnostic(
                code="structured_output_typed_validation_error",
                message="structured output failed typed model validation",
                validator="pydantic",
                contract_digest=contract.schema_digest,
            )
        )
    return tuple(diagnostics)


def _diagnostic_summary(diagnostics: tuple[StructuredOutputDiagnostic, ...]) -> str:
    first = diagnostics[0]
    if len(diagnostics) == 1:
        return first.message
    return f"{first.message} ({len(diagnostics)} validation issues)"


def _json_pointer(path: tuple[str | int, ...]) -> str:
    if not path:
        return "$"
    encoded = "/".join(str(item).replace("~", "~0").replace("/", "~1") for item in path)
    return f"$/{encoded}"
