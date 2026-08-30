from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.foundation import (
    BoardType,
    Confidence,
    ProcessingStatus,
    Signal,
    SignalType,
    SourceRef,
    SourceType,
    make_signal_identity,
)
from backend.foundation.models.source import RawSourceItem, SourceRankingSignals, SourceReliability
from backend.foundation.primitives import ScoreFactor, canonicalize_url, ensure_utc, normalize_key


@dataclass(frozen=True)
class SourceSignalProjectionInput:
    item: RawSourceItem
    board_type: BoardType
    signal_type: SignalType
    processing_status: ProcessingStatus
    metrics: Mapping[str, Any] = field(default_factory=dict)
    source_reliability: SourceReliability | str | None = None
    ranking_signals: SourceRankingSignals | Mapping[str, Any] | None = None


class SourceSignalProjectionService:
    def project(self, request: SourceSignalProjectionInput) -> Signal:
        item = request.item
        source_ref = SourceRef(
            source_id=item.source_id,
            source_name=item.source_name,
            source_type=_foundation_source_type(item.source_type),
            source_url=canonicalize_url(item.url) or None,
            external_id=item.source_item_id,
        )
        signal_id, canonical_key, content_hash = make_signal_identity(
            signal_type=request.signal_type,
            board_type=request.board_type,
            source=source_ref,
            title=item.title,
            url=item.url,
            published_at=item.published_at,
        )
        source_reliability = _source_reliability(request)
        ranking_signals = _ranking_signals(request)
        confidence_value = _source_confidence_value(item, source_reliability, ranking_signals)
        return Signal(
            signal_id=signal_id,
            signal_type=request.signal_type,
            board_type=request.board_type,
            title=item.title,
            summary=item.summary,
            content=item.raw_content or item.summary,
            url=canonicalize_url(item.url) or item.url,
            language=item.language or "en",
            source=source_ref,
            authors=list(item.authors),
            published_at=ensure_utc(item.published_at),
            collected_at=ensure_utc(item.fetched_at) or item.fetched_at,
            raw_payload=item.to_dict(),
            metrics={
                **{
                    "source_reliability": source_reliability,
                    "source_authority_score": ranking_signals.authority_score,
                    "canonical_url": canonicalize_url(item.url) or item.url,
                },
                **dict(request.metrics),
            },
            tags=_signal_tags(item, ranking_signals),
            content_hash=content_hash,
            canonical_key=canonical_key,
            processing_status=request.processing_status,
            confidence=Confidence(
                value=confidence_value,
                factors=_confidence_factors(item, source_reliability, ranking_signals),
            ),
        )


def _foundation_source_type(source_type: Any) -> SourceType:
    value = _source_type_value(source_type)
    mapping = {
        "rss": SourceType.RSS,
        "atom": SourceType.RSS,
        "official_blog": SourceType.OFFICIAL_BLOG,
        "github": SourceType.GITHUB,
        "arxiv": SourceType.ARXIV,
        "paper_index": SourceType.PAPER_INDEX,
        "hackernews": SourceType.HACKERNEWS,
        "reddit": SourceType.REDDIT,
        "github_discussion": SourceType.GITHUB_DISCUSSION,
        "manual": SourceType.MANUAL,
        "html": SourceType.HTML,
        "web_page": SourceType.WEB_PAGE,
        "devto": SourceType.DEVTO,
        "medium": SourceType.MEDIUM,
        "lobsters": SourceType.LOBSTERS,
        "stackoverflow": SourceType.STACKOVERFLOW,
    }
    return mapping.get(value, SourceType.HTML)


def _source_confidence_value(
    item: RawSourceItem,
    source_reliability: str,
    ranking_signals: SourceRankingSignals,
) -> float:
    reliability = _reliability_value(source_reliability)
    authority = ranking_signals.authority_score
    content = 0.7 if item.summary else 0.5
    return max(0.0, min(1.0, round(0.4 + reliability * 0.3 + authority * 0.2 + content * 0.1, 4)))


def _confidence_factors(
    item: RawSourceItem,
    source_reliability: str,
    ranking_signals: SourceRankingSignals,
) -> list[ScoreFactor]:
    return [
        ScoreFactor(
            name="source_reliability",
            value=_reliability_value(source_reliability),
            weight=0.4,
        ),
        ScoreFactor(name="source_authority", value=ranking_signals.authority_score, weight=0.3),
        ScoreFactor(
            name="content_presence",
            value=1.0 if item.summary or item.raw_content else 0.5,
            weight=0.3,
        ),
    ]


def _source_reliability(request: SourceSignalProjectionInput) -> str:
    value = (
        request.source_reliability
        if request.source_reliability is not None
        else request.item.metadata.get("source_reliability")
    )
    if isinstance(value, SourceReliability):
        return value.value
    text = str(value or "medium").strip().casefold()
    if text in {"high", "medium", "low"}:
        return text
    return "medium"


def _ranking_signals(request: SourceSignalProjectionInput) -> SourceRankingSignals:
    if isinstance(request.ranking_signals, SourceRankingSignals):
        return request.ranking_signals
    if isinstance(request.ranking_signals, Mapping):
        return SourceRankingSignals.from_dict(dict(request.ranking_signals))
    return SourceRankingSignals.from_metadata(request.item.metadata, tags=request.item.tags)


def _signal_tags(item: RawSourceItem, ranking_signals: SourceRankingSignals) -> list[str]:
    tags: list[str] = []
    tags.extend(ranking_signals.tags)
    tags.extend(_string_list(item.metadata.get("signal_tags")))
    cleaned = []
    seen = set()
    for tag in tags:
        marker = normalize_key(tag)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        cleaned.append(tag)
    return cleaned


def _source_type_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value).strip().casefold()
    return str(value).strip().casefold()


def _reliability_value(value: Any) -> float:
    text = str(value or "medium").strip().casefold()
    mapping = {
        "high": 1.0,
        "medium": 0.7,
        "low": 0.4,
    }
    return mapping.get(text, 0.7)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []
