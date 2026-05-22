from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_connector_bundle import (
    DailySourceConnectorBundle,
)
from business.boards.cross_board.workflows.daily_intelligence.source_connector_factory import (
    build_daily_source_connector_bundle,
)


def test_source_connector_factory_builds_bundle_with_defaults() -> None:
    bundle = build_daily_source_connector_bundle()

    assert isinstance(bundle, DailySourceConnectorBundle)
    assert bundle.feed_connector is not None
    assert bundle.medium_connector is not None


def test_source_connector_factory_allows_explicit_connector_override() -> None:
    feed_connector = object()

    bundle = build_daily_source_connector_bundle(feed_connector=feed_connector)

    assert bundle.feed_connector is feed_connector
