from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Mapping

from framework.llm.cache.key import LLMCacheKey, canonical_json_bytes
from framework.llm.models.request import LLMRequest
from framework.llm.models.response import LLMResponse
from framework.llm.models.usage import TokenUsage
from framework.llm.structured_output import (
    ManagedStructuredOutputError,
    StructuredOutputCacheIdentity,
    require_managed_structured_output,
    validate_compiled_structured_output,
)
from framework.shared.graph_identity import GraphExecutionIdentity


CACHE_ENTRY_SCHEMA_VERSION = "v3"
_SAFE_RESPONSE_METADATA_KEYS = {
    "finish_reason",
    "response_format",
    "stop_reason",
    "structured_output_validation",
}


class CacheResponseValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CacheEntry:
    entry_schema_version: str
    cache_key_version: str
    created_at: float
    source_deployment_id: str
    source_provider: str
    source_model: str
    response: dict[str, Any]
    structured_output_identity: StructuredOutputCacheIdentity | None = None
    source_execution_identity: GraphExecutionIdentity | None = None

    @classmethod
    def from_response(
        cls,
        *,
        key: LLMCacheKey,
        request: LLMRequest,
        response: LLMResponse,
        created_at: float | None = None,
    ) -> CacheEntry:
        _validate_cache_execution_identity(
            source=response.execution_identity,
            consumer=request.execution_identity,
            require_exact=True,
        )
        projected = CacheResponseValidator.project(request=request, response=response)
        timestamp = time.time() if created_at is None else float(created_at)
        if not math.isfinite(timestamp) or timestamp < 0:
            raise CacheResponseValidationError("created_at must be a finite non-negative value")
        return cls(
            entry_schema_version=CACHE_ENTRY_SCHEMA_VERSION,
            cache_key_version=key.key_version,
            created_at=timestamp,
            source_deployment_id=key.deployment_id,
            source_provider=key.provider,
            source_model=key.model,
            response=projected,
            structured_output_identity=key.structured_output_identity,
            source_execution_identity=response.execution_identity,
        )

    def to_response(self, *, request: LLMRequest | None = None) -> LLMResponse:
        response = replace(
            CacheResponseValidator.restore(self.response),
            execution_identity=self.source_execution_identity,
        )
        if request is not None:
            CacheResponseValidator.validate(request=request, response=response)
            _validate_cache_execution_identity(
                source=self.source_execution_identity,
                consumer=request.execution_identity,
                require_exact=False,
            )
            metadata = dict(response.metadata)
            if self.source_execution_identity is not None:
                metadata["llm_cache_source_execution_identity"] = (
                    self.source_execution_identity.to_dict()
                )
            response = replace(
                response,
                metadata=metadata,
                execution_identity=request.execution_identity,
            )
        return response

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_schema_version": self.entry_schema_version,
            "cache_key_version": self.cache_key_version,
            "created_at": self.created_at,
            "source_deployment_id": self.source_deployment_id,
            "source_provider": self.source_provider,
            "source_model": self.source_model,
            "response": deepcopy(self.response),
            "structured_output_identity": (
                self.structured_output_identity.to_dict()
                if self.structured_output_identity is not None
                else None
            ),
            "source_execution_identity": (
                self.source_execution_identity.to_dict()
                if self.source_execution_identity is not None
                else None
            ),
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CacheEntry:
        if not isinstance(payload, Mapping):
            raise CacheResponseValidationError("cache entry must be an object")
        version = payload.get("entry_schema_version")
        if version != CACHE_ENTRY_SCHEMA_VERSION:
            raise CacheResponseValidationError("unsupported cache entry schema version")
        key_version = _required_text(payload.get("cache_key_version"), "cache_key_version")
        created_at = _finite_non_negative(payload.get("created_at"), "created_at")
        response_payload = payload.get("response")
        if not isinstance(response_payload, Mapping):
            raise CacheResponseValidationError("cache entry response must be an object")
        response = dict(response_payload)
        CacheResponseValidator.restore(response)
        raw_identity = payload.get("structured_output_identity")
        if raw_identity is not None and not isinstance(raw_identity, Mapping):
            raise CacheResponseValidationError(
                "structured-output cache identity must be an object or null"
            )
        try:
            structured_output_identity = (
                StructuredOutputCacheIdentity.from_metadata(raw_identity)
                if isinstance(raw_identity, Mapping)
                else None
            )
        except ManagedStructuredOutputError as exc:
            raise CacheResponseValidationError(
                "structured-output cache identity is invalid"
            ) from exc
        raw_execution_identity = payload.get("source_execution_identity")
        if raw_execution_identity is not None and not isinstance(
            raw_execution_identity,
            Mapping,
        ):
            raise CacheResponseValidationError(
                "cache source execution identity must be an object or null"
            )
        try:
            source_execution_identity = (
                GraphExecutionIdentity.from_dict(raw_execution_identity)
                if isinstance(raw_execution_identity, Mapping)
                else None
            )
        except (TypeError, ValueError) as exc:
            raise CacheResponseValidationError(
                "cache source execution identity is invalid"
            ) from exc
        return cls(
            entry_schema_version=version,
            cache_key_version=key_version,
            created_at=created_at,
            source_deployment_id=_required_text(
                payload.get("source_deployment_id"),
                "source_deployment_id",
            ),
            source_provider=_required_text(payload.get("source_provider"), "source_provider"),
            source_model=_required_text(payload.get("source_model"), "source_model"),
            response=response,
            structured_output_identity=structured_output_identity,
            source_execution_identity=source_execution_identity,
        )

    @classmethod
    def from_json_bytes(cls, payload: bytes | bytearray | str) -> CacheEntry:
        try:
            decoded = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else payload
            value = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise CacheResponseValidationError("cache entry is not valid JSON") from exc
        if not isinstance(value, dict):
            raise CacheResponseValidationError("cache entry JSON must be an object")
        return cls.from_dict(value)

    def validate_identity(self, key: LLMCacheKey) -> None:
        if self.entry_schema_version != CACHE_ENTRY_SCHEMA_VERSION:
            raise CacheResponseValidationError("cache entry schema version mismatch")
        if self.cache_key_version != key.key_version:
            raise CacheResponseValidationError("cache key version mismatch")
        if self.source_deployment_id != key.deployment_id:
            raise CacheResponseValidationError("cache deployment identity mismatch")
        if self.source_provider != key.provider or self.source_model != key.model:
            raise CacheResponseValidationError("cache provider identity mismatch")
        if self.structured_output_identity != key.structured_output_identity:
            raise CacheResponseValidationError(
                "cache structured-output identity mismatch"
            )


