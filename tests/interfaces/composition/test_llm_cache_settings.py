from __future__ import annotations

import base64
import json

import pytest

from framework.llm.cache import CacheMode
from framework.llm.clients import FakeLLMClient
from framework.llm.context import ModelContextProfile
from framework.llm.models import LLMRequest
from framework.llm.routing import ModelDeployment, ModelRoute
from infrastructure.storage.redis_llm_cache import RedisLLMCache
from interfaces.composition.llm_cache import (
    LLMCacheConfigurationError,
    LLMCacheSettings,
    build_cache_aware_llm_router,
    build_llm_cache_runtime,
)


_ENCRYPTION_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


class TrackingEnv(dict[str, str]):
    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.read_names: list[str] = []

    def get(self, key: str, default=None):  # type: ignore[no-untyped-def]
        self.read_names.append(key)
        return super().get(key, default)


class NoIOFakeRedis:
    def __getattr__(self, name: str):
        raise AssertionError(f"observe/disabled composition performed Redis I/O: {name}")


def _enabled_env(**overrides: str) -> dict[str, str]:
    values = {
        "NEWS_LLM_CACHE_MODE": "read_write",
        "NEWS_LLM_CACHE_BACKEND": "redis",
        "NEWS_LLM_CACHE_ENVIRONMENT": "test",
        "NEWS_LLM_CACHE_LOCAL_TEST_MODE": "true",
        "NEWS_LLM_CACHE_REDIS_URL": "redis://127.0.0.1:6379/15",
        "NEWS_LLM_CACHE_KEY_SECRET": "hmac-secret-with-independent-material",
        "NEWS_LLM_CACHE_ENCRYPTION_KEY": _ENCRYPTION_KEY,
        "NEWS_LLM_CACHE_CACHEABLE_TASK_TYPES": "classify,summarize",
        "NEWS_LLM_CACHE_REQUIRED_DEPENDENCIES": "prompt_revision",
    }
    values.update(overrides)
    return values


def test_disabled_mode_does_not_read_secrets_or_build_a_backend() -> None:
    env = TrackingEnv(
        {
            "NEWS_LLM_CACHE_MODE": "disabled",
            "NEWS_LLM_CACHE_BACKEND": "redis",
        }
    )

    settings = LLMCacheSettings.from_env(env)
    runtime = build_llm_cache_runtime(settings, redis_client=NoIOFakeRedis())

    assert runtime is None
    assert "NEWS_LLM_CACHE_REDIS_URL" not in env.read_names
    assert "NEWS_LLM_CACHE_KEY_SECRET" not in env.read_names
    assert "NEWS_LLM_CACHE_ENCRYPTION_KEY" not in env.read_names


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NEWS_LLM_CACHE_MODE", "automatic"),
        ("NEWS_LLM_CACHE_BACKEND", "runtime-store"),
    ],
)
def test_unknown_mode_or_backend_is_rejected(name: str, value: str) -> None:
    env = _enabled_env(**{name: value})
    with pytest.raises(LLMCacheConfigurationError, match=name):
        LLMCacheSettings.from_env(env)


@pytest.mark.parametrize(
    "missing_name",
    [
        "NEWS_LLM_CACHE_REDIS_URL",
        "NEWS_LLM_CACHE_KEY_SECRET",
        "NEWS_LLM_CACHE_ENCRYPTION_KEY",
    ],
)
def test_non_disabled_redis_requires_dedicated_url_and_secrets(missing_name: str) -> None:
    env = _enabled_env()
    env.pop(missing_name)

    with pytest.raises(LLMCacheConfigurationError, match=missing_name):
        LLMCacheSettings.from_env(env)


@pytest.mark.parametrize(
    ("overrides", "field_name"),
    [
        (
            {
                "NEWS_LLM_CACHE_ENVIRONMENT": "production",
                "NEWS_LLM_CACHE_LOCAL_TEST_MODE": "false",
                "NEWS_LLM_CACHE_REDIS_URL": "redis://cache-user:password@example.com:6379/0",
            },
            "NEWS_LLM_CACHE_REDIS_URL",
        ),
        (
            {
                "NEWS_LLM_CACHE_ENVIRONMENT": "production",
                "NEWS_LLM_CACHE_LOCAL_TEST_MODE": "false",
                "NEWS_LLM_CACHE_REDIS_URL": "rediss://example.com:6379/0",
            },
            "NEWS_LLM_CACHE_REDIS_URL",
        ),
        (
            {
                "NEWS_LLM_CACHE_ENVIRONMENT": "production",
                "NEWS_LLM_CACHE_LOCAL_TEST_MODE": "false",
                "NEWS_LLM_CACHE_REDIS_URL": "rediss://default:password@example.com:6379/0",
            },
            "NEWS_LLM_CACHE_REDIS_URL",
        ),
        (
            {"NEWS_LLM_CACHE_REDIS_URL": "redis://cache.example.com:6379/0"},
            "NEWS_LLM_CACHE_REDIS_URL",
        ),
        (
            {"NEWS_LLM_CACHE_NAMESPACE": "news:runtime:llm-cache"},
            "NEWS_LLM_CACHE_NAMESPACE",
        ),
    ],
)
def test_transport_acl_and_namespace_boundaries_fail_fast(
    overrides: dict[str, str],
    field_name: str,
) -> None:
    with pytest.raises(LLMCacheConfigurationError, match=field_name):
        LLMCacheSettings.from_env(_enabled_env(**overrides))


