from __future__ import annotations

from business.foundation import BoardType, SignalType, SourceType


def signal_type_for_source(source_type: SourceType | str) -> SignalType:
    value = source_type.value if isinstance(source_type, SourceType) else str(source_type)
    if value == "github":
        return SignalType.GITHUB_PROJECT
    if value in {"arxiv", "paper_index"}:
        return SignalType.PAPER
    if value in {"hackernews", "reddit", "github_discussion"}:
        return SignalType.COMMUNITY_DISCUSSION
    return SignalType.AI_NEWS


def board_type_for_signal(signal_type: SignalType) -> BoardType:
    return {
        SignalType.AI_NEWS: BoardType.AI_NEWS,
        SignalType.GITHUB_PROJECT: BoardType.PROJECT_RADAR,
        SignalType.PAPER: BoardType.PAPER_RADAR,
        SignalType.COMMUNITY_DISCUSSION: BoardType.COMMUNITY_PULSE,
    }[signal_type]
