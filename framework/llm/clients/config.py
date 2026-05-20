from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from framework.llm.models.capabilities import ModelCapabilities, _normalize_capability_name
from framework.llm.clients.openai_compatible import (
    LLMConfigurationError,
    LLMRetryPolicy,
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
)


DEFAULT_MODELS_CONFIG_PATH = Path("configs/models.yaml")
DEFAULT_MODEL_ROUTE_ID = "writer-primary"
_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_VALUE_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9_.-]{8,})")
_SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
}


@dataclass(frozen=True)
class OpenAICompatibleDeploymentConfig:
    deployment_id: str
    route_id: str
    config: OpenAICompatibleConfig
    capabilities: ModelCapabilities = ModelCapabilities()
    required_capabilities: tuple[str, ...] = ()
    fallback_deployment_ids: tuple[str, ...] = ()
    enabled: bool = True
    cooldown_seconds: int | None = None
    max_retries: int = 0
    budget_policy: dict[str, Any] = None  # type: ignore[assignment]

    def retry_policy(self) -> LLMRetryPolicy:
        return LLMRetryPolicy(max_attempts=max(1, self.max_retries + 1))

    def build_client(self) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(self.config, retry_policy=self.retry_policy())


def build_openai_compatible_client_from_config(
    path: str | Path | None = None,
    *,
    route_id: str = DEFAULT_MODEL_ROUTE_ID,
) -> OpenAICompatibleClient:
    return load_openai_compatible_deployment(path, route_id=route_id).build_client()


def load_openai_compatible_deployment(
    path: str | Path | None = None,
    *,
    route_id: str | None = None,
) -> OpenAICompatibleDeploymentConfig:
    configured_path, required = _default_model_config_path(path)
    if configured_path is None:
        selected_route_id = route_id or DEFAULT_MODEL_ROUTE_ID
        return OpenAICompatibleDeploymentConfig(
            deployment_id="dashscope-default",
            route_id=selected_route_id,
            config=OpenAICompatibleConfig.dashscope_defaults(),
        )
    if not configured_path.exists():
        if required:
            raise LLMConfigurationError(f"model config file does not exist: {configured_path}")
        selected_route_id = route_id or DEFAULT_MODEL_ROUTE_ID
        return OpenAICompatibleDeploymentConfig(
            deployment_id="dashscope-default",
            route_id=selected_route_id,
            config=OpenAICompatibleConfig.dashscope_defaults(),
        )

    payload = _load_payload(configured_path)
    if not isinstance(payload, dict):
        raise LLMConfigurationError("model config must be an object")
    _assert_no_literal_secrets(payload)
    selected_route_id = _select_route_id(payload, route_id=route_id)
    routes = _dict_value(payload.get("routes"), field="routes", default={})
    route_payload = _dict_value(routes.get(selected_route_id), field=f"routes.{selected_route_id}", default={})
    deployment_payload = _select_deployment_payload(payload, route_id=selected_route_id)
    return _deployment_config(
        deployment_payload,
        route_id=selected_route_id,
        route_payload=route_payload,
    )


def _default_model_config_path(path: str | Path | None) -> tuple[Path | None, bool]:
    if path is not None:
        return Path(path), True
    env_path = os.getenv("NEWS_MODELS_CONFIG")
    if env_path:
        return Path(env_path), True
    if DEFAULT_MODELS_CONFIG_PATH.exists():
        return DEFAULT_MODELS_CONFIG_PATH, False
    return None, False