def test_production_rediss_requires_and_accepts_a_dedicated_acl_identity() -> None:
    url = "rediss://cache-user:cache-password@cache.example.com:6380/0"
    settings = LLMCacheSettings.from_env(
        _enabled_env(
            NEWS_LLM_CACHE_ENVIRONMENT="production",
            NEWS_LLM_CACHE_LOCAL_TEST_MODE="false",
            NEWS_LLM_CACHE_REDIS_URL=url,
        )
    )

    assert settings.redis_url == url
    assert "cache-password" not in repr(settings)
    assert settings.key_secret not in repr(settings)
    assert settings.encryption_key not in repr(settings)


@pytest.mark.parametrize(
    ("overrides", "field_name"),
    [
        ({"NEWS_LLM_CACHE_TTL_SECONDS": "0"}, "NEWS_LLM_CACHE_TTL_SECONDS"),
        ({"NEWS_LLM_CACHE_MAX_ENTRY_BYTES": "999"}, "NEWS_LLM_CACHE_MAX_ENTRY_BYTES"),
        (
            {"NEWS_LLM_CACHE_POLL_INTERVAL_MS": "3000", "NEWS_LLM_CACHE_WAIT_TIMEOUT_MS": "2500"},
            "NEWS_LLM_CACHE_POLL_INTERVAL_MS",
        ),
        (
            {"NEWS_LLM_CACHE_LOCK_TTL_SECONDS": "100"},
            "NEWS_LLM_CACHE_LOCK_TTL_SECONDS",
        ),
        (
            {"NEWS_LLM_CACHE_SOCKET_TIMEOUT_SECONDS": "nan"},
            "NEWS_LLM_CACHE_SOCKET_TIMEOUT_SECONDS",
        ),
    ],
)
def test_numeric_and_lease_relationships_are_bounded(
    overrides: dict[str, str],
    field_name: str,
) -> None:
    with pytest.raises(LLMCacheConfigurationError, match=field_name):
        LLMCacheSettings.from_env(_enabled_env(**overrides))


def test_task_policy_json_is_strict_and_preserves_per_task_dependencies() -> None:
    policies = {
        "classify": {
            "enabled": True,
            "require_temperature_zero": True,
            "required_dependencies": ["prompt_revision", "source_version"],
        },
        "live_research": {"enabled": False},
        "summarize": {"enabled": True, "required_dependencies": ["prompt_revision"]},
    }
    settings = LLMCacheSettings.from_env(
        _enabled_env(
            NEWS_LLM_CACHE_CACHEABLE_TASK_TYPES="",
            NEWS_LLM_CACHE_REQUIRED_DEPENDENCIES="",
            NEWS_LLM_CACHE_TASK_POLICIES_JSON=json.dumps(policies),
        )
    )
    runtime = build_llm_cache_runtime(settings, redis_client=NoIOFakeRedis())

    assert settings.cacheable_task_types == ("classify", "summarize")
    assert settings.task_required_dependencies["classify"] == (
        "prompt_revision",
        "source_version",
    )
    assert runtime is not None
    classify = LLMRequest(
        messages=[{"role": "user", "content": "stable"}],
        temperature=0,
        metadata={
            "task_type": "classify",
            "llm_cache": {
                "scope": {
                    "tenant_id": "tenant",
                    "project_id": "project",
                    "policy_scope": "policy",
                },
                "dependencies": {"prompt_revision": "v1"},
            },
        },
    )
    summarize = LLMRequest.from_dict(
        {
            **classify.to_dict(redact=False),
            "metadata": {
                **classify.metadata,
                "task_type": "summarize",
            },
        }
    )
    assert runtime.policy.evaluate(classify).reason == "missing_dependency_revision"
    assert runtime.policy.evaluate(summarize).eligible is True


