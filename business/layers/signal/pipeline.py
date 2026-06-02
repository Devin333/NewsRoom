from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from pydantic import Field

from business.foundation import (
    AnalysisContext,
    BoardType,
    Confidence,
    PrimitiveModel,
    ProcessingStatus,
    Signal,
    SignalType,
    SourceRef,
    SourceType,
    make_signal_identity,
)
from business.foundation.primitives import ScoreFactor, canonicalize_url, ensure_utc, normalize_key
from business.layers.signal.records import (
    NormalizedSourceItem,
    RankedSourceItem,
    RawSourceItem,
    SignalLineage,
    SourceRankingSignals,
    deduplicate_items,
    normalize_items,
    rank_items,
)
from business.layers.signal.models import (
    RawSignalInput,
    RejectedSignal,
    SignalNormalizeResult,
    SignalPipelineStats,
)
from business.layers.signal.source_mapper import raw_signal_input_to_source_item


class SignalPipelineResult(PrimitiveModel):
    signals: list[Signal] = Field(default_factory=list)
    raw_item_count: int = 0
    normalized_item_count: int = 0
    deduplicated_item_count: int = 0
    ranked_item_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignalPipeline:
    def run(self, inputs: list[RawSignalInput], context: AnalysisContext) -> SignalNormalizeResult:
        raw_items: list[RawSourceItem] = []
        rejected: list[RejectedSignal] = []
        for raw_input in inputs:
            try:
                raw_items.append(raw_signal_input_to_source_item(raw_input))
            except Exception as exc:
                rejected.append(
                    RejectedSignal(raw_input=raw_input, reason="parse_error", detail=str(exc))
                )
        result = self.build_from_raw_items(raw_items, context=context, board_type=context.board_type)
        stats = SignalPipelineStats.from_signals(
            result.signals,
            input_count=len(inputs),
            rejected_count=len(rejected),
            duplicate_count=max(0, len(raw_items) - len(result.signals)),
        )
        return SignalNormalizeResult(signals=result.signals, rejected=rejected, stats=stats)

    def build_from_raw_items(
        self,
        raw_items: list[RawSourceItem],
        *,
        context: AnalysisContext | None = None,
        topic: str | None = None,
        board_type: BoardType | None = None,
    ) -> SignalPipelineResult:
        resolved_context = context or AnalysisContext(board_type=board_type)
        signal_board_type = None if board_type == BoardType.CROSS_BOARD else board_type
        if board_type == BoardType.CROSS_BOARD:
            signals = [
                self.from_raw_item(
                    raw_item,
                    context=resolved_context,
                    board_type=signal_board_type,
                )
                for raw_item in raw_items
            ]
            return SignalPipelineResult(
                signals=_dedupe_signals(signals),
                raw_item_count=len(raw_items),
                normalized_item_count=len(raw_items),
                deduplicated_item_count=len(signals),
                ranked_item_count=len(signals),
                metadata={
                    "board_type": board_type.value,
                    "topic": topic or _topic_for_board(board_type, resolved_context),
                    "cross_board_preserved_source_signals": True,
                },
            )
        normalized_items = normalize_items(raw_items)
        deduped_items = deduplicate_items(normalized_items)
        ranked_items = rank_items(
            deduped_items,
            topic=topic or _topic_for_board(board_type, resolved_context),
        )
        signals = [
            self.from_ranked_item(
                ranked_item,
                context=resolved_context,
                board_type=signal_board_type,
                index=index,
            )
            for index, ranked_item in enumerate(ranked_items)
        ]
        return SignalPipelineResult(
            signals=signals,
            raw_item_count=len(raw_items),
            normalized_item_count=len(normalized_items),
            deduplicated_item_count=len(deduped_items),
            ranked_item_count=len(ranked_items),
            metadata={
                "board_type": board_type.value if board_type is not None else None,
                "topic": topic or _topic_for_board(board_type, resolved_context),
            },
        )

    def coerce_signals(
        self,
        items: list[Any],
        *,
        context: AnalysisContext | None = None,
        board_type: BoardType | None = None,
        topic: str | None = None,
    ) -> SignalPipelineResult:
        if not items:
            return SignalPipelineResult(metadata={"board_type": board_type.value if board_type else None})
        resolved_context = context or AnalysisContext(board_type=board_type)
        raw_items: list[RawSourceItem] = []
        signals: list[Signal] = []
        for item in items:
            if isinstance(item, Signal):
                signals.append(item)
                continue
            raw_item = _coerce_raw_item(item)
            if raw_item is not None:
                raw_items.append(raw_item)
                continue
            signal = _coerce_signal(item, context=resolved_context, board_type=board_type)
            if signal is not None:
                signals.append(signal)
        if raw_items:
            raw_result = self.build_from_raw_items(
                raw_items,
                context=resolved_context,
                topic=topic,
                board_type=board_type,
            )
            signals.extend(raw_result.signals)
            return raw_result.model_copy(update={"signals": _dedupe_signals(signals)})
        return SignalPipelineResult(
            signals=_dedupe_signals(signals),
            metadata={
                "board_type": board_type.value if board_type is not None else None,
                "topic": topic or _topic_for_board(board_type, resolved_context),
            },
        )

    def from_raw_item(
        self,
        item: RawSourceItem,
        *,
        context: AnalysisContext | None = None,
        board_type: BoardType | None = None,
    ) -> Signal:
        resolved_context = context or AnalysisContext(board_type=board_type)
        signal_board_type = board_type if board_type != BoardType.CROSS_BOARD else None
        return self._signal_from_source_item(
            item,
            context=resolved_context,
            board_type=signal_board_type or _board_type_for_source_type(item.source_type, resolved_context),
            signal_type=_signal_type_for_source_type(item.source_type),
            processing_status=ProcessingStatus.NORMALIZED,
            metrics={},
        )

    def from_normalized_item(
        self,
        item: NormalizedSourceItem,
        *,
        context: AnalysisContext | None = None,
        board_type: BoardType | None = None,
    ) -> Signal:
        resolved_context = context or AnalysisContext(board_type=board_type)
        signal_board_type = board_type if board_type != BoardType.CROSS_BOARD else None
        source_item = _raw_item_from_normalized(item)
        return self._signal_from_source_item(
            source_item,
            context=resolved_context,
            board_type=signal_board_type or _board_type_from_normalized_item(item, resolved_context),
            signal_type=_signal_type_for_source_type(source_item.source_type),
            processing_status=ProcessingStatus.DEDUPLICATED,
            metrics=dict(item.metadata),
        )

    def from_ranked_item(
        self,
        item: RankedSourceItem,
        *,
        context: AnalysisContext | None = None,
        board_type: BoardType | None = None,
        index: int = 0,
    ) -> Signal:
        resolved_context = context or AnalysisContext(board_type=board_type)
        signal_board_type = board_type if board_type != BoardType.CROSS_BOARD else None
        source_item = _raw_item_from_normalized(item.item)
        signal = self._signal_from_source_item(
            source_item,
            context=resolved_context,
            board_type=signal_board_type or _board_type_from_ranked_item(item, resolved_context),
            signal_type=_signal_type_for_source_type(source_item.source_type),
            processing_status=ProcessingStatus.ANALYZED,
            metrics={
                "normalized_item_id": item.item.normalized_item_id,
                "ranked_item_id": item.ranked_item_id,
                "relevance_score": item.relevance_score,
                "recency_score": item.recency_score,
                "reliability_score": item.reliability_score,
                "authority_score": item.authority_score,
                "duplicate_cluster_score": item.duplicate_cluster_score,
                "historical_importance_score": item.historical_importance_score,
                "subscription_match_score": item.subscription_match_score,
                "source_quality_score": item.source_quality_score,
                "final_score": item.final_score,
                "rank_index": index,
            },
        )
        return signal.model_copy(
            update={
                "confidence": Confidence(
                    value=_ranked_confidence(item),
                    factors=_ranked_confidence_factors(item),
                ),
            }
        )

    def _signal_from_source_item(
        self,
        item: RawSourceItem,
        *,
        context: AnalysisContext,
        board_type: BoardType,
        signal_type: SignalType,
        processing_status: ProcessingStatus,
        metrics: dict[str, Any],
    ) -> Signal:
        source_ref = SourceRef(
            source_id=item.source_id,
            source_name=item.source_name,
            source_type=_foundation_source_type(item.source_type),
            source_url=canonicalize_url(item.url) or None,
            external_id=item.source_item_id,
        )
        signal_id, canonical_key, content_hash = make_signal_identity(
            signal_type=signal_type,
            board_type=board_type,
            source=source_ref,
            title=item.title,
            url=item.url,
            published_at=item.published_at,
        )
        confidence_value = _source_confidence_value(item)
        ranking_signals = _ranking_signals_from_raw_item(item)
        return Signal(
            signal_id=signal_id,
            signal_type=signal_type,
            board_type=board_type,
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
                    "source_reliability": item.metadata.get("source_reliability", "medium"),
                    "source_authority_score": ranking_signals.authority_score,
                    "canonical_url": canonicalize_url(item.url) or item.url,
                },
                **metrics,
            },
            tags=_signal_tags(item),
            content_hash=content_hash,
            canonical_key=canonical_key,
            processing_status=processing_status,
            confidence=Confidence(
                value=confidence_value,
                factors=_confidence_factors(item, confidence_value),
            ),
        )


