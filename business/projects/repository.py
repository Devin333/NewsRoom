from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import Field

from business.foundation import PrimitiveModel
from business.projects.bridge import ProjectRadarBridge
from business.projects.models import (
    EvolutionProposal,
    LabSession,
    ProjectDataset,
    UserProjectInteractionEvent,
    WatchlistItem,
)


DEFAULT_PROJECT_RUNS_ROOT = ".newsroom/runs"
DEFAULT_PROJECT_STATE_PATH = ".newsroom/projects/state.json"
PROJECT_RUNS_ROOT_ENV = "NEWSROOM_PROJECTS_RUNS_DIR"
PROJECT_STATE_PATH_ENV = "NEWSROOM_PROJECTS_STATE_PATH"
PROJECT_RUN_MARKER = "project_radar"
ARTIFACT_CANDIDATES = ("board_output.json", "output.json", "cards.json")
MANIFEST_CANDIDATE = "manifest.json"


class ProjectState(PrimitiveModel):
    watchlist_items: list[WatchlistItem] = Field(default_factory=list)
    lab_sessions: list[LabSession] = Field(default_factory=list)
    interaction_events: list[UserProjectInteractionEvent] = Field(default_factory=list)
    evolution_proposals: list[EvolutionProposal] = Field(default_factory=list)


class ProjectArtifactRepository:
    def __init__(
        self,
        *,
        runs_root: str | Path | None = None,
        bridge: ProjectRadarBridge | None = None,
    ) -> None:
        self.runs_root = Path(runs_root or os.environ.get(PROJECT_RUNS_ROOT_ENV) or DEFAULT_PROJECT_RUNS_ROOT)
        self.bridge = bridge or ProjectRadarBridge()

    def load_dataset(self) -> ProjectDataset:
        selected = self._latest_project_artifact()
        if selected is None:
            return ProjectDataset(
                source="none",
                notices=[
                    "No real Project Radar artifacts were found. Run Project Radar or configure NEWSROOM_PROJECTS_RUNS_DIR."
                ],
            )
        run_id, artifact_path, payload = selected
        dataset = self.bridge.map_payload(
            payload,
            source="artifact",
            source_run_id=run_id,
        )
        dataset.notices.insert(
            0,
            f"Loaded real Project Radar artifact {artifact_path.name} from run {run_id}.",
        )
        return dataset

    def _latest_project_artifact(self) -> tuple[str, Path, Any] | None:
        if not self.runs_root.exists():
            return None
        candidates: list[tuple[float, str, Path, Any]] = []
        try:
            entries = list(self.runs_root.iterdir())
        except OSError:
            return None
        for entry in entries:
            if not entry.is_dir():
                continue
            manifest = _read_json(entry / MANIFEST_CANDIDATE)
            run_is_project_radar = PROJECT_RUN_MARKER in entry.name.lower() or _manifest_mentions_project_radar(manifest)
            for artifact_path in _artifact_paths(entry, manifest):
                payload = _read_json(artifact_path)
                if payload is None:
                    continue
                if not run_is_project_radar and not _payload_mentions_project_radar(payload):
                    continue
                try:
                    mtime = artifact_path.stat().st_mtime
                except OSError:
                    continue
                candidates.append((mtime, entry.name, artifact_path, payload))
        for _mtime, run_id, artifact_path, payload in sorted(candidates, key=lambda item: item[0], reverse=True):
            if payload is not None:
                return run_id, artifact_path, payload
        return None


class ProjectStateRepository:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get(PROJECT_STATE_PATH_ENV) or DEFAULT_PROJECT_STATE_PATH)

    def load(self) -> ProjectState:
        payload = _read_json(self.path)
        if not isinstance(payload, dict):
            return ProjectState()
        return ProjectState.model_validate(payload)

    def save(self, state: ProjectState) -> ProjectState:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)
        return state

    def replace_watchlist(self, items: list[WatchlistItem]) -> ProjectState:
        state = self.load()
        updated = state.model_copy(update={"watchlist_items": list(items)})
        return self.save(updated)

    def replace_lab_sessions(self, sessions: list[LabSession]) -> ProjectState:
        state = self.load()
        updated = state.model_copy(update={"lab_sessions": list(sessions)})
        return self.save(updated)

    def append_interaction(self, event: UserProjectInteractionEvent) -> ProjectState:
        state = self.load()
        updated = state.model_copy(update={"interaction_events": [*state.interaction_events, event]})
        return self.save(updated)

    def replace_evolution_proposals(self, proposals: list[EvolutionProposal]) -> ProjectState:
        state = self.load()
        updated = state.model_copy(update={"evolution_proposals": list(proposals)})
        return self.save(updated)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _artifact_paths(run_dir: Path, manifest: Any) -> list[Path]:
    paths: list[Path] = []
    for relative_name in ARTIFACT_CANDIDATES:
        paths.append(run_dir / relative_name)
    if isinstance(manifest, dict):
        paths.extend(_manifest_artifact_paths(run_dir, manifest))
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        resolved = path if path.is_absolute() else run_dir / path.relative_to(run_dir) if _is_relative_to(path, run_dir) else path
        if resolved in seen or not resolved.exists() or not resolved.is_file():
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def _manifest_artifact_paths(run_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    artifacts = manifest.get("artifacts") or {}
    result: list[Path] = []
    if isinstance(artifacts, dict):
        for key, value in artifacts.items():
            if not _artifact_key_looks_relevant(str(key), value):
                continue
            result.extend(_paths_from_manifest_value(run_dir, value))
    if isinstance(artifacts, list):
        for item in artifacts:
            if not _artifact_key_looks_relevant("", item):
                continue
            result.extend(_paths_from_manifest_value(run_dir, item))
    return result


def _paths_from_manifest_value(run_dir: Path, value: Any) -> list[Path]:
    if isinstance(value, str):
        return [run_dir / value]
    if isinstance(value, dict):
        candidates = [value.get("path"), value.get("relative_path"), value.get("artifact_path"), value.get("file")]
        return [run_dir / str(candidate) for candidate in candidates if candidate]
    return []


def _manifest_mentions_project_radar(manifest: Any) -> bool:
    if not isinstance(manifest, dict):
        return False
    return PROJECT_RUN_MARKER in json.dumps(manifest, ensure_ascii=False).casefold()


def _payload_mentions_project_radar(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if _text_value(payload.get("board_type")) == PROJECT_RUN_MARKER:
        return True
    if _text_value(payload.get("type")) == PROJECT_RUN_MARKER:
        return True
    if _text_value(_nested(payload, "board_output", "board_type")) == PROJECT_RUN_MARKER:
        return True
    if _text_value(_nested(payload, "output", "board_type")) == PROJECT_RUN_MARKER:
        return True
    if _text_value(_nested(payload, "output", "board_output", "board_type")) == PROJECT_RUN_MARKER:
        return True
    return False


def _artifact_key_looks_relevant(key: str, value: Any) -> bool:
    text = f"{key} {json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}".casefold()
    return any(name.removesuffix(".json") in text for name in ARTIFACT_CANDIDATES) or PROJECT_RUN_MARKER in text


def _nested(record: Any, *keys: str) -> Any:
    current = record
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _text_value(value: Any) -> str:
    return str(value or "").strip().casefold()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
