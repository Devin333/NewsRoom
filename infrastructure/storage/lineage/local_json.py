from __future__ import annotations

import json
from pathlib import Path

from framework.agent.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from infrastructure.storage.lineage.models import LineageRef


class LocalJsonLineageStore:
    def __init__(self, root: str | Path = ".newsroom/runs/_records/lineage") -> None:
        self.root = Path(root)

    def record(self, ref: LineageRef) -> Path:
        _validate_run_id(ref.run_id)
        _validate_required(ref.source_type, "source_type")
        _validate_required(ref.source_id, "source_id")
        _validate_required(ref.target_type, "target_type")
        _validate_required(ref.target_id, "target_id")
        path = self._lineage_path(ref.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(ref.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return path

    def record_many(self, refs: list[LineageRef]) -> list[Path]:
        return [self.record(ref) for ref in refs]

    def list_by_run(self, run_id: str) -> list[LineageRef]:
        path = self._lineage_path(run_id)
        if not path.exists():
            return []
        refs = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    refs.append(LineageRef.from_dict(json.loads(stripped)))
        return refs

    def upstream(self, run_id: str, target_type: str, target_id: str) -> list[LineageRef]:
        _validate_required(target_type, "target_type")
        _validate_required(target_id, "target_id")
        return [
            ref
            for ref in self.list_by_run(run_id)
            if ref.target_type == target_type and ref.target_id == target_id
        ]

    def downstream(self, run_id: str, source_type: str, source_id: str) -> list[LineageRef]:
        _validate_required(source_type, "source_type")
        _validate_required(source_id, "source_id")
        return [
            ref
            for ref in self.list_by_run(run_id)
            if ref.source_type == source_type and ref.source_id == source_id
        ]

    def _lineage_path(self, run_id: str) -> Path:
        validated_run_id = validate_artifact_path_segment(run_id, field="run_id")
        return resolve_artifact_descendant(
            self.root,
            f"{validated_run_id}.jsonl",
            field="lineage_store_path",
        )


def _validate_run_id(run_id: str) -> None:
    validate_artifact_path_segment(run_id, field="run_id")


def _validate_required(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
