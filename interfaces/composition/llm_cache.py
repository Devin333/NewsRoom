from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from framework.llm.cache import (
    CacheMode,
    InMemoryLLMCache,
    LLMCacheKeyFactory,
    LLMCachePolicy,
    LLMCacheRuntime,
)
from framework.llm.routing import LLMRouter, ModelDeployment, ModelRoute
from infrastructure.storage.redis_llm_cache import (
    LLMCacheEnvelopeCodec,
    RedisLLMCache,
    decode_llm_cache_encryption_key,
    validate_llm_cache_namespace,
)


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_TASK_POLICY_KEYS = {"enabled", "required_dependencies", "require_temperature_zero"}
_ALLOWED_BACKENDS = {"memory", "redis"}
_LOCAL_ENVIRONMENTS = {"development", "local", "test"}


class LLMCacheConfigurationError(ValueError):
    def __init__(self, field_name: str, reason: str) -> None:
        self.field_name = field_name
        self.reason = reason
        super().__init__(f"invalid LLM cache configuration: {field_name} ({reason})")


@dataclass(frozen=True)
class LLMCacheSettings:
    mode: CacheMode = CacheMode.DISABLED
    backend: str = "redis"
    namespace: str = "newsroom:llm-cache"
    key_version: str = "v2"
    cache_generation: str = "v2"
    ttl_seconds: float = 300.0
    max_entry_bytes: int = 1_048_576
    connect_timeout_seconds: float = 1.0
    socket_timeout_seconds: float = 1.0
    singleflight_enabled: bool = True
    lock_ttl_seconds: float = 120.0
    wait_timeout_ms: int = 2_500
    poll_interval_ms: int = 50
    provider_timeout_seconds: float = 90.0
    lock_safety_margin_seconds: float = 15.0
    replay_chunk_size: int = 1_024
    cacheable_task_types: tuple[str, ...] = ()
    no_cache_agent_ids: tuple[str, ...] = ()
    required_dependencies: tuple[str, ...] = ()
    task_required_dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict,
        repr=False,
    )
    allow_deterministic_seed: bool = False
    environment: str = "production"
    local_test_mode: bool = False
    redis_url: str | None = field(default=None, repr=False)
    key_secret: str | None = field(default=None, repr=False)
    encryption_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "task_required_dependencies",
            MappingProxyType(
                {
                    str(task_type): tuple(dependencies)
                    for task_type, dependencies in self.task_required_dependencies.items()
                }
            ),
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LLMCacheSettings:
        values = os.environ if env is None else env
        mode = _cache_mode(values.get("NEWS_LLM_CACHE_MODE", CacheMode.DISABLED.value))
        backend = _choice(
            values.get("NEWS_LLM_CACHE_BACKEND", "redis"),
            field_name="NEWS_LLM_CACHE_BACKEND",
            choices=_ALLOWED_BACKENDS,
        )
        if mode is CacheMode.DISABLED:
            return cls(mode=mode, backend=backend)

        environment = _choice(
            values.get("NEWS_LLM_CACHE_ENVIRONMENT", "production"),
            field_name="NEWS_LLM_CACHE_ENVIRONMENT",
            choices={"production", *_LOCAL_ENVIRONMENTS},
        )
        local_test_mode = _bool_env(
            values,
            "NEWS_LLM_CACHE_LOCAL_TEST_MODE",
            default=False,
        )
        if local_test_mode and environment not in _LOCAL_ENVIRONMENTS:
            _invalid("NEWS_LLM_CACHE_LOCAL_TEST_MODE", "requires a local/test environment")
        if backend == "memory" and not local_test_mode:
            _invalid("NEWS_LLM_CACHE_BACKEND", "memory is limited to explicit local/test mode")

        namespace = _validated_namespace(values.get("NEWS_LLM_CACHE_NAMESPACE"))
        key_version = _identifier_env(values, "NEWS_LLM_CACHE_KEY_VERSION", "v2")
        cache_generation = _identifier_env(values, "NEWS_LLM_CACHE_GENERATION", "v2")
        ttl_seconds = _number_env(
            values,
            "NEWS_LLM_CACHE_TTL_SECONDS",
            300.0,
            minimum=1.0,
            maximum=86_400.0,
        )
        max_entry_bytes = _int_env(
            values,
            "NEWS_LLM_CACHE_MAX_ENTRY_BYTES",
            1_048_576,
            minimum=1_024,
            maximum=16 * 1024 * 1024,
        )
        connect_timeout_seconds = _number_env(
            values,
            "NEWS_LLM_CACHE_CONNECT_TIMEOUT_SECONDS",
            1.0,
            minimum=0.05,
            maximum=10.0,
        )
        socket_timeout_seconds = _number_env(
            values,
            "NEWS_LLM_CACHE_SOCKET_TIMEOUT_SECONDS",
            1.0,
            minimum=0.05,
            maximum=30.0,
        )
        singleflight_enabled = _bool_env(
            values,
            "NEWS_LLM_CACHE_SINGLEFLIGHT_ENABLED",
            default=True,
        )
        lock_ttl_seconds = _number_env(
            values,
            "NEWS_LLM_CACHE_LOCK_TTL_SECONDS",
            120.0,
            minimum=1.0,
            maximum=600.0,
        )
        wait_timeout_ms = _int_env(
            values,
            "NEWS_LLM_CACHE_WAIT_TIMEOUT_MS",
            2_500,
            minimum=1,
            maximum=30_000,
        )
        poll_interval_ms = _int_env(
            values,
            "NEWS_LLM_CACHE_POLL_INTERVAL_MS",
            50,
            minimum=1,
            maximum=5_000,
        )
        provider_timeout_seconds = _number_env(
            values,
            "NEWS_LLM_CACHE_PROVIDER_TIMEOUT_SECONDS",
            90.0,
            minimum=0.1,
            maximum=540.0,
        )
        lock_safety_margin_seconds = _number_env(
            values,
            "NEWS_LLM_CACHE_LOCK_SAFETY_MARGIN_SECONDS",
            15.0,
            minimum=0.1,
            maximum=120.0,
        )
        replay_chunk_size = _int_env(
            values,
            "NEWS_LLM_CACHE_REPLAY_CHUNK_SIZE",
            1_024,
            minimum=1,
            maximum=65_536,
        )
        if poll_interval_ms > wait_timeout_ms:
            _invalid("NEWS_LLM_CACHE_POLL_INTERVAL_MS", "must not exceed wait timeout")
        if wait_timeout_ms >= lock_ttl_seconds * 1_000:
            _invalid("NEWS_LLM_CACHE_WAIT_TIMEOUT_MS", "must be shorter than lock TTL")
        if lock_ttl_seconds <= provider_timeout_seconds + lock_safety_margin_seconds:
            _invalid(
                "NEWS_LLM_CACHE_LOCK_TTL_SECONDS",
                "must exceed provider timeout plus safety margin",
            )

        cacheable_task_types, task_dependencies = _task_policies(values)
        required_dependencies = _csv_names(
            values.get("NEWS_LLM_CACHE_REQUIRED_DEPENDENCIES", ""),
            field_name="NEWS_LLM_CACHE_REQUIRED_DEPENDENCIES",
        )
        no_cache_agent_ids = _csv_names(
            values.get("NEWS_LLM_CACHE_NO_CACHE_AGENT_IDS", ""),
            field_name="NEWS_LLM_CACHE_NO_CACHE_AGENT_IDS",
        )
        allow_deterministic_seed = _bool_env(
            values,
            "NEWS_LLM_CACHE_ALLOW_DETERMINISTIC_SEED",
            default=False,
        )

        key_secret = _required_secret(values, "NEWS_LLM_CACHE_KEY_SECRET", minimum_bytes=16)
        redis_url: str | None = None
        encryption_key: str | None = None
        if backend == "redis":
            redis_url = _redis_url(
                values.get("NEWS_LLM_CACHE_REDIS_URL"),
                environment=environment,
                local_test_mode=local_test_mode,
            )
            encryption_key = _required_secret(
                values,
                "NEWS_LLM_CACHE_ENCRYPTION_KEY",
                minimum_bytes=32,
            )
            try:
                decode_llm_cache_encryption_key(encryption_key)
            except ValueError:
                _invalid(
                    "NEWS_LLM_CACHE_ENCRYPTION_KEY",
                    "must be URL-safe base64 encoding exactly 32 bytes",
                )
            if encryption_key == key_secret:
                _invalid(
                    "NEWS_LLM_CACHE_ENCRYPTION_KEY",
                    "must be distinct from the key HMAC secret",
                )

        return cls(
            mode=mode,
            backend=backend,
            namespace=namespace,
            key_version=key_version,
            cache_generation=cache_generation,
            ttl_seconds=ttl_seconds,
            max_entry_bytes=max_entry_bytes,
            connect_timeout_seconds=connect_timeout_seconds,
            socket_timeout_seconds=socket_timeout_seconds,
            singleflight_enabled=singleflight_enabled,
            lock_ttl_seconds=lock_ttl_seconds,
            wait_timeout_ms=wait_timeout_ms,
            poll_interval_ms=poll_interval_ms,
            provider_timeout_seconds=provider_timeout_seconds,
            lock_safety_margin_seconds=lock_safety_margin_seconds,
            replay_chunk_size=replay_chunk_size,
            cacheable_task_types=cacheable_task_types,
            no_cache_agent_ids=no_cache_agent_ids,
            required_dependencies=required_dependencies,
            task_required_dependencies=task_dependencies,
            allow_deterministic_seed=allow_deterministic_seed,
            environment=environment,
            local_test_mode=local_test_mode,
            redis_url=redis_url,
            key_secret=key_secret,
            encryption_key=encryption_key,
        )


