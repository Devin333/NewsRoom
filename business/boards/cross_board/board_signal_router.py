from __future__ import annotations

from typing import Any


PRIMARY_BOARD_TYPES = ("ai_news", "project_radar", "paper_radar", "community_pulse")


class BoardSignalRouter:
    def route(self, signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        routed = {board_type: [] for board_type in PRIMARY_BOARD_TYPES}
        for signal in signals:
            board_type = _board_type_for_signal(signal)
            if board_type in routed:
                routed[board_type].append(dict(signal))
        return routed


def _board_type_for_signal(signal: dict[str, Any]) -> str:
    board_type = str(signal.get("board_type") or "").lower().replace("-", "_")
    if board_type in PRIMARY_BOARD_TYPES:
        return board_type
    signal_type = str(signal.get("signal_type") or signal.get("type") or "").lower().replace("-", "_")
    if signal_type == "github_project":
        return "project_radar"
    if signal_type == "paper":
        return "paper_radar"
    if signal_type == "community_discussion":
        return "community_pulse"
    if signal_type == "ai_news":
        return "ai_news"
    source_type = str(signal.get("source_type") or "").lower()
    if source_type == "github":
        return "project_radar"
    if source_type in {"arxiv", "paper"}:
        return "paper_radar"
    if source_type in {"reddit", "hackernews", "lobsters", "stackoverflow", "devto"}:
        return "community_pulse"
    return "ai_news"


__all__ = ["BoardSignalRouter", "PRIMARY_BOARD_TYPES"]
