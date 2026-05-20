from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol

from framework.agent.runtime.redaction import redact_sensitive_values


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    estimated_cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_tokens

    def to_dict(self) -> dict[str, int | float | None]:
        payload: dict[str, int | float | None] = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.estimated_cost_usd is not None:
            payload["estimated_cost_usd"] = self.estimated_cost_usd
        return payload

    @classmethod
    def from_any(cls, value: Any) -> "TokenUsage":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls()
        data = value.to_dict() if hasattr(value, "to_dict") else value
        if not isinstance(data, dict):
            return cls()
        return cls(
            input_tokens=int(data.get("input_tokens") or 0),
            output_tokens=int(data.get("output_tokens") or 0),
            reasoning_tokens=int(data.get("reasoning_tokens") or 0),
            cached_input_tokens=int(data.get("cached_input_tokens") or 0),
            estimated_cost_usd=(
                float(data["estimated_cost_usd"])
                if data.get("estimated_cost_usd") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class GlobalBudgetPolicy:
    max_total_cost_usd: float | None = None
    max_total_tokens: int | None = None
    max_llm_calls: int | None = None
    on_budget_exceeded: str = "fail"


@dataclass(frozen=True)
class GlobalBudgetUsage:
    llm_calls: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "llm_calls": self.llm_calls,
            "token_usage": self.token_usage.to_dict(),
            "estimated_cost_usd": self.estimated_cost_usd,
        }


@dataclass(frozen=True)
class GlobalBudgetCheck:
    usage: GlobalBudgetUsage
    within_budget: bool
    violations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "usage": self.usage.to_dict(),
            "within_budget": self.within_budget,
            "violations": list(self.violations),
        }


class GlobalBudgetExceededError(RuntimeError):
    def __init__(self, check: Any) -> None:
        super().__init__("global budget exceeded: " + ", ".join(getattr(check, "violations", []) or []))
        self.check = check
        self.error_type = "global_budget_exceeded"


class GlobalBudgetTracker:
    def __init__(self, policy: GlobalBudgetPolicy) -> None:
        self.policy = policy
        self._usage = GlobalBudgetUsage()

    @property
    def usage(self) -> GlobalBudgetUsage:
        return self._usage

    def snapshot(self) -> dict[str, object]:
        return self._usage.to_dict()

    def check_before_llm_call(self, estimated_prompt_tokens: int | None = None) -> GlobalBudgetCheck:
        next_usage = self._preflight_usage(estimated_prompt_tokens=estimated_prompt_tokens)
        return self._check(next_usage, preflight=True)

    def reserve_llm_call(self, estimated_prompt_tokens: int | None = None) -> GlobalBudgetCheck:
        next_usage = self._preflight_usage(estimated_prompt_tokens=estimated_prompt_tokens)
        check = self._check(next_usage, preflight=True)
        self._usage = next_usage
        return check

    def record_llm_call(self, usage: Any, **_: Any) -> GlobalBudgetCheck:
        usage = TokenUsage.from_any(usage)
        next_usage = GlobalBudgetUsage(
            llm_calls=self._usage.llm_calls + 1,
            token_usage=TokenUsage(
                input_tokens=self._usage.token_usage.input_tokens + usage.input_tokens,
                output_tokens=self._usage.token_usage.output_tokens + usage.output_tokens,
                reasoning_tokens=self._usage.token_usage.reasoning_tokens + usage.reasoning_tokens,
                cached_input_tokens=self._usage.token_usage.cached_input_tokens + usage.cached_input_tokens,
            ),
            estimated_cost_usd=self._usage.estimated_cost_usd + float(usage.estimated_cost_usd or 0.0),
        )
        self._usage = next_usage
        return self._check(next_usage, preflight=False)

    def _preflight_usage(self, *, estimated_prompt_tokens: int | None) -> GlobalBudgetUsage:
        prompt_tokens = int(estimated_prompt_tokens or 0)
        return GlobalBudgetUsage(
            llm_calls=self._usage.llm_calls + 1,
            token_usage=TokenUsage(
                input_tokens=self._usage.token_usage.input_tokens + max(0, prompt_tokens),
                output_tokens=self._usage.token_usage.output_tokens,
                reasoning_tokens=self._usage.token_usage.reasoning_tokens,
                cached_input_tokens=self._usage.token_usage.cached_input_tokens,
            ),
            estimated_cost_usd=self._usage.estimated_cost_usd,
        )

    def _check(self, usage: GlobalBudgetUsage, *, preflight: bool) -> GlobalBudgetCheck:
        violations: list[str] = []
        if self.policy.max_llm_calls is not None and usage.llm_calls > self.policy.max_llm_calls:
            violations.append("max_llm_calls")
        if not preflight:
            if self.policy.max_total_tokens is not None and usage.token_usage.total_tokens > self.policy.max_total_tokens:
                violations.append("max_total_tokens")
            if self.policy.max_total_cost_usd is not None and usage.estimated_cost_usd > self.policy.max_total_cost_usd:
                violations.append("max_total_cost_usd")
        check = GlobalBudgetCheck(usage=usage, within_budget=not violations, violations=tuple(violations))
        if violations and self.policy.on_budget_exceeded == "fail":
            raise GlobalBudgetExceededError(check)
        return check