def build_llm_cache_runtime(
    settings: LLMCacheSettings,
    *,
    redis_client: Any | None = None,
) -> LLMCacheRuntime | None:
    if not isinstance(settings, LLMCacheSettings):
        raise TypeError("settings must be LLMCacheSettings")
    _validate_settings_instance(settings)
    if settings.mode is CacheMode.DISABLED:
        return None
    if settings.key_secret is None:
        _invalid("NEWS_LLM_CACHE_KEY_SECRET", "is required")

    policy = LLMCachePolicy(
        mode=settings.mode,
        ttl_seconds=settings.ttl_seconds,
        max_entry_bytes=settings.max_entry_bytes,
        cacheable_task_types=settings.cacheable_task_types,
        no_cache_agent_ids=settings.no_cache_agent_ids,
        required_dependencies=settings.required_dependencies,
        task_required_dependencies=settings.task_required_dependencies,
        allow_deterministic_seed=settings.allow_deterministic_seed,
    )
    key_factory = LLMCacheKeyFactory(
        secret=settings.key_secret,
        namespace=settings.namespace,
        key_version=settings.key_version,
        cache_generation=settings.cache_generation,
    )

    if settings.backend == "memory":
        if not settings.local_test_mode:
            _invalid("NEWS_LLM_CACHE_BACKEND", "memory is limited to local/test mode")
        store: Any = InMemoryLLMCache(
            max_entries=1_024,
            max_bytes=64 * 1024 * 1024,
            default_ttl_seconds=settings.ttl_seconds,
        )
    elif settings.backend == "redis":
        if settings.redis_url is None or settings.encryption_key is None:
            _invalid("NEWS_LLM_CACHE_REDIS_URL", "Redis settings are incomplete")
        client = redis_client or _redis_client(settings)
        codec = LLMCacheEnvelopeCodec(
            namespace=settings.namespace,
            encryption_key=settings.encryption_key,
        )
        store = RedisLLMCache(
            client,
            namespace=settings.namespace,
            codec=codec,
            max_entry_bytes=settings.max_entry_bytes,
            max_ttl_seconds=settings.ttl_seconds,
            max_lease_ttl_seconds=settings.lock_ttl_seconds,
        )
    else:
        _invalid("NEWS_LLM_CACHE_BACKEND", "unsupported backend")

    return LLMCacheRuntime(
        policy=policy,
        key_factory=key_factory,
        store=store,
        coordinator=store,
        singleflight_enabled=settings.singleflight_enabled,
        singleflight_lock_ttl_seconds=settings.lock_ttl_seconds,
        singleflight_wait_timeout_ms=settings.wait_timeout_ms,
        singleflight_poll_interval_ms=settings.poll_interval_ms,
        replay_chunk_size=settings.replay_chunk_size,
    )