def _coerce_raw_item(value: Any) -> RawSourceItem | None:
    if isinstance(value, RawSourceItem):
        return value
    if _is_ranked_item_like(value):
        return _raw_item_from_normalized(value.item)
    if _is_normalized_item_like(value):
        return _raw_item_from_normalized(value)
    if _is_raw_item_like(value):
        return _raw_item_from_object(value)
    if isinstance(value, dict) and {"signal_id", "signal_type", "board_type", "source"}.issubset(value):
        return None
    if isinstance(value, dict) and {"source_item_id", "source_id", "source_name", "source_type", "title", "url"}.issubset(value):
        try:
            return RawSourceItem(
                source_item_id=str(value["source_item_id"]),
                source_id=str(value["source_id"]),
                source_name=str(value["source_name"]),
                source_type=_domain_source_type(value["source_type"]),
                title=str(value["title"]),
                url=str(value["url"]),
                fetched_at=_parse_datetime(value.get("fetched_at")) or datetime.now(),
                published_at=_parse_datetime(value.get("published_at")),
                summary=_optional_text(value.get("summary")),
                raw_content=_optional_text(value.get("raw_content")),
                authors=_string_list(value.get("authors")),
                tags=_string_list(value.get("tags")),
                language=_optional_text(value.get("language")),
                metadata=dict(value.get("metadata") or {}),
            )
        except ValueError:
            return _coerce_raw_item_from_dict(value)
    if isinstance(value, dict):
        return _coerce_raw_item_from_dict(value)
    return None