@dataclass(frozen=True)
class LLMRequest:
    messages: list[dict[str, str]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    response_format: str | dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    output_schema_name: str = "structured_output"

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "messages": [dict(message) for message in self.messages],
            "tools": deepcopy(self.tools),
            "metadata": dict(self.metadata),
        }
        if self.response_format is not None:
            payload["response_format"] = deepcopy(self.response_format)
        if self.output_schema is not None:
            payload["output_schema"] = deepcopy(self.output_schema)
            payload["output_schema_name"] = self.output_schema_name
        return redact_sensitive_values(payload) if redact else payload


@dataclass(frozen=True)
class LLMToolCall:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str | None = None
    provider_tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": deepcopy(self.arguments),
            "raw_arguments": self.raw_arguments,
            "provider_tool_call_id": self.provider_tool_call_id,
            "metadata": dict(self.metadata),
        }
        return redact_sensitive_values(payload) if redact else payload


@dataclass(frozen=True)
class LLMResponse:
    content: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    metadata: dict[str, Any] = field(default_factory=dict)
    structured_output: dict[str, Any] | None = None
    tool_calls: list[LLMToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "usage", TokenUsage.from_any(self.usage))

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "content": self.content,
            "usage": self.usage.to_dict(),
            "metadata": dict(self.metadata),
            "structured_output": deepcopy(self.structured_output),
            "tool_calls": [_tool_call_to_dict(tool_call, redact=False) for tool_call in self.tool_calls],
        }
        return redact_sensitive_values(payload) if redact else payload

    @classmethod
    def from_any(cls, value: Any) -> "LLMResponse":
        if isinstance(value, cls):
            return value
        if value is None:
            raise TypeError("LLM response is required")
        return cls(
            content=str(getattr(value, "content", "")),
            usage=TokenUsage.from_any(getattr(value, "usage", None)),
            metadata=dict(getattr(value, "metadata", {}) or {}),
            structured_output=(
                dict(getattr(value, "structured_output"))
                if isinstance(getattr(value, "structured_output", None), dict)
                else None
            ),
            tool_calls=[_coerce_tool_call(item) for item in getattr(value, "tool_calls", [])],
        )


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> Any:
        ...


class LLMStructuredOutputValidationError(ValueError):
    """Raised when parsed structured output violates the requested schema."""


@dataclass(frozen=True)
class LLMStreamEvent:
    event_type: str
    text_delta: str | None = None
    tool_call: LLMToolCall | None = None
    tool_call_delta: dict[str, Any] | None = None
    usage_delta: TokenUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "event_type": self.event_type,
            "text_delta": self.text_delta,
            "tool_call": self.tool_call.to_dict(redact=False) if self.tool_call else None,
            "tool_call_delta": dict(self.tool_call_delta or {}),
            "usage_delta": self.usage_delta.to_dict() if self.usage_delta else None,
            "metadata": dict(self.metadata),
        }
        return redact_sensitive_values(payload) if redact else payload

    @classmethod
    def from_any(cls, value: Any) -> "LLMStreamEvent":
        if isinstance(value, cls):
            return value
        return cls(
            event_type=str(getattr(value, "event_type", "")),
            text_delta=getattr(value, "text_delta", None),
            tool_call=_coerce_optional_tool_call(getattr(value, "tool_call", None)),
            tool_call_delta=(
                dict(getattr(value, "tool_call_delta"))
                if isinstance(getattr(value, "tool_call_delta", None), dict)
                else None
            ),
            usage_delta=TokenUsage.from_any(getattr(value, "usage_delta", None))
            if getattr(value, "usage_delta", None) is not None
            else None,
            metadata=dict(getattr(value, "metadata", {}) or {}),
        )


