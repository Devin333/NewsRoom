from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc

from backend.projects.dto import WatchlistCreateRequest, WatchlistPatchRequest
from backend.projects.models import ProjectDataset, WatchSignal, WatchlistItem, stable_id
from backend.projects.repository import ProjectStateRepository


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
        owner = request.user_id or "anonymous"
        saved: WatchlistItem | None = None

        def update(state):
            nonlocal saved
            existing = next(
                (
                    item
                    for item in state.watchlist_items
                    if item.project_id == request.project_id and item.user_id == owner and item.status != "archived"
                ),
                None,
            )
            if existing is not None:
                updated_items: list[WatchlistItem] = []
                for item in state.watchlist_items:
                    if item.id != existing.id:
                        updated_items.append(item)
                        continue
                    saved = item.model_copy(
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
                    updated_items.append(saved)
                return state.model_copy(update={"watchlist_items": updated_items})
            saved = WatchlistItem(
                id=stable_id("watchlist", owner, request.project_id, _now().isoformat()),
                user_id=owner,
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
            return state.model_copy(update={"watchlist_items": [*state.watchlist_items, saved]})

        self.state_repository.update(update)
        if saved is None:
            raise RuntimeError("watchlist update failed")
        return saved

    def patch(self, item_id: str, request: WatchlistPatchRequest, *, user_id: str | None = None) -> WatchlistItem | None:
        updated_item: WatchlistItem | None = None

        def update(state):
            nonlocal updated_item
            updated_items: list[WatchlistItem] = []
            for item in state.watchlist_items:
                if item.id != item_id:
                    updated_items.append(item)
                    continue
                if user_id is not None and item.user_id != user_id:
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
            return state.model_copy(update={"watchlist_items": updated_items})

        self.state_repository.update(update)
        return updated_item

    def refresh(self, dataset: ProjectDataset, item_id: str, *, user_id: str | None = None) -> WatchlistItem | None:
        updated_item: WatchlistItem | None = None

        def update(state):
            nonlocal updated_item
            updated_items: list[WatchlistItem] = []
            for item in state.watchlist_items:
                if item.id != item_id:
                    updated_items.append(item)
                    continue
                if user_id is not None and item.user_id != user_id:
                    updated_items.append(item)
                    continue
                if not any(project.id == item.project_id for project in dataset.projects):
                    updated_items.append(item)
                    continue
                signals = _signals_for_project(dataset, item.project_id)
                updated_item = item.model_copy(
                    update={
                        "signals": signals,
                        "last_checked_at": _now(),
                        "last_change_summary": _change_summary(signals),
                        "next_action": _next_action(signals),
                    }
                )
                updated_items.append(updated_item)
            return state.model_copy(update={"watchlist_items": updated_items})

        self.state_repository.update(update)
        return updated_item

    def delete(self, item_id: str, *, user_id: str | None = None) -> bool:
        deleted = False

        def update(state):
            nonlocal deleted
            remaining = [
                item
                for item in state.watchlist_items
                if item.id != item_id or (user_id is not None and item.user_id != user_id)
            ]
            deleted = len(remaining) != len(state.watchlist_items)
            return state.model_copy(update={"watchlist_items": remaining})

        self.state_repository.update(update)
        return deleted


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


def _change_summary(signals: list[WatchSignal]) -> str:
    if not signals:
        return "No fresh Project Radar signals were available for this watch item."
    high = sum(1 for signal in signals if signal.severity == "high")
    medium = sum(1 for signal in signals if signal.severity == "medium")
    return f"Refreshed {len(signals)} Project Radar signals ({high} high, {medium} medium)."


def _next_action(signals: list[WatchSignal]) -> str:
    if any(signal.signal_type == "metric_snapshot" for signal in signals):
        return "Review the latest metric snapshot and compare ranking movement."
    if signals:
        return "Open the source reference and verify whether follow-up analysis is needed."
    return "Run Project Radar again before making a product decision."


def _now() -> datetime:
    return datetime.now(UTC)