def _raw_item_from_object(value: Any) -> RawSourceItem:
    metadata = dict(getattr(value, "metadata", {}) or {})
    raw_artifact_ref = getattr(value, "raw_artifact_ref", None)
    parse_artifact_ref = getattr(value, "parse_artifact_ref", None)
    lineage = getattr(value, "lineage", None)
    return RawSourceItem(
        source_item_id=str(getattr(value, "source_item_id")),
        source_id=str(getattr(value, "source_id")),
        source_name=str(getattr(value, "source_name", None) or getattr(value, "source_id")),
        source_type=_domain_source_type(getattr(value, "source_type", metadata.get("source_type") or "rss")),
        title=str(getattr(value, "title")),
        url=str(getattr(value, "url")),
        fetched_at=_parse_datetime(getattr(value, "fetched_at", None)) or datetime.now(),
        published_at=_parse_datetime(getattr(value, "published_at", None)),
        summary=_optional_text(getattr(value, "summary", None)),
        raw_content=_optional_text(getattr(value, "raw_content", None)),
        raw_artifact_ref=raw_artifact_ref,
        parse_artifact_ref=parse_artifact_ref,
        authors=_string_list(getattr(value, "authors", None)),
        tags=_string_list(getattr(value, "tags", None)),
        language=_optional_text(getattr(value, "language", None)),
        lineage=_lineage_from_object(lineage),
        metadata=metadata,
    )