class LLMStreamAccumulator:
    def __init__(self, *, metadata: dict[str, Any] | None = None) -> None:
        self._text_parts: list[str] = []
        self._tool_calls: list[LLMToolCall] = []
        self._usage = TokenUsage()
        self._metadata = dict(metadata or {})

    def add_event(self, event: Any) -> None:
        event = LLMStreamEvent.from_any(event)
        if event.event_type == "text_delta" and event.text_delta:
            self._text_parts.append(event.text_delta)
        elif event.event_type == "tool_call_complete" and event.tool_call:
            self._tool_calls.append(event.tool_call)
        elif event.event_type == "usage_delta" and event.usage_delta:
            self._usage = TokenUsage(
                input_tokens=self._usage.input_tokens + event.usage_delta.input_tokens,
                output_tokens=self._usage.output_tokens + event.usage_delta.output_tokens,
                reasoning_tokens=self._usage.reasoning_tokens + event.usage_delta.reasoning_tokens,
                cached_input_tokens=self._usage.cached_input_tokens + event.usage_delta.cached_input_tokens,
                estimated_cost_usd=_sum_optional_cost(
                    self._usage.estimated_cost_usd,
                    event.usage_delta.estimated_cost_usd,
                ),
            )
        elif event.event_type == "message_complete":
            self._metadata.update(event.metadata)
        elif event.event_type == "error":
            raise RuntimeError(f"LLM stream error: {event.metadata.get('error_type') or 'stream_error'}")

    def to_response(self) -> LLMResponse:
        return LLMResponse(
            content="".join(self._text_parts),
            usage=self._usage,
            metadata=dict(self._metadata),
            tool_calls=list(self._tool_calls),
        )


def validate_structured_output(value: Any, schema: Any) -> None:
    schema = _schema_to_dict(schema)
    if not isinstance(schema, dict):
        raise LLMStructuredOutputValidationError("schema must be an object")
    _validate_value(value, schema, "$")


def _schema_to_dict(schema: Any) -> dict[str, Any]:
    if isinstance(schema, dict):
        return schema
    model_json_schema = getattr(schema, "model_json_schema", None)
    if callable(model_json_schema):
        exported = model_json_schema()
        if isinstance(exported, dict):
            return exported
    schema_method = getattr(schema, "schema", None)
    if callable(schema_method):
        exported = schema_method()
        if isinstance(exported, dict):
            return exported
    raise LLMStructuredOutputValidationError("schema must be an object")


def _validate_value(value: Any, schema: dict[str, Any], path: str) -> None:
    if not isinstance(schema, dict):
        raise LLMStructuredOutputValidationError(f"{path}: schema must be an object")
    if "enum" in schema:
        allowed = schema["enum"]
        if not isinstance(allowed, list):
            raise LLMStructuredOutputValidationError(f"{path}: enum must be an array")
        if value not in allowed:
            raise LLMStructuredOutputValidationError(f"{path}: value is not in enum")
    if "const" in schema and value != schema["const"]:
        raise LLMStructuredOutputValidationError(f"{path}: value does not match const")
    expected_type = schema.get("type")
    if expected_type is None:
        if "properties" in schema or "required" in schema:
            expected_type = "object"
        elif "items" in schema:
            expected_type = "array"
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not all(isinstance(item, str) for item in expected_types):
            raise LLMStructuredOutputValidationError(f"{path}: type must be a string or array")
        if not any(_matches_json_type(value, item) for item in expected_types):
            raise LLMStructuredOutputValidationError(
                f"{path}: expected {' or '.join(expected_types)}, got {type(value).__name__}"
            )
    if isinstance(value, dict):
        _validate_object(value, schema, path)
    elif isinstance(value, list):
        _validate_array(value, schema, path)
    elif isinstance(value, str):
        _validate_string(value, schema, path)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _validate_number(value, schema, path)


def _validate_object(value: dict[str, Any], schema: dict[str, Any], path: str) -> None:
    min_properties = _optional_non_negative_int(schema, "minProperties", path)
    if min_properties is not None and len(value) < min_properties:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected at least {min_properties} properties, got {len(value)}"
        )
    max_properties = _optional_non_negative_int(schema, "maxProperties", path)
    if max_properties is not None and len(value) > max_properties:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected at most {max_properties} properties, got {len(value)}"
        )
    required = schema.get("required", []) or []
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise LLMStructuredOutputValidationError(f"{path}: required must be an array of strings")
    for property_name in required:
        if property_name not in value:
            raise LLMStructuredOutputValidationError(f"{path}: missing required property: {property_name}")
    properties = schema.get("properties", {}) or {}
    if not isinstance(properties, dict):
        raise LLMStructuredOutputValidationError(f"{path}: properties must be an object")
    for property_name, property_schema in properties.items():
        if property_name in value:
            _validate_value(value[property_name], property_schema, f"{path}.{property_name}")
    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(value) - set(properties))
        if unexpected:
            raise LLMStructuredOutputValidationError(f"{path}: unexpected properties: {', '.join(unexpected)}")


