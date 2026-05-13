from pathlib import Path

import pytest

from core.framework.llm import (
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


def test_tracked_model_config_is_secret_free_and_loadable() -> None:
    deployment = load_openai_compatible_deployment(
        Path("configs/models.yaml"),
        route_id="daily-intelligence-writer",
    )

    assert deployment.deployment_id == "dashscope-deepseek-v4-flash"
    assert deployment.config.provider == "dashscope"
    assert deployment.config.api_key_env == "DASHSCOPE_API_KEY"
