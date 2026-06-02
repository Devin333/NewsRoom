from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from business.foundation.feedback.measurement import ImprovementMeasurement, ImprovementMeasurementBuilder


@dataclass(frozen=True)
class ProductizedImprovementMeasurementInput:
    quality_summary: dict[str, Any]
    cards: list[dict[str, Any]]
    subscription_payload: dict[str, Any]
    deduplication_result: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_productized_run(
        cls,
        *,
        quality_summary: dict[str, Any],
        cards: list[dict[str, Any]],
        subscription_payload: dict[str, Any],
        productized_run: Any | None = None,
    ) -> "ProductizedImprovementMeasurementInput":
        return cls(
            quality_summary=quality_summary,
            cards=cards,
            subscription_payload=subscription_payload,
            deduplication_result=deduplication_result_from_productized_run(productized_run),
        )

    @classmethod
    def from_legacy_inputs(
        cls,
        *,
        quality_summary: dict[str, Any],
        cards: list[dict[str, Any]],
        subscription_payload: dict[str, Any],
        board_run_result: Any = None,
        productized_run: Any | None = None,
    ) -> "ProductizedImprovementMeasurementInput":
        deduplication_result = _deduplication_result_from_productized_run(productized_run)
        if deduplication_result is None:
            deduplication_result = _legacy_deduplication_result_from_board_result(board_run_result) or {}
        return cls(
            quality_summary=quality_summary,
            cards=cards,
            subscription_payload=subscription_payload,
            deduplication_result=deduplication_result,
        )


@dataclass(frozen=True)
class ProductizedImprovementMeasurementSnapshot:
    quality_score: Any
    card_count: int
    evidence_coverage: float
    duplicate_rate: float
    empty_output: bool
    subscription_match: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProductizedImprovementMeasurementService:
    def __init__(self, *, measurement_builder: ImprovementMeasurementBuilder | None = None) -> None:
        self.measurement_builder = measurement_builder or ImprovementMeasurementBuilder()

    def snapshot(
        self,
        *,
        quality_summary: dict[str, Any],
        cards: list[dict[str, Any]],
        board_run_result: Any,
        subscription_payload: dict[str, Any],
        productized_run: Any | None = None,
    ) -> ProductizedImprovementMeasurementSnapshot:
        return self.snapshot_input(
            ProductizedImprovementMeasurementInput.from_legacy_inputs(
                quality_summary=quality_summary,
                cards=cards,
                subscription_payload=subscription_payload,
                board_run_result=board_run_result,
                productized_run=productized_run,
            )
        )

    def snapshot_input(
        self,
        measurement_input: ProductizedImprovementMeasurementInput,
    ) -> ProductizedImprovementMeasurementSnapshot:
        return ProductizedImprovementMeasurementSnapshot(
            quality_score=(
                measurement_input.quality_summary.get("score")
                if isinstance(measurement_input.quality_summary, dict)
                else None
            ),
            card_count=len(measurement_input.cards),
            evidence_coverage=evidence_coverage(measurement_input.cards),
            duplicate_rate=duplicate_rate_from_deduplication_result(
                measurement_input.deduplication_result,
            ),
            empty_output=len(measurement_input.cards) == 0,
            subscription_match=1.0 if measurement_input.subscription_payload.get("targets") else 0.0,
        )

    def measure(
        self,
        *,
        previous_baseline: dict[str, Any] | None,
        quality_summary: dict[str, Any],
        cards: list[dict[str, Any]],
        board_run_result: Any,
        subscription_payload: dict[str, Any],
        productized_run: Any | None = None,
    ) -> ImprovementMeasurement:
        return self.measure_input(
            previous_baseline=previous_baseline,
            measurement_input=ProductizedImprovementMeasurementInput.from_legacy_inputs(
                quality_summary=quality_summary,
                cards=cards,
                subscription_payload=subscription_payload,
                board_run_result=board_run_result,
                productized_run=productized_run,
            ),
        )

    def measure_input(
        self,
        *,
        previous_baseline: dict[str, Any] | None,
        measurement_input: ProductizedImprovementMeasurementInput,
    ) -> ImprovementMeasurement:
        return self.measurement_builder.measure(
            previous_baseline,
            self.snapshot_input(measurement_input).to_dict(),
        )


def measurement_snapshot(
    *,
    quality_summary: dict[str, Any],
    cards: list[dict[str, Any]],
    board_run_result: Any,
    subscription_payload: dict[str, Any],
    productized_run: Any | None = None,
) -> dict[str, Any]:
    return ProductizedImprovementMeasurementService().snapshot(
        quality_summary=quality_summary,
        cards=cards,
        board_run_result=board_run_result,
        subscription_payload=subscription_payload,
        productized_run=productized_run,
    ).to_dict()


def evidence_coverage(cards: list[dict[str, Any]]) -> float:
    if not cards:
        return 0.0
    return round(sum(1 for card in cards if card.get("evidence_refs")) / len(cards), 4)


def duplicate_rate(result: Any = None, *, productized_run: Any | None = None) -> float:
    return duplicate_rate_from_deduplication_result(
        deduplication_result_for_measurement(
            productized_run=productized_run,
            board_run_result=result,
        )
    )


def duplicate_rate_from_deduplication_result(deduplication_result: dict[str, Any]) -> float:
    groups = deduplication_result.get("event_groups") if isinstance(deduplication_result, dict) else []
    if not groups:
        return 0.0
    duplicate_groups = [
        group
        for group in groups
        if isinstance(group, dict) and len(group.get("item_ids") or []) > 1
    ]
    return round(len(duplicate_groups) / len(groups), 4)


def deduplication_result_for_measurement(
    *,
    productized_run: Any | None = None,
    board_run_result: Any = None,
) -> dict[str, Any]:
    formal = _deduplication_result_from_productized_run(productized_run)
    if formal is not None:
        return formal
    return _legacy_deduplication_result_from_board_result(board_run_result) or {}


def deduplication_result_from_productized_run(productized_run: Any | None) -> dict[str, Any]:
    value = _deduplication_result_from_productized_run(productized_run)
    return value or {}


def _deduplication_result_from_productized_run(productized_run: Any | None) -> dict[str, Any] | None:
    if productized_run is None:
        return None
    if isinstance(productized_run, dict):
        value = productized_run.get("deduplication_result")
    else:
        value = getattr(productized_run, "deduplication_result", None)
    return dict(value) if isinstance(value, dict) else None


def _legacy_deduplication_result_from_board_result(result: Any) -> dict[str, Any] | None:
    metadata = getattr(result, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return None
    productized_state = metadata.get("productized_run_state")
    if (
        isinstance(productized_state, dict)
        and isinstance(productized_state.get("deduplication_result"), dict)
    ):
        return dict(productized_state["deduplication_result"])
    dedupe = metadata.get("deduplication_result")
    return dict(dedupe) if isinstance(dedupe, dict) else None


__all__ = [
    "ProductizedImprovementMeasurementInput",
    "ProductizedImprovementMeasurementService",
    "ProductizedImprovementMeasurementSnapshot",
    "deduplication_result_from_productized_run",
    "deduplication_result_for_measurement",
    "duplicate_rate",
    "duplicate_rate_from_deduplication_result",
    "evidence_coverage",
    "measurement_snapshot",
]