def _coerce_signal(value: Any, *, context: AnalysisContext, board_type: BoardType | None) -> Signal | None:
    if isinstance(value, Signal):
        return value
    if isinstance(value, dict) and {"signal_id", "signal_type", "board_type", "title", "source"}.issubset(value):
        return Signal.model_validate(value)
    if isinstance(value, dict):
        maybe_signal = _signal_from_board_dict(value, context=context, board_type=board_type)
        if maybe_signal is not None:
            return maybe_signal
    return None


def _raw_item_from_normalized(item: NormalizedSourceItem) -> RawSourceItem:
    lineage_metadata = item.lineage.metadata if item.lineage is not None else {}
    metadata = dict(item.metadata)
    source_type = (
        metadata.get("source_type")
        or lineage_metadata.get("source_type")
        or _infer_source_type_from_url(item.url)
        or "rss"
    )
    metadata.setdefault("source_type", _source_type_value(source_type))
    metadata.setdefault("source_reliability", item.source_reliability.value)
    metadata.setdefault("source_name", item.source_id)
    if item.summary is not None:
        metadata.setdefault("raw_content", item.summary)
    authors = _string_list(metadata.get("authors"))
    tags = _string_list(metadata.get("tags"))
    if authors:
        metadata["authors"] = authors
    if tags:
        metadata["tags"] = tags
    if item.lineage is not None:
        metadata.setdefault("lineage", item.lineage.to_dict())
    return RawSourceItem(
        source_item_id=item.source_item_id,
        source_id=item.source_id,
        source_name=str(metadata.get("source_name") or item.source_id),
        source_type=_domain_source_type(source_type),
        title=item.title,
        url=item.url,
        fetched_at=item.fetched_at,
        published_at=item.published_at,
        summary=item.summary,
        raw_content=metadata.get("raw_content"),
        authors=authors,
        tags=tags,
        language=item.language,
        lineage=item.lineage,
        metadata=metadata,
    )


def _coerce_raw_item_from_dict(value: dict[str, Any]) -> RawSourceItem | None:
    if {"signal_id", "signal_type", "board_type", "source"}.issubset(value):
        return None
    raw_metadata = value.get("metadata")
    metadata: dict[str, Any] = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    raw_source_payload = value.get("source")
    source_payload: dict[str, Any] = (
        dict(raw_source_payload) if isinstance(raw_source_payload, dict) else {}
    )
    source_type = value.get("source_type") or metadata.get("source_type") or source_payload.get("source_type")
    if source_type is None and not any(key in value for key in ("source_item_id", "source_id", "title", "url")):
        return None
    if "source_item_id" not in value and "source_id" not in value and "title" not in value and "url" not in value:
        return None
    source_item_id = str(value.get("source_item_id") or value.get("normalized_item_id") or value.get("ranked_item_id") or value.get("id") or value.get("title") or "item")
    source_id = str(value.get("source_id") or source_payload.get("source_id") or "source")
    source_name = str(value.get("source_name") or source_payload.get("source_name") or source_id)
    url = str(value.get("url") or value.get("source_url") or value.get("canonical_url") or "https://example.com")
    fetched_at = _parse_datetime(value.get("fetched_at") or value.get("collected_at")) or datetime.now()
    published_at = _parse_datetime(value.get("published_at"))
    if "source_type" not in metadata and source_type is not None:
        metadata["source_type"] = _source_type_value(source_type)
    if "source_name" not in metadata:
        metadata["source_name"] = source_name
    if "source_reliability" not in metadata:
        metadata["source_reliability"] = value.get("source_reliability") or metadata.get("source_reliability") or "medium"
    if "raw_content" not in metadata and value.get("raw_content") is not None:
        metadata["raw_content"] = value.get("raw_content")
    authors_value = value.get("authors") if value.get("authors") is not None else metadata.get("authors")
    tags_value = value.get("tags") if value.get("tags") is not None else metadata.get("tags")
    if "authors" not in metadata and authors_value is not None:
        metadata["authors"] = authors_value
    if "tags" not in metadata and tags_value is not None:
        metadata["tags"] = tags_value
    if "lineage" not in metadata and isinstance(value.get("lineage"), dict):
        metadata["lineage"] = dict(value["lineage"])
    return RawSourceItem(
        source_item_id=source_item_id,
        source_id=source_id,
        source_name=source_name,
        source_type=_domain_source_type(source_type or "rss"),
        title=str(value.get("title") or value.get("headline") or "Untitled"),
        url=url,
        fetched_at=fetched_at,
        published_at=published_at,
        summary=_optional_text(value.get("summary") or value.get("description")),
        raw_content=_optional_text(value.get("raw_content") or value.get("content")),
        authors=_string_list(authors_value),
        tags=_string_list(tags_value),
        language=_optional_text(value.get("language")),
        lineage=_lineage_from_dict(value.get("lineage")),
        metadata=metadata,
    )


