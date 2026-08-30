from __future__ import annotations

from typing import Any

from backend.foundation import (
    Badge,
    BoardCard,
    BoardType,
    BusinessProvenance,
    BusinessQualityCheck,
    Confidence,
    DisplayMetric,
    ObjectRef,
    ObjectType,
    Relation,
    Signal,
    Score,
    build_stable_id,
    quality_snapshot_from_checks,
)
from backend.layers.analysis.pipeline import AnalysisResult
from backend.layers.extraction.models import ExtractionResult


class BoardCardBuilder:
    def build_card(
        self,
        signal: Signal,
        extraction: ExtractionResult,
        relations: list[Relation],
        analysis: AnalysisResult,
        board_type: BoardType,
    ) -> BoardCard:
        primary = _primary_object(signal, extraction)
        score = _board_score(signal, extraction, relations, analysis)
        badges = _badges(signal, extraction, analysis)
        metrics = _metrics(signal, extraction, relations)
        related_refs = _related_refs(extraction, relations)
        return BoardCard(
            card_id=build_stable_id("card", board_type.value, primary.object_id),
            board_type=board_type,
            title=_card_title(signal, extraction),
            subtitle=_card_subtitle(signal),
            summary=_card_summary(signal),
            primary_object_ref=primary,
            badges=badges,
            metrics=metrics,
            related_refs=related_refs,
            score=score,
            confidence=_card_confidence(signal, extraction, relations),
            published_at=signal.published_at,
            ranking_reason=_ranking_reason(signal, score, relations),
            ranking_features=_ranking_features(score),
            evidence_refs=[signal.source],
            provenance=BusinessProvenance(
                source_refs=[signal.source],
                evidence_refs=[signal.source],
                upstream_object_refs=[signal.source],
            ),
            quality=quality_snapshot_from_checks(
                [
                    BusinessQualityCheck.create(
                        "card_has_evidence_refs",
                        passed=True,
                        reason="Card includes source evidence.",
                        evidence_refs=[signal.source],
                    ),
                    BusinessQualityCheck.create(
                        "card_has_ranking_reason",
                        passed=True,
                        reason="Card includes deterministic ranking reason.",
                    ),
                ],
                score=score.value,
                confidence=signal.confidence.value if signal.confidence else None,
            ),
            metadata={"signal_id": signal.signal_id, "board_type": board_type.value},
        )


def _primary_object(signal: Signal, extraction: ExtractionResult) -> ObjectRef:
    if extraction.technologies:
        technology = extraction.technologies[0]
        return ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name)
    if extraction.entities:
        entity = extraction.entities[0]
        return ObjectRef(object_type="entity", object_id=entity.entity_id, label=entity.canonical_name)
    if extraction.topics:
        topic = extraction.topics[0]
        return ObjectRef(object_type="topic", object_id=topic.topic_id, label=topic.name)
    return ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title)


def _card_title(signal: Signal, extraction: ExtractionResult) -> str:
    primary = _primary_object(signal, extraction)
    return primary.label or signal.title


def _card_subtitle(signal: Signal) -> str:
    parts = [signal.source.source_name]
    if signal.published_at:
        parts.append(signal.published_at.isoformat())
    return " | ".join(parts)


def _card_summary(signal: Signal) -> str:
    return signal.summary or signal.content or signal.title


def _card_confidence(signal: Signal, extraction: ExtractionResult, relations: list[Relation]) -> Confidence:
    base = signal.confidence.value if signal.confidence else 0.6
    relation_boost = min(0.2, len(relations) * 0.02)
    extraction_boost = min(0.1, (len(extraction.entities) + len(extraction.technologies)) * 0.02)
    return Confidence(value=min(1.0, base + relation_boost + extraction_boost), factors=list(signal.confidence.factors) if signal.confidence else [])


def _badges(signal: Signal, extraction: ExtractionResult, analysis: AnalysisResult) -> list[Badge]:
    badges = [Badge(label=signal.board_type.value), Badge(label=signal.signal_type.value)]
    if analysis.radar_items:
        badges.append(Badge(label=analysis.radar_items[0].recommendation.value.replace("_", " ")))
    if extraction.technologies:
        badges.append(Badge(label=extraction.technologies[0].category.value))
    return badges


def _metrics(signal: Signal, extraction: ExtractionResult, relations: list[Relation]) -> list[DisplayMetric]:
    return [
        DisplayMetric(label="Relations", value=len(relations)),
        DisplayMetric(label="Technologies", value=len(extraction.technologies)),
        DisplayMetric(label="Signals", value=1),
    ]


def _related_refs(extraction: ExtractionResult, relations: list[Relation]) -> list[ObjectRef]:
    refs = [relation.target_ref for relation in relations]
    if extraction.technologies:
        refs.extend(ObjectRef(object_type="technology", object_id=item.technology_id, label=item.name) for item in extraction.technologies)
    return _dedupe_refs(refs)


def _board_score(signal: Signal, extraction: ExtractionResult, relations: list[Relation], analysis: AnalysisResult) -> Score:
    technology_ids = {technology.technology_id for technology in extraction.technologies}
    trend = next((item for item in analysis.trends if item.target_ref.object_id in technology_ids), None)
    quality = next((item for item in analysis.qualities if item.target_ref.object_id == signal.signal_id), None)
    impact = next((item for item in analysis.impacts if item.target_ref.object_id in technology_ids), None)
    value = 0.4
    factors = []
    if trend is not None:
        value += 0.2 * trend.score.value
        factors.extend(trend.score.factors)
    if quality is not None:
        value += 0.2 * quality.score.value
        factors.extend(quality.score.factors)
    if impact is not None:
        value += 0.2 * impact.score.value
        factors.extend(impact.score.factors)
    return Score(value=min(1.0, round(value, 4)), factors=factors)


def _ranking_features(score: Score) -> dict[str, Any]:
    features: dict[str, Any] = {"score": score.value}
    for factor in score.factors:
        features[factor.name] = factor.value
    return features


def _ranking_reason(signal: Signal, score: Score, relations: list[Relation]) -> str:
    factor_names = [factor.name for factor in score.factors[:3]]
    if factor_names:
        return f"Ranked from {signal.signal_type.value} with score {score.value:.2f}; key factors: {', '.join(factor_names)}."
    return f"Ranked from {signal.signal_type.value} with score {score.value:.2f} and {len(relations)} relation(s)."


def _dedupe_refs(refs: list[ObjectRef]) -> list[ObjectRef]:
    seen: set[tuple[str, str]] = set()
    result: list[ObjectRef] = []
    for ref in refs:
        marker = (ObjectType(ref.object_type).value, ref.object_id)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(ref)
    return result


__all__ = ["BoardCardBuilder"]