def build_llm_cache_runtime_from_env(
    env: Mapping[str, str] | None = None,
    *,
    redis_client: Any | None = None,
) -> LLMCacheRuntime | None:
    return build_llm_cache_runtime(
        LLMCacheSettings.from_env(env),
        redis_client=redis_client,
    )


def build_cache_aware_llm_router(
    *,
    routes: Iterable[ModelRoute],
    deployments: Iterable[ModelDeployment],
    settings: LLMCacheSettings | None = None,
    env: Mapping[str, str] | None = None,
    redis_client: Any | None = None,
    cache_runtime: LLMCacheRuntime | None = None,
    **router_options: Any,
) -> LLMRouter:
    if cache_runtime is not None and (settings is not None or env is not None):
        raise ValueError("cache_runtime cannot be combined with cache settings or env")
    runtime = cache_runtime
    if runtime is None:
        runtime = build_llm_cache_runtime(
            settings or LLMCacheSettings.from_env(env),
            redis_client=redis_client,
        )
    return LLMRouter(
        routes=routes,
        deployments=deployments,
        cache_runtime=runtime,
        **router_options,
    )


def _redis_client(settings: LLMCacheSettings) -> Any:
    try:
        import redis
    except ImportError:
        _invalid("redis", "install the newsroom redis optional dependency")
    try:
        return redis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=settings.connect_timeout_seconds,
            socket_timeout=settings.socket_timeout_seconds,
            retry_on_timeout=False,
        )
    except Exception:
        _invalid("NEWS_LLM_CACHE_REDIS_URL", "Redis client construction failed")