def _load_payload(path: Path) -> Any:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix == ".toml":
        return tomllib.loads(path.read_text(encoding="utf-8"))
    if suffix in {".yaml", ".yml"}:
        return _load_yaml(path)
    raise LLMConfigurationError(f"unsupported model config file type: {path.suffix}")


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise LLMConfigurationError(
            "YAML model configs require PyYAML; use JSON/TOML or install pyyaml"
        ) from exc
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _select_deployment_payload(payload: dict[str, Any], *, route_id: str) -> dict[str, Any]:
    routes = _dict_value(payload.get("routes"), field="routes", default={})
    groups = _dict_value(payload.get("model_groups"), field="model_groups", default={})
    route_payload = _dict_value(routes.get(route_id), field=f"routes.{route_id}", default={})

    group_id = _optional_text(
        route_payload.get("model_group")
        or route_payload.get("model_group_id")
        or route_payload.get("group")
    )
    deployment_id = _optional_text(
        route_payload.get("deployment_id") or route_payload.get("primary_deployment_id")
    )
    if group_id is None and route_id in groups:
        group_id = route_id

    if group_id is not None:
        group_payload = groups.get(group_id)
        if not isinstance(group_payload, dict):
            raise LLMConfigurationError(f"model group is not configured: {group_id}")
        deployments = _deployment_list(group_payload.get("deployments"), field=f"model_groups.{group_id}.deployments")
        return _select_from_deployments(deployments, deployment_id=deployment_id, field=f"model_groups.{group_id}.deployments")

    deployments = _deployment_list(payload.get("deployments"), field="deployments")
    if deployments:
        return _select_from_deployments(deployments, deployment_id=deployment_id, field="deployments")

    if groups:
        first_group_id = next(iter(groups))
        group_payload = groups[first_group_id]
        if not isinstance(group_payload, dict):
            raise LLMConfigurationError(f"model group is invalid: {first_group_id}")
        deployments = _deployment_list(
            group_payload.get("deployments"),
            field=f"model_groups.{first_group_id}.deployments",
        )
        return _select_from_deployments(
            deployments,
            deployment_id=deployment_id,
            field=f"model_groups.{first_group_id}.deployments",
        )

    raise LLMConfigurationError("model config must define at least one deployment")


def _select_route_id(payload: dict[str, Any], *, route_id: str | None) -> str:
    explicit_route_id = _optional_text(route_id)
    if explicit_route_id:
        return explicit_route_id
    routes = _dict_value(payload.get("routes"), field="routes", default={})
    configured_default = _optional_text(
        payload.get("default_route_id")
        or payload.get("default_route")
        or payload.get("default_model_route")
    )
    if configured_default:
        if routes and configured_default not in routes:
            raise LLMConfigurationError(f"default_route_id is not configured: {configured_default}")
        return configured_default
    return DEFAULT_MODEL_ROUTE_ID


def _deployment_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        values = list(value.values())
    elif isinstance(value, list):
        values = value
    else:
        raise LLMConfigurationError(f"{field} must be a list or object")
    deployments = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise LLMConfigurationError(f"{field}[{index}] must be an object")
        deployments.append(item)
    return deployments


def _select_from_deployments(
    deployments: list[dict[str, Any]],
    *,
    deployment_id: str | None,
    field: str,
) -> dict[str, Any]:
    if not deployments:
        raise LLMConfigurationError(f"{field} must contain at least one deployment")
    if deployment_id is not None:
        for deployment in deployments:
            if str(deployment.get("deployment_id") or "") == deployment_id:
                return deployment
        raise LLMConfigurationError(f"model deployment is not configured: {deployment_id}")
    for deployment in deployments:
        if _bool_value(deployment.get("enabled"), default=True):
            return deployment
    raise LLMConfigurationError(f"{field} has no enabled deployment")


