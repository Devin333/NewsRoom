from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from framework.llm import (
    LLMConfigurationError,
    load_openai_compatible_deployment,
    validate_openai_compatible_models_config,
)


@pytest.fixture(autouse=True)
def _clear_llm_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "NEWS_LLM_PROVIDER",
        "NEWS_LLM_PROVIDER_NAME",
        "NEWS_LLM_BASE_URL",
        "NEWS_LLM_MODEL",
        "NEWS_LLM_API_KEY",
        "NEWS_LLM_API_KEY_ENV",
    ):
        monkeypatch.delenv(name, raising=False)


def _valid_payload() -> dict:
    return {
        "default_route_id": "writer",
        "model_groups": {
            "writer-group": {
                "deployments": [
                    {
                        "deployment_id": "writer-primary",
                        "provider": "openai-compatible",
                        "provider_name": "test-provider",
                        "model": "test-model",
                        "api_base": "https://llm.example/v1",
                        "api_key": "${TEST_LLM_API_KEY}",
                        "timeout_seconds": 30,
                        "max_retries": 2,
                        "capabilities": {
                            "supports_tool_calling": True,
                            "context_window_tokens": 8192,
                            "max_output_tokens": 1024,
                        },
                        "context_profile": {
                            "default_output_tokens": 256,
                            "tokenizer_family": "test-tokenizer",
                            "tokenizer_revision": "v1",
                            "normalizer_revision": "openai-chat-completions-v1",
                            "profile_revision": "profile-v1",
                            "operational_input_fraction": 0.9,
                            "safety_margin_tokens": 64,
                            "allow_conservative_fallback": True,
                        },
                    },
                    {
                        "deployment_id": "writer-fallback",
                        "provider": "openai-compatible",
                        "provider_name": "test-provider",
                        "model": "test-model-fallback",
                        "api_base": "https://llm.example/v1",
                        "api_key_env": "TEST_LLM_FALLBACK_KEY",
                        "timeout_seconds": 30,
                        "max_retries": 0,
                    },
                ],
            }
        },
        "routes": {
            "writer": {
                "model_group": "writer-group",
                "deployment_id": "writer-primary",
                "fallback_deployment_ids": ["writer-fallback"],
                "required_capabilities": ["tool-calling"],
                "budget_policy": {"max_tokens_per_call": 1000},
            }
        },
    }


