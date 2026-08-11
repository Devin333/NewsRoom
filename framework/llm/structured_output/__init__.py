from __future__ import annotations

from framework.llm.structured_output.contracts import (
    LOCAL_STRUCTURED_OUTPUT_DIALECT,
    LLMStructuredOutputError,
    LLMStructuredOutputParseError,
    LLMStructuredOutputSchemaError,
    LLMStructuredOutputValidationError,
    StructuredOutputContract,
    StructuredOutputDiagnostic,
    StructuredOutputLimits,
    StructuredOutputValidationResult,
)
from framework.llm.structured_output.decoder import (
    StrictStructuredOutputDecoder,
    decode_structured_output,
)
from framework.llm.structured_output.managed import (
    ManagedStructuredOutputError,
    STRUCTURED_OUTPUT_VALIDATION_METADATA_KEY,
    StructuredOutputCacheIdentity,
    managed_validation_metadata,
    require_managed_structured_output,
    require_managed_structured_output_for_contract,
    structured_output_response_fingerprint,
    structured_output_text_fingerprint,
)
from framework.llm.structured_output.preflight import (
    compile_structured_output_contract,
    schema_for_provider,
)
from framework.llm.structured_output.observability import (
    STRUCTURED_OUTPUT_EVENT_TYPES,
    StructuredOutputEvent,
    StructuredOutputEventSink,
    StructuredOutputMetricPoint,
    project_structured_output_metrics,
)
from framework.llm.structured_output.projection import (
    LLMStructuredOutputProjectionError,
    ProviderSchemaProjection,
    ProviderSchemaProjectionMode,
    ProviderStructuredOutputCapability,
    ProviderStructuredOutputMode,
    ProviderStructuredOutputPolicy,
    project_structured_output_contract,
    structured_output_enforcement_keywords,
)
from framework.llm.structured_output.validator import (
    validate_compiled_structured_output,
    validate_structured_output,
    validate_structured_output_result,
)

__all__ = [
    "LOCAL_STRUCTURED_OUTPUT_DIALECT",
    "LLMStructuredOutputError",
    "LLMStructuredOutputParseError",
    "LLMStructuredOutputProjectionError",
    "LLMStructuredOutputSchemaError",
    "LLMStructuredOutputValidationError",
    "ManagedStructuredOutputError",
    "ProviderSchemaProjection",
    "ProviderSchemaProjectionMode",
    "ProviderStructuredOutputCapability",
    "ProviderStructuredOutputMode",
    "ProviderStructuredOutputPolicy",
    "StrictStructuredOutputDecoder",
    "StructuredOutputContract",
    "StructuredOutputCacheIdentity",
    "StructuredOutputDiagnostic",
    "StructuredOutputLimits",
    "StructuredOutputEvent",
    "StructuredOutputEventSink",
    "StructuredOutputMetricPoint",
    "StructuredOutputValidationResult",
    "compile_structured_output_contract",
    "decode_structured_output",
    "managed_validation_metadata",
    "project_structured_output_contract",
    "project_structured_output_metrics",
    "require_managed_structured_output",
    "require_managed_structured_output_for_contract",
    "schema_for_provider",
    "structured_output_enforcement_keywords",
    "structured_output_response_fingerprint",
    "structured_output_text_fingerprint",
    "STRUCTURED_OUTPUT_VALIDATION_METADATA_KEY",
    "STRUCTURED_OUTPUT_EVENT_TYPES",
    "validate_compiled_structured_output",
    "validate_structured_output",
    "validate_structured_output_result",
]
