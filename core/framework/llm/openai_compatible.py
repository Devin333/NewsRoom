from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.framework.llm.models import LLMRequest, LLMResponse, TokenUsage
from core.framework.llm.redaction import redact_sensitive_values
from core.framework.llm.streaming import LLMStreamEvent
from core.framework.llm.tool_adapters import (
    LLMToolCallParseError,
    LLMToolSchemaError,
    parse_openai_tool_calls,
    to_openai_tools,
)


class LLMConfigurationError(RuntimeError):
    """Raised when LLM provider configuration is incomplete."""


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider request fails."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        error_type: str = "unknown_llm_error",
        retryable: bool = False,
        status_code: int | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.error_type = error_type
        self.retryable = retryable
        self.status_code = status_code
        self.attempts = attempts

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message": str(self),
            "provider": self.provider,
            "error_type": self.error_type,
            "retryable": self.retryable,
            "status_code": self.status_code,
            "attempts": self.attempts,
        }
        if redact:
            return redact_sensitive_values(payload)
        return payload


Transport = Callable[[Request, float], bytes]
StreamTransport = Callable[[Request, float], Iterable[bytes | str]]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class LLMRetryPolicy:
    max_attempts: int = 1
    retry_delay_seconds: tuple[float, ...] = (0.0,)
    retryable_status_codes: tuple[int, ...] = (408, 409, 429, 500, 502, 503, 504)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        object.__setattr__(self, "retry_delay_seconds", tuple(self.retry_delay_seconds))
        object.__setattr__(self, "retryable_status_codes", tuple(self.retryable_status_codes))
        if any(delay < 0 for delay in self.retry_delay_seconds):
            raise ValueError("retry delays must be non-negative")

    def delay_after_attempt(self, attempt: int) -> float:
        if not self.retry_delay_seconds:
            return 0.0
        index = min(max(attempt - 1, 0), len(self.retry_delay_seconds) - 1)
        return self.retry_delay_seconds[index]


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    provider: str
    base_url: str
    model: str
    api_key_env: str
    timeout_seconds: float = 90.0

    @classmethod
    def dashscope_defaults(cls) -> OpenAICompatibleConfig:
        return cls(
            provider="dashscope",
            base_url=os.environ.get(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            model=os.environ.get("NEWS_LLM_MODEL", "deepseek-v4-flash"),
            api_key_env="DASHSCOPE_API_KEY",
        )

    def resolve_api_key(self) -> str:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise LLMConfigurationError(f"missing required environment variable: {self.api_key_env}")
        return api_key


class OpenAICompatibleClient:
    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        retry_policy: LLMRetryPolicy | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or _urlopen_transport
        self._stream_transport = stream_transport or _urlopen_stream_transport
        self._retry_policy = retry_policy or LLMRetryPolicy()
        self._sleep = sleep or time.sleep

    def complete(self, request: LLMRequest) -> LLMResponse:
        api_key = self.config.resolve_api_key()
        try:
            payload = self._build_payload(request)
        except LLMToolSchemaError as exc:
            raise LLMProviderError(
                f"{self.config.provider} request tool schema is invalid: {exc}",
                provider=self.config.provider,
                error_type="invalid_request_schema",
                retryable=False,
            ) from exc

        for attempt in range(1, self._retry_policy.max_attempts + 1):
            http_request = self._build_http_request(api_key, payload)
            try:
                raw_body = self._transport(http_request, self.config.timeout_seconds)
            except HTTPError as exc:
                error = self._error_from_http(exc, attempts=attempt)
            except (TimeoutError, URLError, OSError) as exc:
                error = self._error_from_network(exc, attempts=attempt)
            else:
                response_payload = self._parse_response_payload(raw_body, attempts=attempt)
                return self._normalize_response(response_payload, request=request, attempts=attempt)

            if not error.retryable or attempt >= self._retry_policy.max_attempts:
                raise error

            self._sleep(self._retry_policy.delay_after_attempt(attempt))

        raise LLMProviderError(
            f"{self.config.provider} request failed before sending",
            provider=self.config.provider,
            attempts=self._retry_policy.max_attempts,
        )

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamEvent]:
        api_key = self.config.resolve_api_key()
        try:
            payload = self._build_payload(request)
        except LLMToolSchemaError as exc:
            raise LLMProviderError(
                f"{self.config.provider} request tool schema is invalid: {exc}",
                provider=self.config.provider,
                error_type="invalid_request_schema",
                retryable=False,
            ) from exc
        payload["stream"] = True

        http_request = self._build_http_request(api_key, payload)
        try:
            lines = self._stream_transport(http_request, self.config.timeout_seconds)
        except HTTPError as exc:
            raise self._error_from_http(exc, attempts=1) from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise self._error_from_network(exc, attempts=1) from exc

        yield LLMStreamEvent(
            event_type="message_start",
            metadata={"provider": self.config.provider, "model": self.config.model},
        )
        assembler = _OpenAIStreamToolCallAssembler(request.tools)
        completed = False
        last_finish_reason: str | None = None
        response_id: str | None = None

        try:
            for raw_line in lines:
                line = _stream_line_text(raw_line)
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    completed = True
                    break
                chunk = self._parse_stream_chunk(data)
                response_id = response_id or _optional_str(chunk.get("id"))
                usage = _usage_from_stream_chunk(chunk)
                if usage is not None:
                    yield LLMStreamEvent(event_type="usage_delta", usage_delta=usage)
                for event in _events_from_stream_chunk(
                    chunk,
                    assembler=assembler,
                    provider=self.config.provider,
                    attempts=1,
                ):
                    if event.event_type == "message_complete":
                        last_finish_reason = event.metadata.get("finish_reason")
                        completed = True
                        continue
                    yield event
        except LLMToolCallParseError as exc:
            raise LLMProviderError(
                f"{self.config.provider} streaming tool call parse failed: {exc}",
                provider=self.config.provider,
                error_type="stream_tool_call_parse_error",
                retryable=False,
                attempts=1,
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMProviderError(
                f"{self.config.provider} stream chunk is not valid JSON",
                provider=self.config.provider,
                error_type="provider_stream_chunk_invalid",
                retryable=False,
                attempts=1,
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise self._error_from_network(exc, attempts=1) from exc

        if not completed:
            last_finish_reason = last_finish_reason or "stream_ended"
        yield LLMStreamEvent(
            event_type="message_complete",
            metadata={
                "provider": self.config.provider,
                "model": self.config.model,
                "response_id": response_id,
                "finish_reason": last_finish_reason or "stop",
                "attempts": 1,
                "retry_count": 0,
            },
        )

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": request.messages,
        }
        if request.tools:
            payload["tools"] = to_openai_tools(request.tools)

        response_format = _provider_response_format(request)
        if response_format is not None:
            payload["response_format"] = response_format
        return payload

    def _build_http_request(self, api_key: str, payload: dict[str, Any]) -> Request:
        return Request(
            url=f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def _parse_response_payload(self, raw_body: bytes, *, attempts: int) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMProviderError(
                f"{self.config.provider} response payload is not valid JSON",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
                retryable=False,
                attempts=attempts,
            ) from exc
        if not isinstance(payload, dict):
            raise LLMProviderError(
                f"{self.config.provider} response payload is not an object",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
                retryable=False,
                attempts=attempts,
            )
        return payload

    def _parse_stream_chunk(self, data: str) -> dict[str, Any]:
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise LLMProviderError(
                f"{self.config.provider} stream chunk is not an object",
                provider=self.config.provider,
                error_type="provider_stream_chunk_invalid",
                retryable=False,
                attempts=1,
            )
        return payload

    def _normalize_response(
        self,
        payload: dict[str, Any],
        *,
        request: LLMRequest,
        attempts: int,
    ) -> LLMResponse:
        choices = payload.get("choices") or []
        if not choices:
            raise LLMProviderError(
                f"{self.config.provider} response missing choices",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
                retryable=False,
                attempts=attempts,
            )
        choice = choices[0]
        if not isinstance(choice, dict):
            raise LLMProviderError(
                f"{self.config.provider} response choice is not an object",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
                retryable=False,
                attempts=attempts,
            )
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            raise LLMProviderError(
                f"{self.config.provider} response message is not an object",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
                retryable=False,
                attempts=attempts,
            )
        try:
            tool_calls = parse_openai_tool_calls(message.get("tool_calls"), request.tools)
        except LLMToolCallParseError as exc:
            raise LLMProviderError(
                f"{self.config.provider} tool call parse failed: {exc}",
                provider=self.config.provider,
                error_type="tool_call_parse_error",
                retryable=False,
                attempts=attempts,
            ) from exc

        content = message.get("content")
        if content is None and tool_calls:
            content = ""
        if not isinstance(content, str):
            raise LLMProviderError(
                f"{self.config.provider} response missing message content",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
                retryable=False,
                attempts=attempts,
            )
        structured_output = None
        if _expects_structured_output(request):
            structured_output = self._parse_structured_output(content, attempts=attempts)

        usage_payload = payload.get("usage") or {}
        if not isinstance(usage_payload, dict):
            usage_payload = {}
        try:
            usage = TokenUsage(
                input_tokens=int(usage_payload.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage_payload.get("completion_tokens", 0) or 0),
            )
        except (TypeError, ValueError) as exc:
            raise LLMProviderError(
                f"{self.config.provider} response usage is invalid",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
                retryable=False,
                attempts=attempts,
            ) from exc
        return LLMResponse(
            content=content,
            usage=usage,
            metadata={
                "provider": self.config.provider,
                "model": self.config.model,
                "response_id": payload.get("id"),
                "attempts": attempts,
                "retry_count": attempts - 1,
            },
            structured_output=structured_output,
            tool_calls=tool_calls,
        )

    def _parse_structured_output(self, content: str, *, attempts: int) -> dict[str, Any]:
        try:
            structured_output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"{self.config.provider} structured output is not valid JSON",
                provider=self.config.provider,
                error_type="structured_output_parse_error",
                retryable=False,
                attempts=attempts,
            ) from exc
        if not isinstance(structured_output, dict):
            raise LLMProviderError(
                f"{self.config.provider} structured output is not a JSON object",
                provider=self.config.provider,
                error_type="structured_output_parse_error",
                retryable=False,
                attempts=attempts,
            )
        return structured_output

    def _error_from_http(self, exc: HTTPError, *, attempts: int) -> LLMProviderError:
        status_code = int(exc.code)
        retryable = status_code in self._retry_policy.retryable_status_codes
        error_type = _error_type_from_http_status(status_code)
        return LLMProviderError(
            f"{self.config.provider} request failed: HTTP {status_code}",
            provider=self.config.provider,
            error_type=error_type,
            retryable=retryable,
            status_code=status_code,
            attempts=attempts,
        )

    def _error_from_network(self, exc: TimeoutError | URLError | OSError, *, attempts: int) -> LLMProviderError:
        reason = getattr(exc, "reason", None)
        is_timeout = isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError)
        error_type = "provider_timeout" if is_timeout else "provider_connection_error"
        return LLMProviderError(
            f"{self.config.provider} request failed: {error_type}",
            provider=self.config.provider,
            error_type=error_type,
            retryable=True,
            attempts=attempts,
        )


