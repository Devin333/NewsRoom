from __future__ import annotations

from datetime import UTC, datetime, timezone, timedelta

from framework.shared import duration_ms, ensure_utc, format_datetime, parse_datetime, utc_now


def test_utc_now_returns_aware_utc_datetime() -> None:
    assert utc_now().tzinfo == UTC


def test_ensure_utc_treats_naive_datetime_as_utc() -> None:
    value = datetime(2026, 5, 20, 1, 2, 3)

    assert ensure_utc(value) == datetime(2026, 5, 20, 1, 2, 3, tzinfo=UTC)


def test_ensure_utc_converts_aware_datetime() -> None:
    value = datetime(2026, 5, 20, 9, 2, 3, tzinfo=timezone(timedelta(hours=8)))

    assert ensure_utc(value) == datetime(2026, 5, 20, 1, 2, 3, tzinfo=UTC)


def test_parse_and_format_datetime_round_trip_z_suffix() -> None:
    parsed = parse_datetime("2026-05-20T01:02:03Z")

    assert parsed == datetime(2026, 5, 20, 1, 2, 3, tzinfo=UTC)
    assert format_datetime(parsed) == "2026-05-20T01:02:03Z"
    assert parse_datetime(None) is None
    assert format_datetime(None) is None


def test_duration_ms_uses_utc_values() -> None:
    start = datetime(2026, 5, 20, 1, 2, 3, tzinfo=UTC)
    end = datetime(2026, 5, 20, 1, 2, 4, 250000, tzinfo=UTC)

    assert duration_ms(start, end) == 1250
