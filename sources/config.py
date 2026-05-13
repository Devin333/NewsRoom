from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from domain.sources import SourceDefinition
from sources.registry import SourceRegistry


class SourceConfigError(ValueError):
    pass


_PRD_SOURCE_SECTIONS = {
    "rss_feeds": "rss",
    "atom_feeds": "atom",
    "official_blogs": "official_blog",
    "github_lists": "github",
    "arxiv_categories": "arxiv",
}
_SOURCE_DEFINITION_FIELDS = {
    "source_id",
    "id",
    "name",
    "source_type",
    "url",
    "reliability",
    "authority_score",
    "enabled",
    "fetch_interval_seconds",
    "respect_robots",
    "user_agent",
    "topics",
    "category",
    "language",
    "region",
    "metadata",
}


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
        values = [
            *_object_list(payload["sources"], field="sources"),
            *_prd_section_payloads(payload),
        ]
    elif isinstance(payload, dict):
        values = _prd_section_payloads(payload)
    else:
        raise SourceConfigError("source config must be a list or an object with a sources list")
    if not values:
        raise SourceConfigError("source config must define at least one source")
    source_payloads = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise SourceConfigError(f"source config entry at index {index} must be an object")
        source_payloads.append(value)
    return source_payloads


def _object_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SourceConfigError(f"{field} must be a list")
    objects = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SourceConfigError(f"{field}[{index}] must be an object")
        objects.append(dict(item))
    return objects


def _prd_section_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    source_payloads: list[dict[str, Any]] = []
    for section, source_type in _PRD_SOURCE_SECTIONS.items():
        for entry in _object_list(payload.get(section), field=section):
            source_payloads.append(_normalize_section_payload(entry, section=section, source_type=source_type))
    return source_payloads


def _normalize_section_payload(
    payload: dict[str, Any],
    *,
    section: str,
    source_type: str,
) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("source_type", source_type)
    if "source_id" not in normalized and "id" in normalized:
        normalized["source_id"] = normalized["id"]
    metadata = _dict_value(normalized.get("metadata"))
    for key, value in payload.items():
        if key not in _SOURCE_DEFINITION_FIELDS and value is not None:
            metadata[key] = value
    metadata["config_section"] = section
    if section == "arxiv_categories" and "query" not in metadata:
        arxiv_category = payload.get("arxiv_category") or payload.get("category")
        if arxiv_category:
            metadata["query"] = f"cat:{arxiv_category}"
    normalized["metadata"] = metadata
    return normalized


def _source_definition(payload: dict[str, Any]) -> SourceDefinition:
    return SourceDefinition(
        source_id=str(payload.get("source_id") or ""),
        name=str(payload.get("name") or ""),
        source_type=str(payload.get("source_type") or ""),
        url=str(payload.get("url") or ""),
        reliability=str(payload.get("reliability") or "medium"),
        authority_score=float(payload.get("authority_score", 0.5)),
        enabled=_bool_value(payload.get("enabled"), default=True),
        fetch_interval_seconds=_positive_int_value(
            payload.get("fetch_interval_seconds"),
            default=3600,
            field_name="fetch_interval_seconds",
        ),
        respect_robots=_bool_value(payload.get("respect_robots"), default=True),
        user_agent=_optional_text(payload.get("user_agent")),
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


def _positive_int_value(value: Any, *, default: int, field_name: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceConfigError(f"{field_name} must be an integer") from exc
    if parsed < 1:
        raise SourceConfigError(f"{field_name} must be at least 1")
    return parsed