def _error_type_from_http_status(status_code: int) -> str:
    if status_code == 400:
        return "invalid_request_schema"
    if status_code in (401, 403):
        return "invalid_api_key"
    if status_code == 404:
        return "invalid_model"
    if status_code == 408:
        return "provider_timeout"
    if status_code == 409:
        return "temporary_provider_error"
    if status_code == 413:
        return "context_length_exceeded"
    if status_code == 429:
        return "rate_limited"
    if 500 <= status_code <= 599:
        return "provider_server_error"
    if 400 <= status_code <= 499:
        return "provider_client_error"
    return "unknown_llm_error"


def _provider_response_format(request: LLMRequest) -> dict[str, Any] | None:
    if request.response_format is not None:
        if isinstance(request.response_format, str):
            return {"type": request.response_format}
        return dict(request.response_format)
    if request.output_schema is not None:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": request.output_schema_name or "structured_output",
                "strict": True,
                "schema": request.output_schema,
            },
        }
    return None


def _expects_structured_output(request: LLMRequest) -> bool:
    if request.output_schema is not None:
        return True
    response_format = request.response_format
    if isinstance(response_format, str):
        return response_format in {"json_object", "json_schema"}
    if isinstance(response_format, dict):
        return response_format.get("type") in {"json_object", "json_schema"}
    return False


