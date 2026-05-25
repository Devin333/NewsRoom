from __future__ import annotations

import os
from pathlib import Path


def load_root_env(*, override: bool = False) -> Path | None:
    env_path = _repo_root() / ".env"
    if not env_path.exists():
        return None

    for key, value in _read_env_file(env_path).items():
        if not override and key in os.environ:
            continue
        os.environ[key] = value

    return env_path


def env_values_from_root(*, override: bool = False) -> dict[str, str]:
    values = dict(os.environ)
    env_path = _repo_root() / ".env"
    if not env_path.exists():
        return values

    for key, value in _read_env_file(env_path).items():
        if not override and key in values:
            continue
        values[key] = value

    return values


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        key = name.strip()
        if key:
            values[key] = _normalize_env_value(value.strip())
    return values


def _normalize_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
