from __future__ import annotations

from collections import Counter
from datetime import datetime

from framework.shared.time import parse_datetime, utc_now
from business.memory.models import BusinessMemoryHit


def estimate_topic_momentum(
    hits: list[BusinessMemoryHit],
    *,
    now: datetime | None = None,
) -> float:
    if not hits:
        return 0.0
    actual_now = parse_datetime(now) or utc_now()
    topics = Counter(hit.topic for hit in hits if hit.topic)
    sources = {hit.source_name for hit in hits if hit.source_name}
    recent = 0
    for hit in hits:
        published = parse_datetime(hit.published_at)
        if published is not None and (actual_now - published).days <= 14:
            recent += 1
    topic_strength = max(topics.values() or [0]) / max(1, len(hits))
    source_strength = min(1.0, len(sources) / 3.0)
    recency_strength = min(1.0, recent / max(1, len(hits)))
    return _clamp(topic_strength * 0.45 + source_strength * 0.25 + recency_strength * 0.30)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