def _deployment_config(
    payload: dict[str, Any],
    *,
    route_id: str,
    route_payload: dict[str, Any] | None = None,
) -> OpenAICompatibleDeploymentConfig:
    provider_kind = _env_override_text(
        payload,
        "provider",
        env_names=("NEWS_LLM_PROVIDER",),
        field="provider",
        required=True,
    )
    if provider_kind not in {"openai-compatible", "openai_compatible", "dashscope"}:
        raise LLMConfigurationError(f"unsupported OpenAI-compatible provider: {provider_kind}")
    provider_name = _optional_text(
        _env_override_text(
            payload,
            "provider_name",
            env_names=("NEWS_LLM_PROVIDER_NAME",),
            field="provider_name",
            required=False,
        )
    ) or (
        "dashscope" if provider_kind == "dashscope" else provider_kind
    )
    base_url = _env_override_text(
        payload,
        "api_base",
        aliases=("base_url", "api_url"),
        env_names=("NEWS_LLM_BASE_URL",),
        field="api_base",
        required=True,
    )
    _validate_url(base_url, field="api_base")
    api_key_env = _api_key_env(payload)
    timeout_seconds = _positive_float(
        payload.get("timeout_seconds", 90.0),
        field="timeout_seconds",
    )
    max_retries = _non_negative_int(payload.get("max_retries", 0), field="max_retries")
    capabilities = _capabilities_from_payload(payload)
    required_capabilities = _required_capabilities_from_route_payload(
        route_payload=route_payload or {}
    )
    fallback_deployment_ids = _fallback_deployment_ids_from_route_payload(
        route_payload=route_payload or {}
    )
    enabled = _bool_value(payload.get("enabled"), default=True)
    cooldown_seconds = _optional_positive_int(
        payload.get("cooldown_seconds"),
        field="cooldown_seconds",
    )
    budget_policy = _budget_policy_from_route_payload(route_payload or {})
    return OpenAICompatibleDeploymentConfig(
        deployment_id=_required_text(payload.get("deployment_id"), field="deployment_id"),
        route_id=route_id,
        config=OpenAICompatibleConfig(
            provider=provider_name,
            base_url=base_url,
            model=_env_override_text(
                payload,
                "model",
                env_names=("NEWS_LLM_MODEL",),
                field="model",
                required=True,
            ),
            api_key_env=api_key_env,
            timeout_seconds=timeout_seconds,
        ),
        capabilities=capabilities,
        required_capabilities=required_capabilities,
        fallback_deployment_ids=fallback_deployment_ids,
        enabled=enabled,
        cooldown_seconds=cooldown_seconds,
        max_retries=max_retries,
        budget_policy=budget_policy,
    )


def _api_key_env(payload: dict[str, Any]) -> str:
    api_key_env = _optional_text(
        os.getenv("NEWS_LLM_API_KEY_ENV") or payload.get("api_key_env")
    )
    if api_key_env:
        if _ENV_NAME_RE.fullmatch(api_key_env) is None:
            raise LLMConfigurationError("api_key_env must be an environment variable name")
        return api_key_env
    override_secret = _optional_text(os.getenv("NEWS_LLM_API_KEY"))
    if override_secret:
        raise LLMConfigurationError(
            "NEWS_LLM_API_KEY must not be used in model diagnostics; set NEWS_LLM_API_KEY_ENV"
        )
    api_key = _required_text(payload.get("api_key"), field="api_key")
    match = _ENV_PLACEHOLDER_RE.fullmatch(api_key)
    if match is None:
        raise LLMConfigurationError("api_key must use an environment placeholder such as ${DASHSCOPE_API_KEY}")
    return match.group(1)


def _capabilities_from_payload(payload: dict[str, Any]) -> ModelCapabilities:
    capability_payload = payload.get("capabilities")
    if capability_payload is None:
        capability_payload = payload.get("model_capabilities")
    if capability_payload is None:
        return ModelCapabilities()
    if not isinstance(capability_payload, dict):
        raise LLMConfigurationError("capabilities must be an object")
    normalized = dict(capability_payload)
    context_window_tokens = normalized.pop("context_window_tokens", None)
    max_output_tokens = normalized.pop("max_output_tokens", None)
    capability_values: dict[str, bool | int | None] = {}
    for key, value in normalized.items():
        if not isinstance(value, bool):
            raise LLMConfigurationError(f"capabilities.{key} must be a boolean")
        capability_name = _normalize_capability_name(key)
        capability_values[capability_name] = value
    if context_window_tokens is not None:
        capability_values["context_window_tokens"] = _positive_int(
            context_window_tokens,
            field="capabilities.context_window_tokens",
        )
    if max_output_tokens is not None:
        capability_values["max_output_tokens"] = _positive_int(
            max_output_tokens,
            field="capabilities.max_output_tokens",
        )
    try:
        return ModelCapabilities(**capability_values)
    except TypeError as exc:
        raise LLMConfigurationError(f"invalid capabilities config: {exc}") from exc