def _validate_settings_instance(settings: LLMCacheSettings) -> None:
    if not isinstance(settings.mode, CacheMode):
        _invalid("mode", "must be CacheMode")
    if settings.backend not in _ALLOWED_BACKENDS:
        _invalid("backend", "unsupported backend")
    if settings.mode is CacheMode.DISABLED:
        return
    _validated_namespace(settings.namespace)
    for field_name, value in (
        ("key_version", settings.key_version),
        ("cache_generation", settings.cache_generation),
    ):
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            _invalid(field_name, "must be a bounded identifier")
    _validate_number(
        settings.ttl_seconds,
        field_name="ttl_seconds",
        minimum=1.0,
        maximum=86_400.0,
    )
    _validate_integer(
        settings.max_entry_bytes,
        field_name="max_entry_bytes",
        minimum=1_024,
        maximum=16 * 1024 * 1024,
    )
    _validate_number(
        settings.connect_timeout_seconds,
        field_name="connect_timeout_seconds",
        minimum=0.05,
        maximum=10.0,
    )
    _validate_number(
        settings.socket_timeout_seconds,
        field_name="socket_timeout_seconds",
        minimum=0.05,
        maximum=30.0,
    )
    _validate_number(
        settings.lock_ttl_seconds,
        field_name="lock_ttl_seconds",
        minimum=1.0,
        maximum=600.0,
    )
    _validate_integer(
        settings.wait_timeout_ms,
        field_name="wait_timeout_ms",
        minimum=1,
        maximum=30_000,
    )
    _validate_integer(
        settings.poll_interval_ms,
        field_name="poll_interval_ms",
        minimum=1,
        maximum=5_000,
    )
    _validate_number(
        settings.provider_timeout_seconds,
        field_name="provider_timeout_seconds",
        minimum=0.1,
        maximum=540.0,
    )
    _validate_number(
        settings.lock_safety_margin_seconds,
        field_name="lock_safety_margin_seconds",
        minimum=0.1,
        maximum=120.0,
    )
    _validate_integer(
        settings.replay_chunk_size,
        field_name="replay_chunk_size",
        minimum=1,
        maximum=65_536,
    )
    if settings.poll_interval_ms > settings.wait_timeout_ms:
        _invalid("poll_interval_ms", "must not exceed wait timeout")
    if settings.wait_timeout_ms >= settings.lock_ttl_seconds * 1_000:
        _invalid("wait_timeout_ms", "must be shorter than lock TTL")
    if (
        settings.lock_ttl_seconds
        <= settings.provider_timeout_seconds + settings.lock_safety_margin_seconds
    ):
        _invalid("lock_ttl_seconds", "must exceed provider timeout plus safety margin")
    if not isinstance(settings.key_secret, str) or len(settings.key_secret.encode("utf-8")) < 16:
        _invalid("key_secret", "must contain at least 16 bytes")
    if settings.backend == "memory":
        if not settings.local_test_mode or settings.environment not in _LOCAL_ENVIRONMENTS:
            _invalid("backend", "memory is limited to local/test mode")
        return
    if settings.encryption_key is None:
        _invalid("encryption_key", "is required")
    try:
        decode_llm_cache_encryption_key(settings.encryption_key)
    except ValueError:
        _invalid("encryption_key", "must decode to exactly 32 bytes")
    if settings.encryption_key == settings.key_secret:
        _invalid("encryption_key", "must be distinct from the key HMAC secret")
    _redis_url(
        settings.redis_url,
        environment=settings.environment,
        local_test_mode=settings.local_test_mode,
    )


