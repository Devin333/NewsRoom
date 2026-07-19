from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any

from business.foundation.models.source import (
    SourceFetchPolicy as BusinessSourceFetchPolicy,
)
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_config import (
    build_default_source_fetch_policy,
    build_default_source_registry,
)
from business.layers.signal.source_health import BasicSourceHealthManager, SourceHealthStore
from business.layers.signal.source_router import SourceConnectorRouter
from business.layers.signal.source_tool_runtime import SourceRateLimitDecision
from infrastructure.external.sources import (
    ArxivSourceConnector,
    DevToConnector,
    DomainRateLimiter,
    FeedConnector,
    HackerNewsConnector,
    HtmlConnector,
    LobstersConnector,
    ManualConnector,
    MediumConnector,
    RedditConnector,
    StackOverflowConnector,
    default_arxiv_connector,
    default_arxiv_source_connector,
    default_github_connector,
)
from infrastructure.external.sources.fetch_policy import (
    SourceFetchPolicy as InfraSourceFetchPolicy,
)
from infrastructure.storage.source_health import source_health_store_from_env
from interfaces.services.source_mapping import (
    to_business_fetch_policy,
    to_infrastructure_fetch_policy,
)
from interfaces.services.source_service import SourceApplicationService
from interfaces.services.source_tool_runtime import InfrastructureSourceToolRuntime


class SourceRateLimiterAdapter:
    """Expose the infrastructure ledger through the business limiter port."""

    def __init__(self, ledger: DomainRateLimiter) -> None:
        self._ledger = ledger

    @property
    def ledger(self) -> DomainRateLimiter:
        return self._ledger

    def reserve(
        self,
        url: str,
        *,
        limit_per_minute: int | None,
    ) -> SourceRateLimitDecision:
        decision = self._ledger.reserve(
            url,
            limit_per_minute=limit_per_minute,
        )
        return SourceRateLimitDecision(
            allowed=decision.allowed,
            domain=decision.domain,
            limit_per_minute=decision.limit_per_minute,
            window_seconds=decision.window_seconds,
            retry_after_seconds=decision.retry_after_seconds,
        )


@dataclass(frozen=True)
class SourceRuntimeComposition:
    source_registry: SourceRegistry
    business_fetch_policy: BusinessSourceFetchPolicy
    fetch_policy: InfraSourceFetchPolicy
    reservation_ledger: DomainRateLimiter
    rate_limiter: SourceRateLimiterAdapter
    health_manager: BasicSourceHealthManager
    source_router: SourceConnectorRouter
    source_service: SourceApplicationService
    source_tool_runtime: InfrastructureSourceToolRuntime
    research_arxiv_connector: Any

    def source_service_factory(self) -> SourceApplicationService:
        return self.source_service


class SourceRuntimeProvider:
    """Lazily create one explicit Source composition for an owning process root."""

    def __init__(
        self,
        factory: Callable[[], SourceRuntimeComposition] | None = None,
    ) -> None:
        self._factory = factory or build_source_runtime_composition
        self._composition: SourceRuntimeComposition | None = None
        self._lock = Lock()

    def get(self) -> SourceRuntimeComposition:
        composition = self._composition
        if composition is not None:
            return composition
        with self._lock:
            composition = self._composition
            if composition is None:
                composition = self._factory()
                self._composition = composition
            return composition

    def source_service_factory(self) -> SourceApplicationService:
        return self.get().source_service


