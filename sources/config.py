from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from domain.sources import SourceDefinition
from sources.registry import SourceRegistry


class SourceConfigError(ValueError):
    pass


def load_source_definitions(path: str | Path) -> list[SourceDefinition]:
    config_path = Path(path)
    payload = _load_payload(config_path)
    source_payloads = _source_payloads(payload)
    definitions = []
    for index, source_payload in enumerate(source_payloads):
        try:
            definitions.append(_source_definition(source_payload))
        except Exception as exc:
            raise SourceConfigError(f"invalid source config at index {index}: {exc}") from exc
    return definitions


def load_source_registry(path: str | Path, *, validate: bool = True) -> SourceRegistry:
    registry = SourceRegistry(load_source_definitions(path))
    if validate:
        validation = registry.validate()
        if not validation.is_valid:
            issues = "; ".join(
                f"{issue.source_id}.{issue.field}: {issue.message}"
                for issue in validation.errors
            )
            raise SourceConfigError(f"source config validation failed: {issues}")
    return registry


def _load_payload(path: Path) -> Any:
    if not path.exists():
        raise SourceConfigError(f"source config file does not exist: {path}")
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix == ".toml":
        return tomllib.loads(path.read_text(encoding="utf-8"))
    if suffix in {".yaml", ".yml"}:
        return _load_yaml(path)
    raise SourceConfigError(f"unsupported source config file type: {path.suffix}")


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise SourceConfigError(
            "YAML source configs require PyYAML; use JSON/TOML or install pyyaml"
        ) from exc
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _source_payloads(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict) and isinstance(payload.get("sources"), list):
        values = payload["sources"]
    else:
        raise SourceConfigError("source config must be a list or an object with a sources list")
    source_payloads = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise SourceConfigError(f"source config entry at index {index} must be an object")
        source_payloads.append(value)
    return source_payloads


def _source_definition(payload: dict[str, Any]) -> SourceDefinition:
    return SourceDefinition(
        source_id=str(payload.get("source_id") or ""),
        name=str(payload.get("name") or ""),
        source_type=str(payload.get("source_type") or ""),
        url=str(payload.get("url") or ""),
        reliability=str(payload.get("reliability") or "medium"),
        authority_score=float(payload.get("authority_score", 0.5)),
        enabled=_bool_value(payload.get("enabled"), default=True),
        respect_robots=_bool_value(payload.get("respect_robots"), default=True),
        topics=_string_list(payload.get("topics")),
        category=_optional_text(payload.get("category")),
        language=_optional_text(payload.get("language")),
        region=_optional_text(payload.get("region")),
        metadata=_dict_value(payload.get("metadata")),
    )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SourceConfigError("source topics must be a list")
    return [str(item) for item in value if str(item).strip()]


def _dict_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SourceConfigError("source metadata must be an object")
    return dict(value)


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