def _validate_array(value: list[Any], schema: dict[str, Any], path: str) -> None:
    min_items = _optional_non_negative_int(schema, "minItems", path)
    if min_items is not None and len(value) < min_items:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected at least {min_items} items, got {len(value)}"
        )
    max_items = _optional_non_negative_int(schema, "maxItems", path)
    if max_items is not None and len(value) > max_items:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected at most {max_items} items, got {len(value)}"
        )
    if schema.get("uniqueItems") is True:
        seen = set()
        for index, item in enumerate(value):
            key = _stable_value_key(item)
            if key in seen:
                raise LLMStructuredOutputValidationError(f"{path}: duplicate item at index {index}")
            seen.add(key)
    item_schema = schema.get("items")
    if item_schema is None:
        return
    if not isinstance(item_schema, dict):
        raise LLMStructuredOutputValidationError(f"{path}: items must be an object")
    for index, item in enumerate(value):
        _validate_value(item, item_schema, f"{path}[{index}]")


def _validate_string(value: str, schema: dict[str, Any], path: str) -> None:
    min_length = _optional_non_negative_int(schema, "minLength", path)
    if min_length is not None and len(value) < min_length:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected string length at least {min_length}, got {len(value)}"
        )
    max_length = _optional_non_negative_int(schema, "maxLength", path)
    if max_length is not None and len(value) > max_length:
        raise LLMStructuredOutputValidationError(
            f"{path}: expected string length at most {max_length}, got {len(value)}"
        )
    pattern = schema.get("pattern")
    if pattern is None:
        return
    if not isinstance(pattern, str):
        raise LLMStructuredOutputValidationError(f"{path}: pattern must be a string")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise LLMStructuredOutputValidationError(f"{path}: invalid pattern: {exc}") from exc
    if not compiled.search(value):
        raise LLMStructuredOutputValidationError(f"{path}: string does not match pattern")


def _validate_number(value: int | float, schema: dict[str, Any], path: str) -> None:
    minimum = _optional_number(schema, "minimum", path)
    if minimum is not None and value < minimum:
        raise LLMStructuredOutputValidationError(f"{path}: expected number >= {minimum}, got {value}")
    maximum = _optional_number(schema, "maximum", path)
    if maximum is not None and value > maximum:
        raise LLMStructuredOutputValidationError(f"{path}: expected number <= {maximum}, got {value}")


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    raise LLMStructuredOutputValidationError(f"unsupported schema type: {expected_type}")


def _optional_non_negative_int(schema: dict[str, Any], keyword: str, path: str) -> int | None:
    if keyword not in schema:
        return None
    value = schema[keyword]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LLMStructuredOutputValidationError(f"{path}: {keyword} must be a non-negative integer")
    return value


def _optional_number(schema: dict[str, Any], keyword: str, path: str) -> float | None:
    if keyword not in schema:
        return None
    value = schema[keyword]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise LLMStructuredOutputValidationError(f"{path}: {keyword} must be a number")
    return float(value)


def _stable_value_key(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{key}:{_stable_value_key(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_stable_value_key(item) for item in value) + "]"
    return repr(value)


def _coerce_tool_call(value: Any) -> LLMToolCall:
    if isinstance(value, LLMToolCall):
        return value
    return LLMToolCall(
        tool_call_id=str(getattr(value, "tool_call_id", "")),
        tool_name=str(getattr(value, "tool_name", "")),
        arguments=dict(getattr(value, "arguments", {}) or {}),
        raw_arguments=getattr(value, "raw_arguments", None),
        provider_tool_call_id=getattr(value, "provider_tool_call_id", None),
        metadata=dict(getattr(value, "metadata", {}) or {}),
    )


def _coerce_optional_tool_call(value: Any) -> LLMToolCall | None:
    if value is None:
        return None
    return _coerce_tool_call(value)


def _tool_call_to_dict(value: Any, *, redact: bool) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict(redact=redact)
    return _coerce_tool_call(value).to_dict(redact=redact)


def _sum_optional_cost(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return round(float(left or 0.0) + float(right or 0.0), 12)
