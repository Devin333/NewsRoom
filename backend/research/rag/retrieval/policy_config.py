from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


class RetrievalPolicyConfigError(ValueError):
    """Raised when a retrieval policy config file cannot be loaded."""


def load_policy_config_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RetrievalPolicyConfigError(f"retrieval policy config file does not exist: {path}")
    suffix = path.suffix.casefold()
    try:
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        elif suffix in {".yaml", ".yml"}:
            payload = _load_yaml(path)
        else:
            raise RetrievalPolicyConfigError(f"unsupported retrieval policy config file type: {path.suffix}")
    except OSError as exc:
        raise RetrievalPolicyConfigError(f"could not read retrieval policy config file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RetrievalPolicyConfigError(f"retrieval policy config file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RetrievalPolicyConfigError("retrieval policy config root must be an object")
    return payload


def stable_policy_config(policy: Any) -> dict[str, Any]:
    if is_dataclass(policy):
        payload = asdict(policy)
    elif hasattr(policy, "__dict__"):
        payload = dict(policy.__dict__)
    else:
        payload = {"value": str(policy)}
    return _normalize(payload)


def policy_config_hash(policy: Any) -> str:
    payload = stable_policy_config(policy)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()[:16]


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return [_normalize(item) for item in sorted(value)]
    return value


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RetrievalPolicyConfigError(
            "YAML retrieval policy configs require PyYAML; use JSON or install pyyaml"
        ) from exc
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RetrievalPolicyConfigError(
            f"retrieval policy config file is not valid YAML: {path}"
        ) from exc


__all__ = [
    "RetrievalPolicyConfigError",
    "load_policy_config_payload",
    "policy_config_hash",
    "stable_policy_config",
]
