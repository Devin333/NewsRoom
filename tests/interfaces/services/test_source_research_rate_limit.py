from __future__ import annotations

import pytest

from business.foundation.models.source import SourceFetchPolicy as BusinessSourceFetchPolicy
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health import BasicSourceHealthManager
from infrastructure.external.sources import SourceRateLimitExceededError
from infrastructure.external.sources.fetch_policy import SourceFetchPolicy
from interfaces.services.source_runtime import build_source_runtime_composition


ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2607.00001v1</id>
    <updated>2026-07-19T00:00:00Z</updated>
    <published>2026-07-19T00:00:00Z</published>
    <title>Shared Source quota</title>
    <summary>Source metadata consumes the provider reservation.</summary>
    <author><name>Example Author</name></author>
  </entry>
</feed>
"""


@pytest.mark.parametrize("method_name", ["fetch_source_package", "fetch_pdf_package"])
def test_research_arxiv_fetch_uses_shared_ledger_and_denies_before_network(
    monkeypatch,
    method_name: str,
) -> None:
    composition = build_source_runtime_composition(
        source_registry=SourceRegistry([]),
        fetch_policy=BusinessSourceFetchPolicy(
            rate_limit_per_domain_per_minute=1,
        ),
        health_manager=BasicSourceHealthManager(),
        fetch_text=lambda _url: ARXIV_XML,
    )
    source_result = composition.source_service.fetch_arxiv(
        query="id:2607.00001",
        limit=1,
    )
    assert len(source_result.items) == 1
    assert source_result.errors == []

    network_calls: list[str] = []
    monkeypatch.setattr(
        "infrastructure.external.sources.arxiv.ensure_robots_allowed",
        lambda *_args, **_kwargs: network_calls.append("robots"),
    )
    monkeypatch.setattr(
        "infrastructure.external.sources.arxiv.open_request_with_fetch_policy",
        lambda *_args, **_kwargs: network_calls.append("fetch"),
    )

    with pytest.raises(SourceRateLimitExceededError) as captured:
        getattr(composition.research_arxiv_connector, method_name)("2607.00001")

    assert captured.value.domain == "arxiv.org"
    assert captured.value.limit_per_minute == 1
    assert captured.value.retry_after_seconds is not None
    assert network_calls == []


def test_research_arxiv_policy_cannot_split_the_shared_domain_quota() -> None:
    composition = build_source_runtime_composition(
        source_registry=SourceRegistry([]),
        fetch_policy=BusinessSourceFetchPolicy(
            rate_limit_per_domain_per_minute=2,
        ),
        research_arxiv_fetch_policy=SourceFetchPolicy(
            rate_limit_per_domain_per_minute=99,
            timeout_seconds=73,
            retry_times=4,
        ),
    )

    policy = composition.research_arxiv_connector.fetch_policy
    assert policy.rate_limit_per_domain_per_minute == 2
    assert policy.timeout_seconds == 73
    assert policy.retry_times == 4
