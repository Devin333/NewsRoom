#!/usr/bin/env python3
"""Probe provider-side prompt/context caching through an OpenAI-compatible API.

The probe sends several requests with an identical long system-message prefix
and a different user-message suffix. It reports cache metadata returned by the
provider; it does not expose or download the model's raw KV tensors.

Required environment variables:
  OPENAI_BASE_URL  API base URL, for example https://example.com/v1
  OPENAI_MODEL     deployed model name
  OPENAI_API_KEY   API key

Exit codes:
  0  at least one response reported cached input tokens
  1  configuration, transport, or response error
  2  cache field was reported, but all requests were misses
  3  responses succeeded without any cache field (result is unknown)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
import secrets
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_REQUESTS = 3
DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_PREFIX_WORDS = 1600
DEFAULT_MAX_TOKENS = 8
DEFAULT_TIMEOUT_SECONDS = 90.0
MAX_REQUESTS = 100
MAX_PREFIX_WORDS = 100_000
MAX_MAX_TOKENS = 4096
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
ERROR_BODY_BYTES = 16 * 1024

# Providers use slightly different names for the same accounting value. The
# first entry is the OpenAI/DashScope Chat Completions shape.
_CACHE_TOKEN_PATHS: tuple[tuple[str, ...], ...] = (
    ("prompt_tokens_details", "cached_tokens"),
    ("input_tokens_details", "cached_tokens"),
    ("prompt_tokens_details", "cache_read_input_tokens"),
    ("input_tokens_details", "cache_read_input_tokens"),
    ("cache_read_input_tokens",),
    ("cached_tokens",),
    ("prompt_cache_hit_tokens",),
)


class ProbeConfigurationError(ValueError):
    """Raised when required environment variables or CLI values are invalid."""


class ProbeRequestError(RuntimeError):
    """Raised for a provider, network, or response-format failure."""


@dataclass(frozen=True)
class ProbeConfig:
    endpoint: str
    model: str
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ProbeConfig":
        values = os.environ if environ is None else environ
        missing: list[str] = []
        raw_base_url = str(values.get("OPENAI_BASE_URL", "")).strip()
        model = str(values.get("OPENAI_MODEL", "")).strip()
        api_key = str(values.get("OPENAI_API_KEY", "")).strip()
        if not raw_base_url:
            missing.append("OPENAI_BASE_URL")
        if not model:
            missing.append("OPENAI_MODEL")
        if not api_key:
            missing.append("OPENAI_API_KEY")
        if missing:
            raise ProbeConfigurationError(
                "Missing required environment variable(s): " + ", ".join(missing)
            )
        return cls(
            endpoint=normalize_chat_completions_url(raw_base_url),
            model=model,
            api_key=api_key,
        )


@dataclass(frozen=True)
class ProbeOptions:
    requests: int = DEFAULT_REQUESTS
    delay_seconds: float = DEFAULT_DELAY_SECONDS
    prefix_words: int = DEFAULT_PREFIX_WORDS
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.requests < 2:
            raise ProbeConfigurationError("--requests must be at least 2")
        if self.requests > MAX_REQUESTS:
            raise ProbeConfigurationError(f"--requests must not exceed {MAX_REQUESTS}")
        if not math.isfinite(self.delay_seconds) or self.delay_seconds < 0:
            raise ProbeConfigurationError("--delay-seconds must be non-negative")
        if self.prefix_words < 1:
            raise ProbeConfigurationError("--prefix-words must be positive")
        if self.prefix_words > MAX_PREFIX_WORDS:
            raise ProbeConfigurationError(
                f"--prefix-words must not exceed {MAX_PREFIX_WORDS}"
            )
        if self.max_tokens < 1:
            raise ProbeConfigurationError("--max-tokens must be positive")
        if self.max_tokens > MAX_MAX_TOKENS:
            raise ProbeConfigurationError(
                f"--max-tokens must not exceed {MAX_MAX_TOKENS}"
            )
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ProbeConfigurationError("--timeout-seconds must be positive")


@dataclass(frozen=True)
class TransportResponse:
    payload: Mapping[str, Any]
    status_code: int = 200


@dataclass(frozen=True)
class CacheObservation:
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    cache_field: str | None
    cache_conflict: bool = False

    @property
    def cache_field_reported(self) -> bool:
        return self.cache_field is not None


@dataclass(frozen=True)
class ProbeResult:
    observations: tuple[CacheObservation, ...]
    status: str
    exit_code: int


SendJson = Callable[
    [str, Mapping[str, Any], str, float], TransportResponse | Mapping[str, Any]
]
Emit = Callable[[str], None]


def normalize_chat_completions_url(base_url: str) -> str:
    """Return a safe Chat Completions URL without duplicating the endpoint."""

    if not isinstance(base_url, str):
        raise ProbeConfigurationError("OPENAI_BASE_URL must be a string")
    value = base_url.strip()
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise ProbeConfigurationError(f"Invalid OPENAI_BASE_URL: {exc}") from exc
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ProbeConfigurationError(
            "OPENAI_BASE_URL must be an absolute http(s) URL"
        )
    try:
        hostname = parts.hostname
        port = parts.port
        has_userinfo = parts.username is not None or parts.password is not None
    except ValueError as exc:
        raise ProbeConfigurationError(f"Invalid OPENAI_BASE_URL: {exc}") from exc
    if not hostname or (
        port is not None and not (0 < port <= 65535)
    ):
        raise ProbeConfigurationError(
            "OPENAI_BASE_URL must contain a valid host and port"
        )
    if has_userinfo:
        raise ProbeConfigurationError(
            "OPENAI_BASE_URL must not contain username or password"
        )
    if parts.query or parts.fragment:
        raise ProbeConfigurationError(
            "OPENAI_BASE_URL must not contain a query string or fragment"
        )

    path = parts.path.rstrip("/")
    if path.lower().endswith("/responses"):
        raise ProbeConfigurationError(
            "This probe uses Chat Completions; set OPENAI_BASE_URL to an API base "
            "URL, not a /responses endpoint"
        )
    if not path.lower().endswith("/chat/completions"):
        path = f"{path}/chat/completions" if path else "/chat/completions"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def build_stable_prefix(prefix_words: int) -> str:
    """Build a deterministic prefix without depending on a model tokenizer."""

    marker = (
        "Agora prompt cache probe. Keep this prefix unchanged across requests. "
    )
    return marker + " ".join("evidence" for _ in range(prefix_words))


def build_probe_payload(
    *,
    model: str,
    stable_prefix: str,
    session_id: str,
    request_index: int,
    max_tokens: int,
) -> dict[str, Any]:
    """Create a Chat Completions request with a controlled changing suffix."""

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": stable_prefix},
            {
                "role": "user",
                "content": (
                    f"Probe session {session_id}; request {request_index}. "
                    f"Reply with only CACHE_PROBE_{request_index}."
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }


def extract_cache_observation(payload: Mapping[str, Any]) -> CacheObservation:
    """Extract cache accounting while treating absent metadata as unknown."""

    usage = payload.get("usage")
    usage_map: Mapping[str, Any] = usage if isinstance(usage, Mapping) else {}
    input_tokens = _first_integer(usage_map, ("prompt_tokens", "input_tokens"))
    output_tokens = _first_integer(
        usage_map, ("completion_tokens", "output_tokens")
    )

    recognized: list[tuple[str, int]] = []
    for path in _CACHE_TOKEN_PATHS:
        value = _value_at_path(usage_map, path)
        parsed = _coerce_nonnegative_integer(value)
        if parsed is not None:
            recognized.append(("usage." + ".".join(path), parsed))
    cache_field = recognized[0][0] if recognized else None
    cached_tokens = recognized[0][1] if recognized else None
    cache_conflict = len({item[1] for item in recognized}) > 1
    return CacheObservation(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        cache_field=cache_field,
        cache_conflict=cache_conflict,
    )


def classify_observations(
    observations: Sequence[CacheObservation],
) -> tuple[str, int]:
    """Classify a run without treating an unreported field as a miss."""

    if not observations:
        return "no_observations", 1
    hits = [item for item in observations if (item.cached_tokens or 0) > 0]
    if hits:
        if len(observations) > 1 and any(
            (item.cached_tokens or 0) > 0 for item in observations[1:]
        ):
            return "hit", 0
        return "warm_hit_on_first_request", 0
    if any(item.cache_field_reported for item in observations):
        return "miss", 2
    return "not_reported", 3


def run_probe(
    config: ProbeConfig,
    options: ProbeOptions,
    *,
    sender: SendJson,
    sleeper: Callable[[float], None] = time.sleep,
    emit: Emit = print,
    session_id: str | None = None,
) -> ProbeResult:
    """Run the probe through an injectable sender for deterministic tests."""

    if session_id is None:
        session_id = secrets.token_hex(8)
    stable_prefix = build_stable_prefix(options.prefix_words)
    prefix_hash = hashlib.sha256(stable_prefix.encode("utf-8")).hexdigest()[:16]
    emit("[config]")
    emit(f"  endpoint:       {_redact_text(config.endpoint, config.api_key)}")
    emit(f"  model:          {_redact_text(config.model, config.api_key)}")
    emit(f"  requests:       {options.requests}")
    emit(f"  prefix_words:   {options.prefix_words}")
    emit(f"  prefix_sha256:  {prefix_hash}")
    if options.prefix_words < 1024:
        emit(
            "[warn] prefix_words is below 1024; the provider's cache threshold "
            "may not be met."
        )
    emit(
        "[info] The system prefix is identical; only the user suffix changes "
        "between requests."
    )

    observations: list[CacheObservation] = []
    short_prefix_warning_emitted = False
    for request_index in range(1, options.requests + 1):
        payload = build_probe_payload(
            model=config.model,
            stable_prefix=stable_prefix,
            session_id=session_id,
            request_index=request_index,
            max_tokens=options.max_tokens,
        )
        started = time.perf_counter()
        try:
            response = sender(
                config.endpoint,
                payload,
                config.api_key,
                options.timeout_seconds,
            )
            normalized = _normalize_transport_response(response, config.api_key)
        except ProbeRequestError as exc:
            raise ProbeRequestError(
                f"request {request_index}/{options.requests} failed: "
                f"{_redact_text(str(exc), config.api_key)}"
            ) from None
        except Exception as exc:
            raise ProbeRequestError(
                f"request {request_index}/{options.requests} failed "
                f"({type(exc).__name__})"
            ) from None
        observation = extract_cache_observation(normalized.payload)
        observations.append(observation)
        elapsed = time.perf_counter() - started
        emit(
            f"[request {request_index}/{options.requests}] "
            f"HTTP {normalized.status_code} in {elapsed:.2f}s; "
            f"input_tokens={_display_count(observation.input_tokens)}; "
            f"output_tokens={_display_count(observation.output_tokens)}; "
            f"cached_tokens={_display_count(observation.cached_tokens)}; "
            f"cache_field={observation.cache_field or 'not-reported'}"
            f"{'; conflict' if observation.cache_conflict else ''}"
        )
        if (
            not short_prefix_warning_emitted
            and observation.input_tokens is not None
            and observation.input_tokens < 1024
        ):
            emit(
                "[warn] Provider reported fewer than 1024 input tokens; the "
                "provider's cache threshold may not be met."
            )
            short_prefix_warning_emitted = True
        if request_index < options.requests and options.delay_seconds:
            sleeper(options.delay_seconds)

    status, exit_code = classify_observations(observations)
    emit("")
    if status == "hit":
        emit("[result] Provider prompt/context cache HIT on a repeated prefix.")
    elif status == "warm_hit_on_first_request":
        emit(
            "[result] Cache metadata was already positive on the first request; "
            "the prefix may have been warm before this probe."
        )
    elif status == "miss":
        emit(
            "[result] Cache field was reported, but no cache hit was observed "
            "in this run."
        )
    else:
        emit(
            "[result] The provider did not report a recognized cache field; "
            "support and hit status cannot be determined."
        )
    emit(f"RESULT={_result_label(status)}")
    emit(
        "[note] This tests provider-side prompt/context cache accounting only; "
        "raw model KV tensors are not exposed by this script."
    )
    return ProbeResult(tuple(observations), status, exit_code)


def post_json(
    endpoint: str,
    payload: Mapping[str, Any],
    api_key: str,
    timeout_seconds: float,
) -> TransportResponse:
    """POST JSON without logging request content or credentials."""

    request = Request(
        url=endpoint,
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AgoraHub-PromptCacheProbe/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            try:
                status_code = int(getattr(response, "status", 200) or 200)
            except (TypeError, ValueError):
                raise ProbeRequestError(
                    "Provider returned an invalid HTTP status"
                ) from None
    except HTTPError as exc:
        raise ProbeRequestError(
            f"HTTP {exc.code}: {_safe_provider_error(exc, api_key)}"
        ) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise ProbeRequestError(
            f"Network error ({type(exc).__name__}); check endpoint and connectivity"
        ) from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProbeRequestError("Provider response exceeded the 4 MiB safety limit")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeRequestError(
            f"Provider response was not valid JSON ({type(exc).__name__})"
        ) from None
    if not isinstance(decoded, Mapping):
        raise ProbeRequestError("Provider response JSON must be an object")
    if "error" in decoded:
        diagnostic = _safe_error_payload(decoded, api_key)
        raise ProbeRequestError(
            "Provider returned an error: "
            + (diagnostic or "no safe diagnostic")
        )
    if "usage" in decoded and not isinstance(decoded["usage"], Mapping):
        raise ProbeRequestError("Provider response usage must be an object")
    if "choices" in decoded and not isinstance(decoded["choices"], list):
        raise ProbeRequestError("Provider response choices must be an array")
    if "usage" not in decoded and "choices" not in decoded:
        raise ProbeRequestError("Provider response lacked usage or choices")
    return TransportResponse(decoded, status_code)


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    sender: SendJson | None = None,
) -> int:
    args = parse_args(argv)
    try:
        config = ProbeConfig.from_env(environ)
        options = ProbeOptions(
            requests=args.requests,
            delay_seconds=args.delay_seconds,
            prefix_words=args.prefix_words,
            max_tokens=args.max_tokens,
            timeout_seconds=args.timeout_seconds,
        )
        result = run_probe(
            config,
            options,
            sender=sender or post_json,
        )
        return result.exit_code
    except ProbeConfigurationError as exc:
        print(f"[fail] Configuration error: {exc}", file=sys.stderr)
        return 1
    except ProbeRequestError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe provider-side prompt/context cache via an "
            "OpenAI-compatible API."
        )
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=DEFAULT_REQUESTS,
        help=(
            f"Number of requests to send (default: {DEFAULT_REQUESTS}; "
            f"range: 2-{MAX_REQUESTS})."
        ),
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Delay between requests (default: {DEFAULT_DELAY_SECONDS}).",
    )
    parser.add_argument(
        "--prefix-words",
        type=int,
        default=DEFAULT_PREFIX_WORDS,
        help=(
            "Approximate repeated English words in the stable prefix "
            f"(default: {DEFAULT_PREFIX_WORDS})."
        ),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=(
            f"Maximum generated tokens per request (default: {DEFAULT_MAX_TOKENS}; "
            f"maximum: {MAX_MAX_TOKENS})."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-request timeout (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    return parser.parse_args(argv)


def _normalize_transport_response(
    response: TransportResponse | Mapping[str, Any],
    api_key: str = "",
) -> TransportResponse:
    if isinstance(response, TransportResponse):
        normalized = response
    elif isinstance(response, Mapping):
        normalized = TransportResponse(response)
    else:
        raise ProbeRequestError("Test transport returned an invalid response object")
    if not isinstance(normalized.payload, Mapping):
        raise ProbeRequestError("Provider response JSON must be an object")
    try:
        status_code = int(normalized.status_code)
    except (TypeError, ValueError):
        raise ProbeRequestError("Provider returned an invalid HTTP status") from None
    if not 200 <= status_code < 300:
        diagnostic = _safe_error_payload(normalized.payload, api_key)
        suffix = f": {diagnostic}" if diagnostic else ""
        raise ProbeRequestError(f"Provider returned HTTP {status_code}{suffix}")
    if "error" in normalized.payload:
        diagnostic = _safe_error_payload(normalized.payload, api_key)
        raise ProbeRequestError(
            "Provider returned an error: " + (diagnostic or "no safe diagnostic")
        )
    if "usage" in normalized.payload and not isinstance(
        normalized.payload["usage"], Mapping
    ):
        raise ProbeRequestError("Provider response usage must be an object")
    if "choices" in normalized.payload and not isinstance(
        normalized.payload["choices"], list
    ):
        raise ProbeRequestError("Provider response choices must be an array")
    if "usage" not in normalized.payload and "choices" not in normalized.payload:
        raise ProbeRequestError("Provider response lacked usage or choices")
    return TransportResponse(normalized.payload, status_code)


def _value_at_path(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _first_integer(value: Mapping[str, Any], keys: Sequence[str]) -> int | None:
    for key in keys:
        parsed = _coerce_nonnegative_integer(value.get(key))
        if parsed is not None:
            return parsed
    return None


def _coerce_nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = int(text, 10)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _display_count(value: int | None) -> str:
    return str(value) if value is not None else "not-reported"


def _result_label(status: str) -> str:
    return {
        "hit": "HIT",
        "warm_hit_on_first_request": "WARM_HIT",
        "miss": "MISS",
        "not_reported": "UNREPORTED",
        "no_observations": "ERROR",
    }.get(status, "ERROR")


def _safe_provider_error(exc: HTTPError, api_key: str) -> str:
    """Keep HTTP diagnostics useful while excluding arbitrary provider bodies."""

    try:
        raw = exc.read(ERROR_BODY_BYTES)
    except Exception:
        return "provider returned an HTTP error"
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return "provider returned a non-JSON error body"

    summary = _safe_error_payload(decoded, api_key)
    return summary or "provider returned an HTTP error without a safe diagnostic"


def _safe_error_payload(payload: Any, api_key: str) -> str:
    candidates: list[str] = []
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            for key in ("code", "type", "message"):
                value = error.get(key)
                if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                    candidates.append(str(value))
        for key in ("code", "type", "message"):
            value = payload.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                candidates.append(str(value))
    if not candidates:
        return ""
    summary = "; ".join(dict.fromkeys(candidates))
    if api_key:
        summary = _redact_text(summary, api_key)
    return " ".join(summary.split())[:500]


def _redact_text(value: str, api_key: str) -> str:
    return value.replace(api_key, "[redacted]") if api_key else value


if __name__ == "__main__":
    raise SystemExit(main())