def _required_capabilities_from_route_payload(*, route_payload: dict[str, Any]) -> tuple[str, ...]:
    raw = route_payload.get("required_capabilities")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise LLMConfigurationError("required_capabilities must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise LLMConfigurationError("required_capabilities must contain non-empty strings")
        capability = value.strip().lower().replace("-", "_")
        if capability not in seen:
            normalized.append(capability)
            seen.add(capability)
    return tuple(normalized)


def _fallback_deployment_ids_from_route_payload(*, route_payload: dict[str, Any]) -> tuple[str, ...]:
    raw = route_payload.get("fallback_deployment_ids") or route_payload.get("fallback_deployments")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise LLMConfigurationError("fallback_deployment_ids must be a list")
    values: list[str] = []
    seen: set[str] = set()
    for value in raw:
        text = _optional_text(value)
        if text is None:
            raise LLMConfigurationError("fallback_deployment_ids must contain non-empty strings")
        if text not in seen:
            values.append(text)
            seen.add(text)
    return tuple(values)


def _budget_policy_from_route_payload(route_payload: dict[str, Any]) -> dict[str, Any]:
    raw = route_payload.get("budget_policy")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise LLMConfigurationError("budget_policy must be an object")
    return dict(raw)


def _assert_no_literal_secrets(value: Any, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            item_path = f"{path}.{key_text}" if path else key_text
            if _is_sensitive_key(key_text):
                if key_text in {"api_key", "api-key"} and isinstance(item, str) and _ENV_PLACEHOLDER_RE.fullmatch(item):
                    continue
                if key_text in {"api_key_env", "api-key-env"} and isinstance(item, str) and _ENV_NAME_RE.fullmatch(item):
                    continue
                raise LLMConfigurationError(f"model config field {item_path} must use an environment placeholder")
            _assert_no_literal_secrets(item, path=item_path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_literal_secrets(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise LLMConfigurationError(f"model config field {path or '<root>'} contains a literal secret")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").casefold()
    if normalized in _SENSITIVE_KEY_PARTS:
        return True
    parts = [part for part in normalized.split("_") if part]
    if any(part in _SENSITIVE_KEY_PARTS for part in parts):
        return True
    return any(left == "api" and right == "key" for left, right in zip(parts, parts[1:]))


def _validate_url(value: str, *, field: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMConfigurationError(f"{field} must be an http or https URL")


def _dict_value(value: Any, *, field: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if value is None:
        return dict(default or {})
    if not isinstance(value, dict):
        raise LLMConfigurationError(f"{field} must be an object")
    return dict(value)


def _required_text(value: Any, *, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise LLMConfigurationError(f"{field} is required")
    return text


def _env_override_text(
    payload: dict[str, Any],
    key: str,
    *,
    field: str,
    required: bool,
    aliases: tuple[str, ...] = (),
    env_names: tuple[str, ...] = (),
) -> str:
    for env_name in env_names:
        env_value = _optional_text(os.getenv(env_name))
        if env_value:
            return env_value
    for candidate in (key, *aliases):
        value = _optional_text(payload.get(candidate))
        if value:
            return _resolve_env_placeholder(value, field=field)
    if required:
        raise LLMConfigurationError(f"{field} is required")
    return ""


def _resolve_env_placeholder(value: str, *, field: str) -> str:
    match = _ENV_PLACEHOLDER_RE.fullmatch(value)
    if match is None:
        return value
    env_name = match.group(1)
    resolved = _optional_text(os.getenv(env_name))
    if resolved is None:
        raise LLMConfigurationError(f"{field} environment variable is not set: {env_name}")
    return resolved


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _positive_float(value: Any, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"{field} must be a number") from exc
    if parsed <= 0:
        raise LLMConfigurationError(f"{field} must be greater than zero")
    return parsed


def _positive_int(value: Any, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise LLMConfigurationError(f"{field} must be greater than zero")
    return parsed


def _optional_positive_int(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field=field)


def _non_negative_int(value: Any, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"{field} must be an integer") from exc
    if parsed < 0:
        raise LLMConfigurationError(f"{field} must be non-negative")
    return parsed