def _validate_number(
    value: Any,
    *,
    field_name: str,
    minimum: float,
    maximum: float,
) -> None:
    if isinstance(value, bool):
        _invalid(field_name, "must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        _invalid(field_name, "must be numeric")
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        _invalid(field_name, f"must be between {minimum} and {maximum}")


def _validate_integer(
    value: Any,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _invalid(field_name, f"must be an integer between {minimum} and {maximum}")


def _cache_mode(value: Any) -> CacheMode:
    try:
        return CacheMode(str(value).strip().lower())
    except ValueError:
        _invalid("NEWS_LLM_CACHE_MODE", "unsupported mode")


def _choice(value: Any, *, field_name: str, choices: set[str]) -> str:
    normalized = str(value).strip().lower()
    if normalized not in choices:
        _invalid(field_name, "unsupported value")
    return normalized


def _validated_namespace(value: Any) -> str:
    text = "newsroom:llm-cache" if value is None else str(value)
    try:
        return validate_llm_cache_namespace(text)
    except ValueError:
        _invalid("NEWS_LLM_CACHE_NAMESPACE", "invalid or reserved namespace")


def _identifier_env(values: Mapping[str, str], name: str, default: str) -> str:
    value = str(values.get(name, default)).strip()
    if _IDENTIFIER.fullmatch(value) is None:
        _invalid(name, "must be a bounded identifier")
    return value


def _bool_env(values: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = values.get(name)
    if raw is None or not str(raw).strip():
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    _invalid(name, "must be a boolean")


def _number_env(
    values: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = values.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        parsed = float(str(raw).strip())
    except ValueError:
        _invalid(name, "must be numeric")
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        _invalid(name, f"must be between {minimum} and {maximum}")
    return parsed


def _int_env(
    values: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = values.get(name)
    if raw is None or not str(raw).strip():
        return default
    text = str(raw).strip()
    if re.fullmatch(r"[0-9]+", text) is None:
        _invalid(name, "must be an integer")
    parsed = int(text)
    if not minimum <= parsed <= maximum:
        _invalid(name, f"must be between {minimum} and {maximum}")
    return parsed


def _csv_names(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None or not str(value).strip():
        return ()
    if len(str(value)) > 4_096:
        _invalid(field_name, "is too large")
    names: list[str] = []
    for item in str(value).split(","):
        name = item.strip()
        if _IDENTIFIER.fullmatch(name) is None:
            _invalid(field_name, "must contain bounded identifiers")
        names.append(name)
    return tuple(dict.fromkeys(names))


def _task_policies(
    values: Mapping[str, str],
) -> tuple[tuple[str, ...], Mapping[str, tuple[str, ...]]]:
    raw_json = values.get("NEWS_LLM_CACHE_TASK_POLICIES_JSON")
    raw_tasks = values.get("NEWS_LLM_CACHE_CACHEABLE_TASK_TYPES", "")
    if raw_json is None or not str(raw_json).strip():
        return (
            _csv_names(raw_tasks, field_name="NEWS_LLM_CACHE_CACHEABLE_TASK_TYPES"),
            {},
        )
    if str(raw_tasks).strip():
        _invalid(
            "NEWS_LLM_CACHE_TASK_POLICIES_JSON",
            "cannot be combined with CACHEABLE_TASK_TYPES",
        )
    if len(str(raw_json)) > 65_536:
        _invalid("NEWS_LLM_CACHE_TASK_POLICIES_JSON", "is too large")
    try:
        payload = json.loads(str(raw_json))
    except json.JSONDecodeError:
        _invalid("NEWS_LLM_CACHE_TASK_POLICIES_JSON", "must be valid JSON")
    if not isinstance(payload, dict):
        _invalid("NEWS_LLM_CACHE_TASK_POLICIES_JSON", "must be an object")
    if len(payload) > 256:
        _invalid("NEWS_LLM_CACHE_TASK_POLICIES_JSON", "contains too many task policies")
    enabled_tasks: list[str] = []
    dependencies_by_task: dict[str, tuple[str, ...]] = {}
    for task_type, policy in payload.items():
        if _IDENTIFIER.fullmatch(str(task_type)) is None or not isinstance(policy, dict):
            _invalid("NEWS_LLM_CACHE_TASK_POLICIES_JSON", "contains an invalid task policy")
        unknown = set(policy) - _TASK_POLICY_KEYS
        if unknown:
            _invalid("NEWS_LLM_CACHE_TASK_POLICIES_JSON", "contains unsupported policy fields")
        enabled = policy.get("enabled", True)
        if not isinstance(enabled, bool):
            _invalid("NEWS_LLM_CACHE_TASK_POLICIES_JSON", "enabled must be boolean")
        require_zero = policy.get("require_temperature_zero", True)
        if require_zero is not True:
            _invalid(
                "NEWS_LLM_CACHE_TASK_POLICIES_JSON",
                "require_temperature_zero must remain enabled",
            )
        raw_dependencies = policy.get("required_dependencies", [])
        if not isinstance(raw_dependencies, list) or any(
            not isinstance(item, str) for item in raw_dependencies
        ):
            _invalid(
                "NEWS_LLM_CACHE_TASK_POLICIES_JSON",
                "required_dependencies must be a string list",
            )
        if len(raw_dependencies) > 64:
            _invalid(
                "NEWS_LLM_CACHE_TASK_POLICIES_JSON",
                "contains too many required dependencies",
            )
        dependencies = _csv_names(
            ",".join(raw_dependencies),
            field_name="NEWS_LLM_CACHE_TASK_POLICIES_JSON",
        )
        if enabled:
            enabled_tasks.append(str(task_type))
            dependencies_by_task[str(task_type)] = dependencies
    return tuple(enabled_tasks), dependencies_by_task


def _required_secret(
    values: Mapping[str, str],
    name: str,
    *,
    minimum_bytes: int,
) -> str:
    raw = values.get(name)
    if not isinstance(raw, str) or not raw.strip():
        _invalid(name, "is required")
    if len(raw.encode("utf-8")) < minimum_bytes or len(raw) > 4_096:
        _invalid(name, f"must contain at least {minimum_bytes} bytes")
    return raw


def _redis_url(
    value: Any,
    *,
    environment: str,
    local_test_mode: bool,
) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid("NEWS_LLM_CACHE_REDIS_URL", "is required")
    url = value.strip()
    if len(url) > 2_048 or any(character.isspace() for character in url):
        _invalid("NEWS_LLM_CACHE_REDIS_URL", "is malformed")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError:
        _invalid("NEWS_LLM_CACHE_REDIS_URL", "is malformed")
    if not parsed.hostname or parsed.fragment or parsed.query:
        _invalid("NEWS_LLM_CACHE_REDIS_URL", "is malformed")
    if parsed.scheme == "redis":
        local_host = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if not (local_test_mode and environment in _LOCAL_ENVIRONMENTS and local_host):
            _invalid("NEWS_LLM_CACHE_REDIS_URL", "TLS is required outside local/test mode")
    elif parsed.scheme == "rediss":
        if environment == "production" and (
            not parsed.username or not parsed.password or parsed.username == "default"
        ):
            _invalid(
                "NEWS_LLM_CACHE_REDIS_URL",
                "production requires a dedicated ACL username and password",
            )
    else:
        _invalid("NEWS_LLM_CACHE_REDIS_URL", "must use redis:// or rediss://")
    return url


def _invalid(field_name: str, reason: str) -> Any:
    raise LLMCacheConfigurationError(field_name, reason) from None


__all__ = [
    "LLMCacheConfigurationError",
    "LLMCacheSettings",
    "build_cache_aware_llm_router",
    "build_llm_cache_runtime",
    "build_llm_cache_runtime_from_env",
]