def _signal_from_board_dict(
    value: dict[str, Any],
    *,
    context: AnalysisContext,
    board_type: BoardType | None,
) -> Signal | None:
    if {"signal_id", "signal_type", "board_type", "title", "source"}.issubset(value):
        return Signal.model_validate(value)
    if "title" not in value and "summary" not in value and "content" not in value:
        return None
    raw_item = _coerce_raw_item_from_dict(value)
    if raw_item is None:
        return None
    return SignalPipeline().from_raw_item(
        raw_item,
        context=context,
        board_type=board_type or _board_type_for_source_type(raw_item.source_type, context),
    )


def _signal_type_for_source_type(source_type: Any) -> SignalType:
    value = _source_type_value(source_type)
    if value in {"github"}:
        return SignalType.GITHUB_PROJECT
    if value in {"arxiv", "paper_index"}:
        return SignalType.PAPER
    if value in {"hackernews", "reddit", "github_discussion", "lobsters", "stackoverflow", "devto", "medium"}:
        return SignalType.COMMUNITY_DISCUSSION
    return SignalType.AI_NEWS


def _board_type_for_source_type(source_type: Any, context: AnalysisContext) -> BoardType:
    value = _source_type_value(source_type)
    if value in {"github"}:
        return BoardType.PROJECT_RADAR
    if value in {"arxiv", "paper_index"}:
        return BoardType.PAPER_RADAR
    if value in {"hackernews", "reddit", "github_discussion", "lobsters", "stackoverflow", "devto", "medium"}:
        return BoardType.COMMUNITY_PULSE
    return context.board_type or BoardType.AI_NEWS


def _board_type_from_normalized_item(item: NormalizedSourceItem, context: AnalysisContext) -> BoardType:
    return _board_type_for_source_type(item.metadata.get("source_type") or "rss", context)


def _board_type_from_ranked_item(item: RankedSourceItem, context: AnalysisContext) -> BoardType:
    return _board_type_from_normalized_item(item.item, context)


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


def _domain_source_type(value: Any) -> Any:
    text = _source_type_value(value)
    if text in {"paper_index", "arxiv"}:
        return "arxiv"
    if text in {"github_discussion"}:
        return "github_discussion"
    if text in {"", "none"}:
        return "html"
    return text


def _source_type_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value).strip().casefold()
    return str(value).strip().casefold()


def _infer_source_type_from_url(url: str | None) -> str | None:
    text = str(url or "").strip().casefold()
    if not text:
        return None
    if "github.com" in text:
        return "github"
    if "arxiv.org" in text:
        return "arxiv"
    if "news.ycombinator.com" in text:
        return "hackernews"
    if "reddit.com" in text:
        return "reddit"
    return None


def _topic_for_board(board_type: BoardType | None, context: AnalysisContext) -> str:
    if board_type is not None:
        return board_type.value.replace("_", " ")
    topic = context.metadata.get("topic")
    if isinstance(topic, str) and topic.strip():
        return topic
    return "ai"


