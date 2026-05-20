from pathlib import Path

import pytest

from framework.llm import (
    LLMConfigurationError,
    build_openai_compatible_client_from_config,
    load_openai_compatible_deployment,
)


def test_load_openai_compatible_deployment_reads_env_placeholder(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
model_groups:
  writer-primary:
    deployments:
      - deployment_id: compatible-live
        provider: openai-compatible
        provider_name: dashscope
        model: deepseek-v4-flash
        api_base: https://dashscope.aliyuncs.com/compatible-mode/v1
        api_key: ${TEST_LLM_KEY}
        timeout_seconds: 15
        max_retries: 2
routes:
  daily-intelligence-writer:
    model_group: writer-primary
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_LLM_KEY", "resolved-test-key")

    deployment = load_openai_compatible_deployment(
        config_path,
        route_id="daily-intelligence-writer",
    )

    assert deployment.deployment_id == "compatible-live"
    assert deployment.config.provider == "dashscope"
    assert deployment.config.model == "deepseek-v4-flash"
    assert deployment.config.api_key_env == "TEST_LLM_KEY"
    assert deployment.config.resolve_api_key() == "resolved-test-key"
    assert deployment.retry_policy().max_attempts == 3


def test_load_openai_compatible_deployment_uses_default_route_id_and_env_overrides(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
default_route_id: default-writer
model_groups:
  writer-primary:
    deployments:
      - deployment_id: compatible-live
        provider: openai-compatible
        provider_name: dashscope
        model: configured-model
        api_base: https://configured.example/v1
        api_key: ${TEST_LLM_KEY}
routes:
  default-writer:
    model_group: writer-primary
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWS_LLM_MODEL", "override-model")
    monkeypatch.setenv("NEWS_LLM_BASE_URL", "https://override.example/v1")
    monkeypatch.setenv("NEWS_LLM_API_KEY_ENV", "OVERRIDE_KEY")

    deployment = load_openai_compatible_deployment(config_path, route_id=None)

    assert deployment.route_id == "default-writer"
    assert deployment.config.model == "override-model"
    assert deployment.config.base_url == "https://override.example/v1"
    assert deployment.config.api_key_env == "OVERRIDE_KEY"


def test_load_openai_compatible_deployment_resolves_model_and_base_env_placeholders(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    model: ${TEST_LLM_MODEL}
    api_base: ${TEST_LLM_BASE_URL}
    api_key: ${TEST_LLM_KEY}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_LLM_MODEL", "resolved-model")
    monkeypatch.setenv("TEST_LLM_BASE_URL", "https://resolved.example/v1")

    deployment = load_openai_compatible_deployment(config_path)

    assert deployment.config.model == "resolved-model"
    assert deployment.config.base_url == "https://resolved.example/v1"


def test_load_openai_compatible_deployment_reads_capabilities_from_config(tmp_path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    model: test-model
    api_base: https://llm.example/v1
    api_key: ${TEST_LLM_KEY}
    capabilities:
      json_mode: true
      structured_output: true
      prompt_cache: false
      streaming: true
      context_window_tokens: 200000
      max_output_tokens: 8192
""".strip(),
        encoding="utf-8",
    )

    deployment = load_openai_compatible_deployment(config_path)

    assert deployment.capabilities.supports_json_mode is True
    assert deployment.capabilities.supports_structured_output is True
    assert deployment.capabilities.supports_prompt_cache is False
    assert deployment.capabilities.supports_streaming is True
    assert deployment.capabilities.context_window_tokens == 200000
    assert deployment.capabilities.max_output_tokens == 8192


def test_load_openai_compatible_deployment_reads_route_required_capabilities(tmp_path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    model: test-model
    api_base: https://llm.example/v1
    api_key: ${TEST_LLM_KEY}
routes:
  writer:
    deployment_id: compatible-live
    required_capabilities:
      - structured_output
      - tool_calling
""".strip(),
        encoding="utf-8",
    )

    deployment = load_openai_compatible_deployment(config_path, route_id="writer")

    assert deployment.required_capabilities == ("structured_output", "tool_calling")


def test_load_openai_compatible_deployment_reads_route_fallbacks_and_budget_policy(tmp_path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    model: test-model
    api_base: https://llm.example/v1
    api_key: ${TEST_LLM_KEY}
    cooldown_seconds: 30
routes:
  writer:
    deployment_id: compatible-live
    fallback_deployment_ids:
      - fallback-a
      - fallback-b
    budget_policy:
      max_cost_per_call_usd: 0.01
      on_budget_exceeded: fail
""".strip(),
        encoding="utf-8",
    )

    deployment = load_openai_compatible_deployment(config_path, route_id="writer")

    assert deployment.fallback_deployment_ids == ("fallback-a", "fallback-b")
    assert deployment.cooldown_seconds == 30
    assert deployment.budget_policy == {
        "max_cost_per_call_usd": 0.01,
        "on_budget_exceeded": "fail",
    }


def test_build_openai_compatible_client_from_config_uses_configured_retry_policy(tmp_path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    model: test-model
    api_base: https://llm.example/v1
    api_key: ${TEST_LLM_KEY}
    max_retries: 1
""".strip(),
        encoding="utf-8",
    )

    client = build_openai_compatible_client_from_config(config_path)

    assert client.config.model == "test-model"
    assert client._retry_policy.max_attempts == 2


def test_load_openai_compatible_deployment_rejects_invalid_fallback_list(tmp_path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    model: test-model
    api_base: https://llm.example/v1
    api_key: ${TEST_LLM_KEY}
routes:
  writer:
    deployment_id: compatible-live
    fallback_deployment_ids: fallback-a
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(LLMConfigurationError, match="fallback_deployment_ids"):
        load_openai_compatible_deployment(config_path, route_id="writer")


    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    model: test-model
    api_base: https://llm.example/v1
    api_key: ${TEST_LLM_KEY}
    capabilities:
      structured_output: sometimes
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(LLMConfigurationError, match="capabilities.structured_output"):
        load_openai_compatible_deployment(config_path)


def test_model_config_rejects_literal_api_key(tmp_path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: bad
    provider: openai-compatible
    model: test-model
    api_base: https://llm.example/v1
    api_key: literal-secret-value
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(LLMConfigurationError, match="api_key"):
        load_openai_compatible_deployment(config_path)


def test_model_config_diagnostics_reject_raw_api_key_env_without_printing_secret(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    model: test-model
    api_base: https://llm.example/v1
    api_key: ${TEST_LLM_KEY}
""".strip(),
        encoding="utf-8",
    )
    secret = "sk-secret-value-for-test"
    monkeypatch.setenv("NEWS_LLM_API_KEY", secret)

    with pytest.raises(LLMConfigurationError) as exc_info:
        load_openai_compatible_deployment(config_path)

    assert secret not in str(exc_info.value)
    assert "NEWS_LLM_API_KEY_ENV" in str(exc_info.value)


def test_model_config_reports_missing_required_fields(tmp_path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
deployments:
  - deployment_id: compatible-live
    provider: openai-compatible
    api_key: ${TEST_LLM_KEY}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(LLMConfigurationError, match="api_base is required"):
        load_openai_compatible_deployment(config_path)


def test_tracked_model_config_is_secret_free_and_loadable() -> None:
    deployment = load_openai_compatible_deployment(
        Path("configs/models.yaml"),
        route_id="daily-intelligence-writer",
    )

    assert deployment.deployment_id == "dashscope-deepseek-v4-flash"
    assert deployment.config.provider == "dashscope"
    assert deployment.config.api_key_env == "DASHSCOPE_API_KEY"