def _write_config(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "models.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_openai_compatible_deployment_validates_and_selects_route(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _valid_payload())

    deployment = load_openai_compatible_deployment(path, route_id="writer")

    assert deployment.deployment_id == "writer-primary"
    assert deployment.route_id == "writer"
    assert deployment.config.provider == "test-provider"
    assert deployment.config.api_key_env == "TEST_LLM_API_KEY"
    assert deployment.fallback_deployment_ids == ("writer-fallback",)
    assert deployment.required_capabilities == ("tool_calling",)
    assert deployment.context_profile is not None
    assert deployment.context_profile.deployment_id == "writer-primary"
    assert deployment.context_profile.provider == "test-provider"
    assert deployment.context_profile.model == "test-model"
    assert deployment.context_profile.physical_context_window_tokens == 8192
    assert deployment.context_profile.max_output_tokens == 1024
    assert deployment.context_profile.default_output_tokens == 256
    assert deployment.context_profile.allow_conservative_fallback is True

    model_deployment = deployment.build_model_deployment()
    assert model_deployment.deployment_id == deployment.deployment_id
    assert model_deployment.provider == "test-provider"
    assert model_deployment.model == "test-model"
    assert model_deployment.context_profile == deployment.context_profile


def test_models_config_rejects_route_referencing_unknown_group() -> None:
    payload = _valid_payload()
    payload["routes"]["writer"]["model_group"] = "missing-group"

    with pytest.raises(LLMConfigurationError, match="routes.writer.model_group"):
        validate_openai_compatible_models_config(payload)


def test_models_config_rejects_invalid_unselected_group_before_route_selection(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["model_groups"]["broken-group"] = {
        "deployments": [
            {
                "deployment_id": "broken",
                "provider": "openai-compatible",
                "api_base": "https://llm.example/v1",
                "api_key": "${TEST_LLM_API_KEY}",
            }
        ]
    }
    path = _write_config(tmp_path, payload)

    with pytest.raises(LLMConfigurationError, match=r"broken-group\.deployments\[0\]\.model"):
        load_openai_compatible_deployment(path, route_id="writer")


def test_models_config_rejects_unknown_top_level_field() -> None:
    payload = _valid_payload()
    payload["routez"] = {}

    with pytest.raises(LLMConfigurationError, match=r"model config contains unsupported field\(s\): routez"):
        validate_openai_compatible_models_config(payload)


def test_models_config_parse_error_is_configuration_error_without_file_content(tmp_path: Path) -> None:
    secret = "sk-test-secret-value"
    path = tmp_path / "models.json"
    path.write_text(f'{{"api_key": "{secret}",', encoding="utf-8")

    with pytest.raises(LLMConfigurationError) as exc_info:
        load_openai_compatible_deployment(path, route_id="writer")

    message = str(exc_info.value)
    assert "not valid JSON" in message
    assert str(path) in message
    assert secret not in message


def test_models_config_rejects_unknown_deployment_field() -> None:
    payload = _valid_payload()
    payload["model_groups"]["writer-group"]["deployments"][0]["timeout_second"] = 30

    with pytest.raises(
        LLMConfigurationError,
        match=r"model_groups\.writer-group\.deployments\[0\] contains unsupported field\(s\): timeout_second",
    ):
        validate_openai_compatible_models_config(payload)


def test_models_config_rejects_unknown_route_field() -> None:
    payload = _valid_payload()
    payload["routes"]["writer"]["model_gorup"] = "writer-group"

    with pytest.raises(LLMConfigurationError, match=r"routes\.writer contains unsupported field\(s\): model_gorup"):
        validate_openai_compatible_models_config(payload)


def test_models_config_rejects_unknown_capability_field() -> None:
    payload = _valid_payload()
    payload["model_groups"]["writer-group"]["deployments"][0]["capabilities"]["supports_toolz"] = True

    with pytest.raises(LLMConfigurationError, match=r"capabilities contains unsupported field\(s\): supports_toolz"):
        validate_openai_compatible_models_config(payload)


def test_models_config_rejects_unknown_context_profile_field() -> None:
    payload = _valid_payload()
    payload["model_groups"]["writer-group"]["deployments"][0]["context_profile"][
        "tokenizer_verzion"
    ] = "v2"

    with pytest.raises(
        LLMConfigurationError,
        match=r"context_profile contains unsupported field\(s\): tokenizer_verzion",
    ):
        validate_openai_compatible_models_config(payload)


def test_models_config_requires_context_profile_capacity_from_profile_or_capabilities() -> None:
    payload = _valid_payload()
    deployment = payload["model_groups"]["writer-group"]["deployments"][0]
    deployment["capabilities"].pop("max_output_tokens")

    with pytest.raises(
        LLMConfigurationError,
        match=r"context_profile\.max_output_tokens or capabilities\.max_output_tokens is required",
    ):
        validate_openai_compatible_models_config(payload)


def test_models_config_rejects_context_profile_default_above_model_maximum() -> None:
    payload = _valid_payload()
    payload["model_groups"]["writer-group"]["deployments"][0]["context_profile"][
        "default_output_tokens"
    ] = 2048

    with pytest.raises(
        LLMConfigurationError,
        match="default_output_tokens must not exceed max_output_tokens",
    ):
        validate_openai_compatible_models_config(payload)


def test_context_profile_can_define_physical_limits_without_capability_aliases(
    tmp_path: Path,
) -> None:
    payload = _valid_payload()
    deployment_payload = payload["model_groups"]["writer-group"]["deployments"][0]
    deployment_payload["capabilities"].pop("context_window_tokens")
    deployment_payload["capabilities"].pop("max_output_tokens")
    deployment_payload["context_profile"]["physical_context_window_tokens"] = 16384
    deployment_payload["context_profile"]["max_output_tokens"] = 2048
    path = _write_config(tmp_path, payload)

    deployment = load_openai_compatible_deployment(path, route_id="writer")

    assert deployment.context_profile is not None
    assert deployment.context_profile.physical_context_window_tokens == 16384
    assert deployment.context_profile.max_output_tokens == 2048


def test_models_config_requires_api_key_reference() -> None:
    payload = _valid_payload()
    deployment = payload["model_groups"]["writer-group"]["deployments"][0]
    deployment.pop("api_key")

    with pytest.raises(LLMConfigurationError, match="api_key or .*api_key_env"):
        validate_openai_compatible_models_config(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("timeout_seconds", 0, "must be greater than zero"),
        ("max_retries", -1, "must be non-negative"),
    ],
)
def test_models_config_rejects_invalid_numeric_fields(field: str, value: int, message: str) -> None:
    payload = _valid_payload()
    payload["model_groups"]["writer-group"]["deployments"][0][field] = value

    with pytest.raises(LLMConfigurationError, match=message):
        validate_openai_compatible_models_config(payload)


def test_models_config_error_does_not_expose_literal_secret() -> None:
    payload = _valid_payload()
    secret = "sk-test-secret-value"
    payload["model_groups"]["writer-group"]["deployments"][0]["api_key"] = secret

    with pytest.raises(LLMConfigurationError) as exc_info:
        validate_openai_compatible_models_config(payload)

    assert secret not in str(exc_info.value)


def test_models_config_rejects_unknown_route_without_falling_back_to_first_group(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _valid_payload())

    with pytest.raises(LLMConfigurationError, match="model route is not configured: typo-route"):
        load_openai_compatible_deployment(path, route_id="typo-route")


def test_models_config_accepts_top_level_deployments_without_routes(tmp_path: Path) -> None:
    payload = deepcopy(_valid_payload())
    payload.pop("model_groups")
    payload.pop("routes")
    payload.pop("default_route_id")
    payload["deployments"] = [
        {
            "deployment_id": "top-level",
            "provider": "openai-compatible",
            "provider_name": "test-provider",
            "model": "test-model",
            "api_base": "https://llm.example/v1",
            "api_key_env": "TEST_LLM_API_KEY",
        }
    ]
    path = _write_config(tmp_path, payload)

    deployment = load_openai_compatible_deployment(path, route_id="adhoc")

    assert deployment.deployment_id == "top-level"
    assert deployment.route_id == "adhoc"
