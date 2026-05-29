from __future__ import annotations

from datetime import UTC, datetime

from business.projects.dto import WatchlistCreateRequest, WatchlistPatchRequest
from business.projects.models import ProjectDataset, WatchSignal, WatchlistItem, stable_id
from business.projects.repository import ProjectStateRepository


class ProjectWatchlistService:
    def __init__(self, state_repository: ProjectStateRepository) -> None:
        self.state_repository = state_repository

    def list(self, *, user_id: str | None = None) -> list[WatchlistItem]:
        items = self.state_repository.load().watchlist_items
        if user_id:
            items = [item for item in items if item.user_id == user_id]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def add(self, dataset: ProjectDataset, request: WatchlistCreateRequest) -> WatchlistItem:
        if not any(project.id == request.project_id for project in dataset.projects):
            raise ValueError(f"project not found: {request.project_id}")
        state = self.state_repository.load()
        existing = next(
            (
                item
                for item in state.watchlist_items
                if item.project_id == request.project_id and item.user_id == (request.user_id or "anonymous") and item.status != "archived"
            ),
            None,
        )
        if existing is not None:
            updated_items: list[WatchlistItem] = []
            updated_existing: WatchlistItem | None = None
            for item in state.watchlist_items:
                if item.id != existing.id:
                    updated_items.append(item)
                    continue
                updated_existing = item.model_copy(
                    update={
                        "watch_reason": request.watch_reason,
                        "watch_topics": request.watch_topics,
                        "priority": request.priority,
                        "notify_on": request.notify_on or item.notify_on,
                        "last_checked_at": _now(),
                        "last_change_summary": "Watch settings updated from Projects module.",
                        "next_action": "Review latest Project Radar evidence.",
                        "signals": _signals_for_project(dataset, request.project_id),
                    }
                )
                updated_items.append(updated_existing)
            self.state_repository.replace_watchlist(updated_items)
            return updated_existing or existing
        item = WatchlistItem(
            id=stable_id("watchlist", request.user_id or "anonymous", request.project_id, _now().isoformat()),
            user_id=request.user_id or "anonymous",
            project_id=request.project_id,
            watch_reason=request.watch_reason,
            watch_topics=request.watch_topics,
            priority=request.priority,
            notify_on=request.notify_on or ["release", "docs_change", "hot_score"],
            last_checked_at=_now(),
            last_change_summary="Initial watch registered from Projects module.",
            next_action="Review latest Project Radar evidence.",
            signals=_signals_for_project(dataset, request.project_id),
        )
        self.state_repository.replace_watchlist([*state.watchlist_items, item])
        return item

    def patch(self, item_id: str, request: WatchlistPatchRequest) -> WatchlistItem | None:
        state = self.state_repository.load()
        updated_items: list[WatchlistItem] = []
        updated_item: WatchlistItem | None = None
        for item in state.watchlist_items:
            if item.id != item_id:
                updated_items.append(item)
                continue
            patch = {
                key: value
                for key, value in {
                    "watch_reason": request.watch_reason,
                    "watch_topics": request.watch_topics,
                    "priority": request.priority,
                    "status": request.status,
                    "notify_on": request.notify_on,
                    "next_action": request.next_action,
                    "last_checked_at": _now(),
                }.items()
                if value is not None
            }
            updated_item = item.model_copy(update=patch)
            updated_items.append(updated_item)
        if updated_item is not None:
            self.state_repository.replace_watchlist(updated_items)
        return updated_item

    def delete(self, item_id: str) -> bool:
        state = self.state_repository.load()
        remaining = [item for item in state.watchlist_items if item.id != item_id]
        if len(remaining) == len(state.watchlist_items):
            return False
        self.state_repository.replace_watchlist(remaining)
        return True


def _signals_for_project(dataset: ProjectDataset, project_id: str) -> list[WatchSignal]:
    project = next(project for project in dataset.projects if project.id == project_id)
    signals: list[WatchSignal] = []
    metric = next((item for item in dataset.metric_snapshots if item.project_id == project_id), None)
    if metric is not None:
        signals.append(
            WatchSignal(
                id=stable_id("watch_signal", project_id, "metric"),
                project_id=project_id,
                signal_type="metric_snapshot",
                title="Latest Project Radar metric snapshot",
                summary=f"Source mentions: {metric.source_mentions}; quality: {metric.quality_score}",
                source_url=project.canonical_url,
                severity="medium",
                occurred_at=metric.snapshot_at,
            )
        )
    if project.github_url:
        signals.append(
            WatchSignal(
                id=stable_id("watch_signal", project_id, "github"),
                project_id=project_id,
                signal_type="source_available",
                title="Public repository source",
                summary="The project has a public GitHub source reference from Project Radar.",
                source_url=project.github_url,
                severity="low",
            )
        )
    return signals


def _now() -> datetime:
    return datetime.now(UTC)
