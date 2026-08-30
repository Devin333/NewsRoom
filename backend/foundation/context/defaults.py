from __future__ import annotations

from datetime import datetime, timedelta, timezone as _tz

from backend.foundation.primitives import TimeWindow, ensure_utc


UTC = _tz.utc


def default_time_window(days: int = 7, *, reference_time: datetime | None = None) -> TimeWindow:
    anchor = ensure_utc(reference_time or datetime.now(UTC)) or datetime.now(UTC)
    return TimeWindow(
        start_at=anchor - timedelta(days=days),
        end_at=anchor,
        label=f"last_{days}_days",
    )


__all__ = ["default_time_window"]
