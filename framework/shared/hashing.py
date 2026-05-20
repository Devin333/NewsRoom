from __future__ import annotations

from hashlib import sha256
from typing import Any

from framework.shared.json import stable_json_dumps


def hash_text(text: str) -> str:
    return hash_bytes(str(text).encode("utf-8"))


def hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def stable_hash(value: Any) -> str:
    return hash_text(stable_json_dumps(value))


def short_hash(value: Any, length: int = 12) -> str:
    if length <= 0:
        raise ValueError("short hash length must be positive")
    return stable_hash(value)[:length]