def _ranked_confidence(item: RankedSourceItem) -> float:
    source_quality = item.source_quality_score if item.source_quality_score is not None else 0.5
    return max(0.0, min(1.0, round(0.3 + item.final_score * 0.5 + source_quality * 0.2, 4)))


def _ranked_confidence_factors(item: RankedSourceItem) -> list[ScoreFactor]:
    return [
        ScoreFactor(name="final_score", value=item.final_score, weight=0.5),
        ScoreFactor(
            name="source_quality_score",
            value=item.source_quality_score if item.source_quality_score is not None else 0.5,
            weight=0.3,
        ),
        ScoreFactor(name="authority_score", value=item.authority_score, weight=0.2),
    ]


def _source_confidence_value(item: RawSourceItem) -> float:
    reliability = _reliability_value(item.metadata.get("source_reliability"))
    authority = _ranking_signals_from_raw_item(item).authority_score
    content = 0.7 if item.summary else 0.5
    return max(0.0, min(1.0, round(0.4 + reliability * 0.3 + authority * 0.2 + content * 0.1, 4)))


def _confidence_factors(item: RawSourceItem, value: float) -> list[ScoreFactor]:
    ranking_signals = _ranking_signals_from_raw_item(item)
    return [
        ScoreFactor(name="source_reliability", value=_reliability_value(item.metadata.get("source_reliability")), weight=0.4),
        ScoreFactor(name="source_authority", value=ranking_signals.authority_score, weight=0.3),
        ScoreFactor(name="content_presence", value=1.0 if item.summary or item.raw_content else 0.5, weight=0.3),
    ]


def _ranking_signals_from_raw_item(item: RawSourceItem) -> SourceRankingSignals:
    return SourceRankingSignals.from_metadata(item.metadata, tags=item.tags)


def _signal_tags(item: RawSourceItem) -> list[str]:
    tags: list[str] = []
    tags.extend(_ranking_signals_from_raw_item(item).tags)
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


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _lineage_from_dict(value: Any) -> Any:
    if not isinstance(value, dict):
        return None

    try:
        return SignalLineage.from_dict(value)
    except Exception:
        return None


def _lineage_from_object(value: Any) -> SignalLineage | None:
    if value is None:
        return None
    if isinstance(value, SignalLineage):
        return value
    if isinstance(value, dict):
        return _lineage_from_dict(value)
    if hasattr(value, "to_dict"):
        return _lineage_from_dict(value.to_dict())
    if hasattr(value, "source_id"):
        return SignalLineage(
            source_id=str(getattr(value, "source_id") or "source"),
            source_item_id=_optional_text(getattr(value, "source_item_id", None)),
            normalized_item_id=_optional_text(getattr(value, "normalized_item_id", None)),
            ranked_item_id=_optional_text(getattr(value, "ranked_item_id", None)),
            raw_url=_optional_text(getattr(value, "raw_url", None)),
            canonical_url=_optional_text(getattr(value, "canonical_url", None)),
            fetched_at=_parse_datetime(getattr(value, "fetched_at", None)),
            published_at=_parse_datetime(getattr(value, "published_at", None)),
            raw_artifact_ref=getattr(value, "raw_artifact_ref", None),
            parse_artifact_ref=getattr(value, "parse_artifact_ref", None),
            metadata=dict(getattr(value, "metadata", {}) or {}),
        )
    return None


def _is_raw_item_like(value: Any) -> bool:
    return all(hasattr(value, attr) for attr in ("source_item_id", "source_id", "title", "url", "fetched_at"))


def _is_normalized_item_like(value: Any) -> bool:
    return all(hasattr(value, attr) for attr in ("normalized_item_id", "source_item_id", "source_id", "canonical_url"))


def _is_ranked_item_like(value: Any) -> bool:
    return hasattr(value, "ranked_item_id") and hasattr(value, "item")


def _dedupe_signals(signals: Iterable[Signal]) -> list[Signal]:
    seen: set[str] = set()
    result: list[Signal] = []
    for signal in signals:
        if signal.signal_id in seen:
            continue
        seen.add(signal.signal_id)
        result.append(signal)
    return result
