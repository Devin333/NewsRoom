from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.framework.llm.models import LLMRequest, LLMResponse, TokenUsage


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


Transport = Callable[[Request, float], bytes]
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
        retry_policy: LLMRetryPolicy | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or _urlopen_transport
        self._retry_policy = retry_policy or LLMRetryPolicy()
        self._sleep = sleep or time.sleep

    def complete(self, request: LLMRequest) -> LLMResponse:
        api_key = self.config.resolve_api_key()
        payload = {
            "model": self.config.model,
            "messages": request.messages,
        }
        if request.tools:
            payload["tools"] = request.tools

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
                return self._normalize_response(response_payload, attempts=attempt)

            if not error.retryable or attempt >= self._retry_policy.max_attempts:
                raise error

            self._sleep(self._retry_policy.delay_after_attempt(attempt))

        raise LLMProviderError(
            f"{self.config.provider} request failed before sending",
            provider=self.config.provider,
            attempts=self._retry_policy.max_attempts,
        )

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

    def _normalize_response(self, payload: dict[str, Any], *, attempts: int) -> LLMResponse:
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
        content = message.get("content")
        if not isinstance(content, str):
            raise LLMProviderError(
                f"{self.config.provider} response missing message content",
                provider=self.config.provider,
                error_type="provider_response_shape_invalid",
                retryable=False,
                attempts=attempts,
            )

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
        )

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


def _urlopen_transport(request: Request, timeout_seconds: float) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()
