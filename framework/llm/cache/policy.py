from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from framework.llm.cache.contracts import CacheContext, CacheEligibility, CacheMode
from framework.llm.cache.key import CacheCanonicalizationError, canonical_json_bytes
from framework.llm.models.request import LLMRequest


@dataclass(frozen=True)
class LLMCachePolicy:
    mode: CacheMode | str = CacheMode.DISABLED
    enabled: bool | None = None
    ttl_seconds: float | None = 300.0
    max_entry_bytes: int = 1_048_576
    cacheable_task_types: tuple[str, ...] = ()
    no_cache_agent_ids: tuple[str, ...] = ()
    required_dependencies: tuple[str, ...] = ()
    freshness_sensitive_task_types: tuple[str, ...] = (
        "live_research",
        "latest",
        "current",
    )
    allow_deterministic_seed: bool = False

    def __post_init__(self) -> None:
        parsed_mode = self.mode if isinstance(self.mode, CacheMode) else CacheMode(str(self.mode))
        if self.enabled is True and parsed_mode is CacheMode.DISABLED:
            parsed_mode = CacheMode.READ_WRITE
        if self.enabled is False:
            parsed_mode = CacheMode.DISABLED
        object.__setattr__(self, "mode", parsed_mode)
        if self.ttl_seconds is not None:
            ttl = float(self.ttl_seconds)
            if not math.isfinite(ttl) or ttl <= 0:
                raise ValueError("ttl_seconds must be a finite positive number")
            object.__setattr__(self, "ttl_seconds", ttl)
        if isinstance(self.max_entry_bytes, bool) or int(self.max_entry_bytes) <= 0:
            raise ValueError("max_entry_bytes must be greater than zero")
        object.__setattr__(self, "max_entry_bytes", int(self.max_entry_bytes))
        object.__setattr__(
            self,
            "cacheable_task_types",
            _normalized_names(self.cacheable_task_types, field="cacheable_task_types"),
        )
        object.__setattr__(
            self,
            "no_cache_agent_ids",
            _normalized_names(self.no_cache_agent_ids, field="no_cache_agent_ids"),
        )
        object.__setattr__(
            self,
            "required_dependencies",
            _normalized_names(self.required_dependencies, field="required_dependencies"),
        )
        object.__setattr__(
            self,
            "freshness_sensitive_task_types",
            _normalized_names(
                self.freshness_sensitive_task_types,
                field="freshness_sensitive_task_types",
            ),
        )

    def evaluate(self, request: LLMRequest) -> CacheEligibility:
        if self.mode is CacheMode.DISABLED:
            return CacheEligibility(False, "cache_disabled")

        task_type = request.metadata.get("task_type")
        if not isinstance(task_type, str) or task_type not in self.cacheable_task_types:
            return CacheEligibility(False, "task_type_not_allowlisted")

        agent_id = request.metadata.get("agent_id")
        if isinstance(agent_id, str) and agent_id in self.no_cache_agent_ids:
            return CacheEligibility(False, "agent_not_cacheable")

        context = CacheContext.from_request(request)
        if context.malformed:
            return CacheEligibility(False, "malformed_cache_context", context)
        if context.scope is None or not context.scope.complete:
            return CacheEligibility(False, "missing_cache_scope", context)

        if request.temperature != 0:
            seeded = self.allow_deterministic_seed and context.deterministic_seed is not None
            if not seeded:
                return CacheEligibility(False, "nondeterministic_temperature", context)

        if request.tools:
            return CacheEligibility(False, "tool_capability_present", context)
        if context.side_effect_candidate:
            return CacheEligibility(False, "side_effect_candidate", context)
        if context.freshness_sensitive or task_type in self.freshness_sensitive_task_types:
            return CacheEligibility(False, "freshness_sensitive_task", context)

        if context.dependencies.missing(self.required_dependencies):
            return CacheEligibility(False, "missing_dependency_revision", context)
        if not _supported_output_contract(request.response_format, request.output_schema):
            return CacheEligibility(False, "unsupported_output_contract", context)

        try:
            canonical_json_bytes(context.dependencies.to_key_payload())
            canonical_json_bytes(dict(context.semantic_metadata))
        except CacheCanonicalizationError:
            return CacheEligibility(False, "unsupported_metadata", context)
        return CacheEligibility(True, "eligible", context)

    def allows(self, request: LLMRequest) -> bool:
        """Compatibility predicate for the development-only `CachedLLMClient`."""
        if self.enabled is not True and self.mode is CacheMode.DISABLED:
            return False
        agent_id = request.metadata.get("agent_id")
        if agent_id in self.no_cache_agent_ids:
            return False
        task_type = request.metadata.get("task_type")
        return isinstance(task_type, str) and task_type in self.cacheable_task_types


def _supported_output_contract(
    response_format: str | dict[str, Any] | None,
    output_schema: dict[str, Any] | None,
) -> bool:
    if output_schema is not None and not isinstance(output_schema, dict):
        return False
    if response_format is None or isinstance(response_format, str):
        return response_format in {None, "text", "json", "json_object", "json_schema"}
    if not isinstance(response_format, dict):
        return False
    format_type = response_format.get("type")
    return format_type in {None, "text", "json", "json_object", "json_schema"}


def _normalized_names(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    parsed: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must contain non-empty strings")
        parsed.append(value.strip())
    return tuple(dict.fromkeys(parsed))
