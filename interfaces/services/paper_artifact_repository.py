from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class PaperArtifactRepository:
    def __init__(self, *, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root).expanduser().resolve()

    def latest_paper_radar_payload(self) -> Mapping[str, Any] | None:
        for run_dir in self._candidate_run_dirs():
            manifest = self._read_json(run_dir / "manifest.json")
            if manifest is not None and not self._is_paper_radar_run(run_dir, manifest):
                continue
            payload = self._read_first_payload(run_dir, manifest)
            if payload is not None:
                return payload
        return None

    def _candidate_run_dirs(self) -> list[Path]:
        if not self.artifact_root.exists():
            return []
        return sorted(
            [path for path in self.artifact_root.iterdir() if path.is_dir()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def _is_paper_radar_run(self, run_dir: Path, manifest: Mapping[str, Any]) -> bool:
        productization = manifest.get("business_productization")
        if isinstance(productization, Mapping) and productization.get("board_type") == "paper_radar":
            return True
        metadata = manifest.get("artifact_metadata")
        if isinstance(metadata, Mapping) and metadata.get("board_type") == "paper_radar":
            return True
        return "paper_radar" in run_dir.name

    def _read_first_payload(self, run_dir: Path, manifest: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        artifact_paths = []
        artifacts = manifest.get("artifacts") if isinstance(manifest, Mapping) else None
        if isinstance(artifacts, Mapping):
            for key in ("board_output", "output", "data_buffer_final", "data_buffer_snapshot", "cards"):
                value = artifacts.get(key)
                if isinstance(value, str):
                    artifact_paths.append(run_dir / value)
        artifact_paths.extend(
            [
                run_dir / "board_output.json",
                run_dir / "output.json",
                run_dir / "data_buffer.final.json",
                run_dir / "data_buffer_snapshot.json",
                run_dir / "cards.json",
            ]
        )
        for path in artifact_paths:
            payload = self._read_json(path)
            if payload is not None:
                return payload
        return None

    def _read_json(self, path: Path) -> Mapping[str, Any] | None:
        if not path.exists() or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, Mapping) else None
