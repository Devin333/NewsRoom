from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from infrastructure.external.sources.arxiv import ArxivConnector
from infrastructure.external.sources.community import LobstersConnector
from infrastructure.external.sources.feed import FeedConnector
from infrastructure.external.sources.fetch_policy import DomainRateLimiter, SourceFetchPolicy
from infrastructure.external.sources.github import GithubConnector
from infrastructure.external.sources.hackernews import HackerNewsConnector
from infrastructure.external.sources.html import HtmlConnector
from infrastructure.external.sources.manual import ManualConnector
from infrastructure.external.sources.models import SourceDefinition, SourceType
from infrastructure.external.sources.reddit import RedditConnector


def _timeout(_: str) -> str:
    raise TimeoutError("timed out")


def _assert_serialized_error_envelope(
    error: Any,
    *,
    source: SourceDefinition,
    error_type: str,
    error_message: str,
    retryable: bool,
    metadata: dict[str, Any],
) -> None:
    payload = error.to_dict()

    assert set(payload) == {
        "source_id",
        "source_name",
        "error_type",
        "error_message",
        "url",
        "retryable",
        "request_ref",
        "response_ref",
        "occurred_at",
        "metadata",
    }
    assert payload == {
        "source_id": source.source_id,
        "source_name": source.name,
        "error_type": error_type,
        "error_message": error_message,
        "url": source.url,
        "retryable": retryable,
        "request_ref": None,
        "response_ref": None,
        "occurred_at": error.occurred_at.isoformat().replace("+00:00", "Z"),
        "metadata": metadata,
    }
    parsed_occurred_at = datetime.fromisoformat(
        payload["occurred_at"].replace("Z", "+00:00")
    )
    assert parsed_occurred_at.tzinfo is not None


@pytest.mark.parametrize(
    ("connector_type", "source_type", "url", "fetch_kwargs"),
    [
        (
            ArxivConnector,
            SourceType.ARXIV,
            "https://export.arxiv.org/api/query",
            {"query": "cat:cs.AI"},
        ),
        (LobstersConnector, SourceType.LOBSTERS, "https://lobste.rs", {}),
        (FeedConnector, SourceType.RSS, "https://example.com/feed.xml", {}),
        (
            GithubConnector,
            SourceType.GITHUB,
            "https://api.github.com",
            {"repository": "owner/repo"},
        ),
        (
            HackerNewsConnector,
            SourceType.HACKERNEWS,
            "https://hacker-news.firebaseio.com/v0",
            {"story_list": "topstories"},
        ),
        (HtmlConnector, SourceType.HTML, "https://example.com/article", {}),
        (
            RedditConnector,
            SourceType.REDDIT,
            "https://www.reddit.com",
            {"subreddit": "python"},
        ),
    ],
)
def test_network_connectors_emit_the_shared_exception_envelope(
    connector_type: type,
    source_type: SourceType,
    url: str,
    fetch_kwargs: dict[str, Any],
) -> None:
    source = SourceDefinition(
        source_id=f"{source_type.value}-source",
        name=f"{source_type.value} source",
        source_type=source_type,
        url=url,
    )
    connector = connector_type(
        fetch_text=_timeout,
        fetch_policy=SourceFetchPolicy(retry_times=0),
    )

    items, errors = connector.fetch(source, limit=1, **fetch_kwargs)

    assert items == []
    assert len(errors) == 1
    error = errors[0]
    assert error.error_type == "fetch_timeout"
    assert error.retryable is True
    assert error.metadata["phase"] == "fetch"
    assert error.metadata["original_exception_type"] == "TimeoutError"
    assert error.metadata["retryable"] is True
    assert error.metadata["source_health_affecting"] is True
    assert error.metadata["workflow_blocking"] is False
    assert error.metadata["operator_action_required"] is False
    assert error.metadata["attempts"] == 1
    _assert_serialized_error_envelope(
        error,
        source=source,
        error_type="fetch_timeout",
        error_message="timed out",
        retryable=True,
        metadata={
            "phase": "fetch",
            "retryable": True,
            "source_health_affecting": True,
            "workflow_blocking": False,
            "operator_action_required": False,
            "original_exception_type": "TimeoutError",
            "attempts": 1,
        },
    )


def test_manual_connector_emits_the_shared_parse_envelope() -> None:
    source = SourceDefinition(
        source_id="manual-source",
        name="Manual source",
        source_type=SourceType.MANUAL,
        url="manual://source",
    )

    items, errors = ManualConnector().fetch(source, records=["not-a-mapping"])  # type: ignore[list-item]

    assert items == []
    assert len(errors) == 1
    assert errors[0].error_type == "parse_error"
    assert errors[0].retryable is False
    assert errors[0].metadata["phase"] == "parse"
    assert errors[0].metadata["workflow_blocking"] is False
    _assert_serialized_error_envelope(
        errors[0],
        source=source,
        error_type="parse_error",
        error_message="manual source record must be an object",
        retryable=False,
        metadata={
            "phase": "parse",
            "retryable": False,
            "source_health_affecting": False,
            "workflow_blocking": False,
            "operator_action_required": False,
            "original_exception_type": "ValueError",
        },
    )


def test_rate_limited_connector_error_uses_the_shared_envelope() -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS source",
        source_type=SourceType.RSS,
        url="https://example.com/feed.xml",
    )
    ledger = DomainRateLimiter(now=lambda: datetime(2026, 7, 19, tzinfo=UTC))
    assert ledger.reserve(source.url, limit_per_minute=1).allowed is True
    fetch_calls = 0

    def fetch_text(_url: str) -> str:
        nonlocal fetch_calls
        fetch_calls += 1
        raise AssertionError("rate-limit denial must happen before fetch")

    items, errors = FeedConnector(
        fetch_text=fetch_text,
        fetch_policy=SourceFetchPolicy(
            rate_limit_per_domain_per_minute=1,
            retry_times=3,
        ),
        rate_limiter=ledger,
    ).fetch(source)

    assert items == []
    assert fetch_calls == 0
    assert len(errors) == 1
    _assert_serialized_error_envelope(
        errors[0],
        source=source,
        error_type="rate_limited",
        error_message="source fetch rate limit reached for domain: example.com",
        retryable=True,
        metadata={
            "phase": "fetch",
            "retryable": True,
            "source_health_affecting": False,
            "workflow_blocking": False,
            "operator_action_required": False,
            "domain": "example.com",
            "limit_per_minute": 1,
            "window_seconds": 60,
            "retry_after_seconds": 60,
        },
    )


@pytest.mark.parametrize(
    "module_name",
    [
        "arxiv.py",
        "community.py",
        "feed.py",
        "github.py",
        "hackernews.py",
        "html.py",
        "manual.py",
        "reddit.py",
    ],
)
def test_connectors_do_not_define_local_source_error_constructors(
    module_name: str,
) -> None:
    module_path = Path("infrastructure/external/sources") / module_name
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    local_helpers = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_source_error"
    ]
    direct_constructors = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SourceError"
    ]

    assert local_helpers == []
    assert direct_constructors == []


def test_shared_factory_is_the_only_infrastructure_source_error_constructor() -> None:
    source_root = Path("infrastructure/external/sources")
    allowed_constructor = source_root / "errors" / "factory.py"
    violations: list[str] = []

    for module_path in source_root.rglob("*.py"):
        if module_path == allowed_constructor:
            continue
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SourceError"
            for node in ast.walk(tree)
        ):
            violations.append(module_path.as_posix())

    assert violations == []
