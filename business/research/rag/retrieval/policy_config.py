from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from typing import Any


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


__all__ = ["policy_config_hash", "stable_policy_config"]