class _OpenAIStreamToolCallAssembler:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools
        self._calls: dict[int, dict[str, Any]] = {}

    def add_deltas(self, raw_tool_calls: Any) -> None:
        if raw_tool_calls in (None, []):
            return
        if not isinstance(raw_tool_calls, list):
            raise LLMToolCallParseError("provider streaming tool_calls must be a list")
        for raw_tool_call in raw_tool_calls:
            if not isinstance(raw_tool_call, dict):
                raise LLMToolCallParseError("provider streaming tool_call must be an object")
            index = int(raw_tool_call.get("index", len(self._calls)))
            current = self._calls.setdefault(
                index,
                {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if raw_tool_call.get("id"):
                current["id"] = str(raw_tool_call["id"])
            if raw_tool_call.get("type"):
                current["type"] = str(raw_tool_call["type"])
            function = raw_tool_call.get("function") or {}
            if function and not isinstance(function, dict):
                raise LLMToolCallParseError("provider streaming tool_call function must be an object")
            current_function = current["function"]
            name_delta = function.get("name")
            if name_delta:
                current_function["name"] = f"{current_function.get('name', '')}{name_delta}"
            args_delta = function.get("arguments")
            if args_delta:
                current_function["arguments"] = (
                    f"{current_function.get('arguments', '')}{args_delta}"
                )

    def complete(self):
        raw_calls = []
        for index in sorted(self._calls):
            raw_call = self._calls[index]
            function = raw_call.get("function") or {}
            raw_calls.append(
                {
                    "id": raw_call.get("id") or f"tool_call_{index + 1}",
                    "type": raw_call.get("type") or "function",
                    "function": {
                        "name": function.get("name") or "",
                        "arguments": function.get("arguments") or "{}",
                    },
                }
            )
        return parse_openai_tool_calls(raw_calls, self._tools)


def _events_from_stream_chunk(
    chunk: dict[str, Any],
    *,
    assembler: _OpenAIStreamToolCallAssembler,
    provider: str,
    attempts: int,
) -> list[LLMStreamEvent]:
    choices = chunk.get("choices") or []
    if not isinstance(choices, list):
        raise LLMProviderError(
            f"{provider} stream chunk choices are invalid",
            provider=provider,
            error_type="provider_stream_chunk_invalid",
            retryable=False,
            attempts=attempts,
        )
    events: list[LLMStreamEvent] = []
    for choice in choices:
        if not isinstance(choice, dict):
            raise LLMProviderError(
                f"{provider} stream chunk choice is invalid",
                provider=provider,
                error_type="provider_stream_chunk_invalid",
                retryable=False,
                attempts=attempts,
            )
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            raise LLMProviderError(
                f"{provider} stream chunk delta is invalid",
                provider=provider,
                error_type="provider_stream_chunk_invalid",
                retryable=False,
                attempts=attempts,
            )
        content = delta.get("content")
        if isinstance(content, str) and content:
            events.append(LLMStreamEvent(event_type="text_delta", text_delta=content))
        assembler.add_deltas(delta.get("tool_calls"))
        finish_reason = choice.get("finish_reason")
        if finish_reason == "tool_calls":
            for tool_call in assembler.complete():
                events.append(LLMStreamEvent(event_type="tool_call_complete", tool_call=tool_call))
        if finish_reason:
            events.append(
                LLMStreamEvent(
                    event_type="message_complete",
                    metadata={"finish_reason": str(finish_reason)},
                )
            )
    return events


def _usage_from_stream_chunk(chunk: dict[str, Any]) -> TokenUsage | None:
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None
    return TokenUsage(
        input_tokens=int(usage.get("prompt_tokens", 0) or 0),
        output_tokens=int(usage.get("completion_tokens", 0) or 0),
    )


def _stream_line_text(raw_line: bytes | str) -> str:
    if isinstance(raw_line, bytes):
        return raw_line.decode("utf-8").strip()
    return str(raw_line).strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _urlopen_transport(request: Request, timeout_seconds: float) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _urlopen_stream_transport(request: Request, timeout_seconds: float) -> Iterable[bytes]:
    with urlopen(request, timeout=timeout_seconds) as response:
        yield from response
