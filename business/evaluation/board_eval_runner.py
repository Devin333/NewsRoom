from __future__ import annotations

from pathlib import Path
from typing import Any

from business.evaluation.board_eval_case import BoardEvalCase
from business.evaluation.board_eval_report import BoardEvalReport
from business.evaluation.board_eval_result import BoardEvalResult


class BoardEvalRunner:
    def __init__(self, *, artifact_root: str | Path = ".newsroom/evals") -> None:
        self.artifact_root = Path(artifact_root)

    def run_case(self, case: BoardEvalCase) -> BoardEvalResult:
        from business.boards._runner import runner_for_board_type

        failures: list[str] = []
        try:
            result = runner_for_board_type(case.board_type, artifact_root=self.artifact_root).run(
                signals=case.signals,
                topic=case.topic,
                run_id=f"eval-{case.case_id}",
            )
            output = result.output
        except Exception as exc:
            return BoardEvalResult(
                case_id=case.case_id,
                board_type=case.board_type,
                passed=False,
                score=0.0,
                failures=[f"unhandled error: {type(exc).__name__}: {exc}"],
                metrics={"unhandled_errors": 1},
            )

        cards = _list(output.get("cards"))
        quality = _dict(output.get("quality_summary"))
        subscription = _dict(output.get("subscription_payload"))
        recommendations = _list(output.get("improvement_recommendations"))
        card_count = len(cards)
        quality_score = _quality_score(quality)
        subscription_tags = _subscription_tags(subscription)
        evidence_coverage = _evidence_coverage(cards)
        ranking_relevance = _ranking_relevance(cards)
        if card_count < case.expected_min_cards:
            failures.append(f"card_count {card_count} < {case.expected_min_cards}")
        if quality_score < case.expected_quality_min:
            failures.append(f"quality_score {quality_score} < {case.expected_quality_min}")
        missing_tags = [tag for tag in case.expected_subscription_tags if tag not in subscription_tags]
        if missing_tags:
            failures.append(f"missing subscription tags: {', '.join(missing_tags)}")
        if case.expected_entities:
            haystack = str(subscription).casefold()
            missing_entities = [entity for entity in case.expected_entities if entity.casefold() not in haystack]
            if missing_entities:
                failures.append(f"missing expected entities: {', '.join(missing_entities)}")
        metric_values = {
            "card_count": card_count,
            "quality_score": quality_score,
            "ranking_relevance": ranking_relevance,
            "evidence_coverage": evidence_coverage,
            "subscription_tag_match": _tag_match(subscription_tags, case.expected_subscription_tags),
            "improvement_recommendation_count": len(recommendations),
            "unhandled_errors": 0,
        }
        score = round(
            (
                min(1.0, card_count / max(1, case.expected_min_cards))
                + quality_score
                + ranking_relevance
                + evidence_coverage
                + metric_values["subscription_tag_match"]
            )
            / 5,
            4,
        )
        return BoardEvalResult(
            case_id=case.case_id,
            board_type=case.board_type,
            passed=not failures,
            score=score,
            failures=failures,
            metrics=metric_values,
        )

    def run_suite(self, cases: list[BoardEvalCase]) -> BoardEvalReport:
        return BoardEvalReport(results=[self.run_case(case) for case in cases])


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _quality_score(quality: dict[str, Any]) -> float:
    value = quality.get("score")
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _subscription_tags(payload: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for target in payload.get("targets") or []:
        if isinstance(target, dict):
            tags.extend(str(tag) for tag in target.get("tags") or [])
    return tags


def _evidence_coverage(cards: list[Any]) -> float:
    if not cards:
        return 0.0
    covered = 0
    for card in cards:
        payload = _dict(card)
        if payload.get("evidence_refs"):
            covered += 1
    return round(covered / len(cards), 4)


def _ranking_relevance(cards: list[Any]) -> float:
    if not cards:
        return 0.0
    relevant = 0
    for card in cards:
        payload = _dict(card)
        if payload.get("ranking_reason") or payload.get("ranking_features"):
            relevant += 1
    return round(relevant / len(cards), 4)


def _tag_match(actual: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    return round(len(set(actual) & set(expected)) / len(set(expected)), 4)


__all__ = ["BoardEvalRunner"]