@pytest.mark.parametrize(
    "policy",
    [
        {"classify": {"unknown": True}},
        {"classify": {"enabled": "yes"}},
        {"classify": {"require_temperature_zero": False}},
        {"classify": {"required_dependencies": "prompt_revision"}},
    ],
)
def test_task_policy_json_rejects_unknown_or_unsafe_shapes(policy: dict[str, object]) -> None:
    with pytest.raises(LLMCacheConfigurationError, match="TASK_POLICIES_JSON"):
        LLMCacheSettings.from_env(
            _enabled_env(
                NEWS_LLM_CACHE_CACHEABLE_TASK_TYPES="",
                NEWS_LLM_CACHE_TASK_POLICIES_JSON=json.dumps(policy),
            )
        )


def test_runtime_composition_injects_one_redis_adapter_as_store_and_coordinator() -> None:
    redis = NoIOFakeRedis()
    settings = LLMCacheSettings.from_env(_enabled_env(NEWS_LLM_CACHE_MODE="observe"))

    runtime = build_llm_cache_runtime(settings, redis_client=redis)

    assert runtime is not None
    assert isinstance(runtime.store, RedisLLMCache)
    assert runtime.coordinator is runtime.store
    assert runtime.mode is CacheMode.OBSERVE


def test_router_composition_keeps_provider_client_unwrapped() -> None:
    client = FakeLLMClient(["provider result"])
    settings = LLMCacheSettings.from_env(_enabled_env(NEWS_LLM_CACHE_MODE="observe"))
    router = build_cache_aware_llm_router(
        routes=[ModelRoute(route_id="route", primary_deployment_id="deployment")],
        deployments=[
            ModelDeployment(
                deployment_id="deployment",
                provider="test",
                model="model",
                client=client,
                context_profile=ModelContextProfile(
                    deployment_id="deployment",
                    provider="test",
                    model="model",
                    physical_context_window_tokens=8_192,
                    max_output_tokens=1_024,
                    default_output_tokens=256,
                    tokenizer_family="test-byte",
                    tokenizer_revision="test-v1",
                    normalizer_revision="canonical-request-v1",
                    profile_revision="test-profile-v1",
                    allow_conservative_fallback=True,
                ),
            )
        ],
        settings=settings,
        redis_client=NoIOFakeRedis(),
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "stable"}],
        temperature=0,
        metadata={
            "task_type": "classify",
            "llm_cache": {
                "scope": {
                    "tenant_id": "tenant",
                    "project_id": "project",
                    "policy_scope": "policy",
                },
                "dependencies": {"prompt_revision": "v1"},
            },
        },
    )

    response = router.complete("route", request)

    assert response.content == "provider result"
    assert client.call_count == 1
    assert response.metadata["llm_cache_mode"] == "observe"
    assert response.metadata["llm_provider_call"] is True


def test_explicit_local_memory_backend_is_available_only_for_development() -> None:
    settings = LLMCacheSettings.from_env(
        _enabled_env(
            NEWS_LLM_CACHE_BACKEND="memory",
            NEWS_LLM_CACHE_MODE="write_only",
        )
    )
    runtime = build_llm_cache_runtime(settings)
    assert runtime is not None
    assert runtime.backend_name == "memory"

    with pytest.raises(LLMCacheConfigurationError, match="BACKEND"):
        LLMCacheSettings.from_env(
            _enabled_env(
                NEWS_LLM_CACHE_BACKEND="memory",
                NEWS_LLM_CACHE_ENVIRONMENT="production",
                NEWS_LLM_CACHE_LOCAL_TEST_MODE="false",
            )
        )


def test_configuration_errors_never_include_secret_values() -> None:
    secret = "same-secret-material-that-must-not-leak"
    env = _enabled_env(
        NEWS_LLM_CACHE_KEY_SECRET=secret,
        NEWS_LLM_CACHE_ENCRYPTION_KEY=secret,
    )
    with pytest.raises(LLMCacheConfigurationError) as raised:
        LLMCacheSettings.from_env(env)
    assert secret not in str(raised.value)


def test_manually_constructed_settings_cannot_bypass_transport_validation() -> None:
    settings = LLMCacheSettings(
        mode=CacheMode.READ_WRITE,
        backend="redis",
        redis_url="redis://cache.example.com:6379/0",
        key_secret="hmac-secret-with-independent-material",
        encryption_key=_ENCRYPTION_KEY,
    )

    with pytest.raises(LLMCacheConfigurationError, match="TLS"):
        build_llm_cache_runtime(settings, redis_client=NoIOFakeRedis())
