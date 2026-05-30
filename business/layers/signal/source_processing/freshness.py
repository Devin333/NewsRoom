from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc

from business.foundation.models.source import RankedSourceItem, SourceFreshnessReport


FRESHNESS_BUCKETS = (
    "0_1_days",
    "1_7_days",
    "7_30_days",
    "over_30_days",
    "missing_published_at",
)
STALE_AFTER_DAYS = 30.0


def build_source_freshness_report(
    ranked_items: list[RankedSourceItem],
    *,
    now: datetime | None = None,
) -> SourceFreshnessReport:
    current_time = _as_utc(now or datetime.now(UTC))
    buckets = {bucket: 0 for bucket in FRESHNESS_BUCKETS}
    rows: list[dict[str, object]] = []

    for ranked in ranked_items:
        item = ranked.item
        timestamp = item.published_at or item.fetched_at
        timestamp_basis = "published_at" if item.published_at is not None else "fetched_at"
        age_days = max(0.0, (_as_utc(current_time) - _as_utc(timestamp)).total_seconds() / 86400)
        bucket = "missing_published_at" if item.published_at is None else _freshness_bucket(age_days)
        buckets[bucket] += 1
        future_timestamp_detected = bool(
            isinstance(item.metadata.get("time_normalization"), dict)
            and item.metadata["time_normalization"].get("future_timestamp_detected") is True
        )
        rows.append(
            {
                "ranked_item_id": ranked.ranked_item_id,
                "normalized_item_id": item.normalized_item_id,
                "source_item_id": item.source_item_id,
                "source_id": item.source_id,
                "canonical_url": item.canonical_url,
                "timestamp_basis": timestamp_basis,
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "age_days": round(age_days, 4),
                "freshness_bucket": bucket,
                "stale": age_days > STALE_AFTER_DAYS,
                "future_timestamp_detected": future_timestamp_detected,
            }
        )

    stale_count = sum(1 for row in rows if row["stale"])
    missing_count = buckets["missing_published_at"]
    future_count = sum(1 for row in rows if row["future_timestamp_detected"])
    status = _freshness_status(
        ranked_count=len(ranked_items),
        stale_count=stale_count,
        missing_count=missing_count,
        future_count=future_count,
    )
    return SourceFreshnessReport(
        freshness_status=status,
        ranked_item_count=len(ranked_items),
        fresh_item_count=len(ranked_items) - stale_count,
        stale_item_count=stale_count,
        missing_published_at_count=missing_count,
        future_timestamp_count=future_count,
        buckets=buckets,
        rows=rows,
    )


def _freshness_bucket(age_days: float) -> str:
    if age_days <= 1:
        return "0_1_days"
    if age_days <= 7:
        return "1_7_days"
    if age_days <= 30:
        return "7_30_days"
    return "over_30_days"


def _freshness_status(
    *,
    ranked_count: int,
    stale_count: int,
    missing_count: int,
    future_count: int,
) -> str:
    if ranked_count == 0:
        return "empty"
    if stale_count == ranked_count:
        return "stale"
    if stale_count or missing_count or future_count:
        return "mixed"
    return "fresh"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
