from __future__ import annotations

import json
from dataclasses import is_dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


class ArtifactManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def start_run(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def write_json(self, run_id: str, name: str, data: Any) -> Path:
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(_json_safe(data), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target

    def write_text(self, run_id: str, name: str, text: str) -> Path:
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def _target(self, run_id: str, name: str) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"artifact name must be relative to the run directory: {name}")
        return self.run_dir(run_id) / relative