def build_source_runtime_composition(
    *,
    source_registry: SourceRegistry | None = None,
    source_config_path: str | Path | None = None,
    fetch_policy: BusinessSourceFetchPolicy | InfraSourceFetchPolicy | None = None,
    research_arxiv_fetch_policy: InfraSourceFetchPolicy | None = None,
    reservation_ledger: DomainRateLimiter | None = None,
    source_health_store: SourceHealthStore | None = None,
    health_manager: BasicSourceHealthManager | None = None,
    health_probe_fetcher: Callable[..., Any] | None = None,
    fetch_text: Callable[[str], str] | None = None,
    request_id_factory: Callable[[], str] | None = None,
) -> SourceRuntimeComposition:
    registry = source_registry or build_default_source_registry(
        source_config_path=source_config_path
    )
    business_policy = to_business_fetch_policy(
        fetch_policy
        or build_default_source_fetch_policy(source_config_path=source_config_path)
    )
    infra_policy = to_infrastructure_fetch_policy(fetch_policy or business_policy)
    ledger = reservation_ledger or DomainRateLimiter()
    limiter_adapter = SourceRateLimiterAdapter(ledger)
    health_store = source_health_store
    if health_store is None and health_manager is None:
        health_store = source_health_store_from_env()
    actual_health_manager = health_manager or BasicSourceHealthManager(
        health_store=health_store
    )

    feed_connector = FeedConnector(
        fetch_text=fetch_text,
        fetch_policy=infra_policy,
        rate_limiter=ledger,
    )
    arxiv_connector = default_arxiv_connector(
        fetch_text=fetch_text,
        fetch_policy=infra_policy,
        rate_limiter=ledger,
    )
    github_connector = default_github_connector(
        fetch_text=fetch_text,
        fetch_policy=infra_policy,
        rate_limiter=ledger,
    )
    source_router = SourceConnectorRouter(
        feed_connector=feed_connector,
        arxiv_connector=arxiv_connector,
        github_connector=github_connector,
        hackernews_connector=HackerNewsConnector(
            fetch_text=fetch_text,
            fetch_policy=infra_policy,
            rate_limiter=ledger,
        ),
        reddit_connector=RedditConnector(
            fetch_text=fetch_text,
            fetch_policy=infra_policy,
            rate_limiter=ledger,
        ),
        lobsters_connector=LobstersConnector(
            fetch_text=fetch_text,
            fetch_policy=infra_policy,
            rate_limiter=ledger,
        ),
        stackoverflow_connector=StackOverflowConnector(
            fetch_text=fetch_text,
            fetch_policy=infra_policy,
            rate_limiter=ledger,
        ),
        devto_connector=DevToConnector(
            fetch_text=fetch_text,
            fetch_policy=infra_policy,
            rate_limiter=ledger,
        ),
        medium_connector=MediumConnector(
            feed_connector=FeedConnector(
                fetch_text=fetch_text,
                fetch_policy=infra_policy,
                rate_limiter=ledger,
            )
        ),
        html_connector=HtmlConnector(
            fetch_text=fetch_text,
            fetch_policy=infra_policy,
            rate_limiter=ledger,
        ),
        manual_connector=ManualConnector(),
        fetch_policy=infra_policy,
        rate_limiter=ledger,
    )
    source_tool_runtime = InfrastructureSourceToolRuntime(
        fetch_text=fetch_text,
        rate_limiter=ledger,
    )
    source_service = SourceApplicationService(
        source_registry=registry,
        health_manager=actual_health_manager,
        source_health_store=health_store,
        health_probe_fetcher=health_probe_fetcher,
        fetch_policy=infra_policy,
        rate_limiter=limiter_adapter,
        arxiv_connector=arxiv_connector,
        github_connector=github_connector,
        source_router=source_router,
        request_id_factory=request_id_factory,
    )
    research_policy = replace(
        research_arxiv_fetch_policy or ArxivSourceConnector.default_fetch_policy(),
        rate_limit_per_domain_per_minute=(
            infra_policy.rate_limit_per_domain_per_minute
        ),
    )
    return SourceRuntimeComposition(
        source_registry=registry,
        business_fetch_policy=business_policy,
        fetch_policy=infra_policy,
        reservation_ledger=ledger,
        rate_limiter=limiter_adapter,
        health_manager=actual_health_manager,
        source_router=source_router,
        source_service=source_service,
        source_tool_runtime=source_tool_runtime,
        research_arxiv_connector=default_arxiv_source_connector(
            fetch_policy=research_policy,
            rate_limiter=ledger,
        ),
    )
__all__ = [
    "SourceRateLimiterAdapter",
    "SourceRuntimeComposition",
    "SourceRuntimeProvider",
    "build_source_runtime_composition",
]