class CacheResponseValidator:
    @classmethod
    def validate(cls, *, request: LLMRequest, response: LLMResponse) -> None:
        if response.tool_calls:
            raise CacheResponseValidationError("tool call responses are not cacheable")
        cls.validate_output_contract(request=request, response=response)

    @classmethod
    def validate_output_contract(cls, *, request: LLMRequest, response: LLMResponse) -> None:
        if response.content is not None and not isinstance(response.content, str):
            raise CacheResponseValidationError("response content must be text or null")
        if response.structured_output is not None and not isinstance(
            response.structured_output,
            dict,
        ):
            raise CacheResponseValidationError("structured output must be an object")

        if request.output_schema is not None:
            if response.structured_output is None:
                raise CacheResponseValidationError("structured output is required")
            contract = request.structured_output_contract()
            if contract is None:
                raise CacheResponseValidationError(
                    "structured-output request has no compiled contract"
                )
            try:
                require_managed_structured_output(request=request, response=response)
                validate_compiled_structured_output(response.structured_output, contract)
            except (ManagedStructuredOutputError, TypeError, ValueError) as exc:
                raise CacheResponseValidationError("structured output validation failed") from exc

        format_type = _response_format_type(request.response_format)
        if format_type in {"json", "json_object", "json_schema"}:
            value: Any = response.structured_output
            if value is None:
                try:
                    value = json.loads(response.content or "")
                except (TypeError, json.JSONDecodeError) as exc:
                    raise CacheResponseValidationError("JSON response is not valid JSON") from exc
            if not isinstance(value, dict):
                raise CacheResponseValidationError("JSON response must be an object")

    @classmethod
    def project(cls, *, request: LLMRequest, response: LLMResponse) -> dict[str, Any]:
        cls.validate(request=request, response=response)
        safe_metadata = {
            key: deepcopy(value)
            for key, value in response.metadata.items()
            if key in _SAFE_RESPONSE_METADATA_KEYS
        }
        try:
            canonical_json_bytes(safe_metadata)
            canonical_json_bytes(response.structured_output)
        except ValueError as exc:
            raise CacheResponseValidationError("response contains unsupported cache values") from exc
        return {
            "content": response.content,
            "usage": response.usage.to_dict(),
            "metadata": safe_metadata,
            "structured_output": deepcopy(response.structured_output),
            "tool_calls": [],
            "model": response.model,
        }

    @classmethod
    def restore(cls, payload: Mapping[str, Any]) -> LLMResponse:
        if not isinstance(payload, Mapping):
            raise CacheResponseValidationError("cached response must be an object")
        allowed = {
            "content",
            "usage",
            "metadata",
            "structured_output",
            "tool_calls",
            "model",
        }
        if set(payload) - allowed:
            raise CacheResponseValidationError("cached response contains unsupported fields")
        tool_calls = payload.get("tool_calls")
        if tool_calls not in (None, []):
            raise CacheResponseValidationError("cached response contains tool calls")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping) or set(metadata) - _SAFE_RESPONSE_METADATA_KEYS:
            raise CacheResponseValidationError("cached response metadata is unsafe")
        structured = payload.get("structured_output")
        if structured is not None and not isinstance(structured, dict):
            raise CacheResponseValidationError("cached structured output must be an object")
        content = payload.get("content")
        if content is not None and not isinstance(content, str):
            raise CacheResponseValidationError("cached response content must be text or null")
        model = payload.get("model")
        if model is not None and not isinstance(model, str):
            raise CacheResponseValidationError("cached response model must be text or null")
        usage = payload.get("usage")
        if usage is not None and not isinstance(usage, Mapping):
            raise CacheResponseValidationError("cached response usage must be an object")
        return LLMResponse(
            content=content,
            usage=TokenUsage.from_dict(dict(usage or {})),
            metadata=deepcopy(dict(metadata)),
            structured_output=deepcopy(structured),
            tool_calls=[],
            model=model,
            raw={},
        )


def _response_format_type(value: str | dict[str, Any] | None) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        format_type = value.get("type")
        return str(format_type) if format_type is not None else None
    return None


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CacheResponseValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _finite_non_negative(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CacheResponseValidationError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise CacheResponseValidationError(f"{field} must be finite and non-negative")
    return parsed


def _validate_cache_execution_identity(
    *,
    source: GraphExecutionIdentity | None,
    consumer: GraphExecutionIdentity | None,
    require_exact: bool,
) -> None:
    if source is None or consumer is None:
        if source != consumer:
            raise CacheResponseValidationError(
                "cache source and consumer execution scopes do not match"
            )
        return
    if require_exact:
        matches = source == consumer
    else:
        matches = (
            source.run_id,
            source.graph_id,
            source.graph_version,
            source.graph_ref,
            source.graph_checksum,
            source.node_id,
            source.node_instance_id,
        ) == (
            consumer.run_id,
            consumer.graph_id,
            consumer.graph_version,
            consumer.graph_ref,
            consumer.graph_checksum,
            consumer.node_id,
            consumer.node_instance_id,
        )
    if not matches:
        raise CacheResponseValidationError(
            "cache source Graph stage identity does not match consumer"
        )
