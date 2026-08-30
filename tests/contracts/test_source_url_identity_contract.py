from __future__ import annotations

import pytest

from backend.foundation.primitives.source_ref import (
    SourceRef,
    canonicalize_url,
    source_url_read_aliases,
)
from backend.foundation.taxonomy import SourceType
from backend.layers.analysis.quality_records import (
    AnalysisEvidenceBundle,
    AnalysisEvidenceItem,
    citation_check,
)
from backend.layers.signal.tools import register_source_tools
from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from infrastructure.external.sources.html import HtmlConnector
from infrastructure.external.sources.models import SourceDefinition
from infrastructure.external.sources.url_utils import canonicalize_url as infrastructure_canonicalize_url
from tests.fixtures.source_url_identity import SOURCE_URL_GOLDEN_CASES, SOURCE_URL_MALFORMED_CASES


@pytest.mark.parametrize(
    ("_case", "url", "base_url", "expected"),
    SOURCE_URL_GOLDEN_CASES,
    ids=[case[0] for case in SOURCE_URL_GOLDEN_CASES],
)
def test_source_url_golden_contract_is_shared_by_business_and_infrastructure(
    _case: str,
    url: str,
    base_url: str | None,
    expected: str,
) -> None:
    assert canonicalize_url(url, base_url=base_url) == expected
    assert infrastructure_canonicalize_url(url, base_url=base_url) == expected


@pytest.mark.parametrize(
    ("_case", "url"),
    SOURCE_URL_MALFORMED_CASES,
    ids=[case[0] for case in SOURCE_URL_MALFORMED_CASES],
)
def test_source_url_golden_contract_rejects_malformed_absolute_urls(
    _case: str,
    url: str,
) -> None:
    with pytest.raises(ValueError, match="malformed Source URL"):
        canonicalize_url(url)
    with pytest.raises(ValueError, match="malformed Source URL"):
        infrastructure_canonicalize_url(url)


def test_source_ref_canonicalizes_before_building_default_identity() -> None:
    raw_url = "HTTPS://Example.com:443/post/?UTM_Source=x&Topic=AI#section"
    canonical_url = "https://example.com/post?Topic=AI"

    from_raw = SourceRef(
        source_name="Example",
        source_type=SourceType.RSS,
        url=raw_url,
    )
    from_canonical = SourceRef(
        source_name="Example",
        source_type=SourceType.RSS,
        source_url=canonical_url,
    )
    explicit = SourceRef(
        source_id="legacy-source-id",
        source_name="Example",
        source_type=SourceType.RSS,
        url=raw_url,
    )

    assert from_raw.url == canonical_url
    assert from_raw.source_url == canonical_url
    assert from_raw.source_id == from_canonical.source_id
    assert explicit.source_id == "legacy-source-id"
    assert explicit.url == canonical_url


def test_historical_source_url_aliases_are_exact_first_and_do_not_mutate_input() -> None:
    persisted = {
        "url": "https://example.com/News/?topic=AI",
        "source_id": "legacy-source-id",
        "canonical_url_hash": "legacy-hash",
        "request_ref": {"artifact_id": "request-1"},
    }
    snapshot = {
        **persisted,
        "request_ref": dict(persisted["request_ref"]),
    }

    aliases = source_url_read_aliases(
        persisted["url"],
        raw_url="HTTPS://Example.com/News/?Topic=AI&UTM_Source=x#section",
    )

    assert aliases[0] == persisted["url"]
    assert "https://example.com/News?Topic=AI" in aliases
    assert "https://example.com/News?topic=AI" in aliases
    assert "https://example.com/News?Topic=AI&UTM_Source=x" in aliases
    assert persisted == snapshot


def test_source_tool_and_html_connector_use_the_business_url_identity() -> None:
    raw_url = "HTTPS://Example.com/News/?UTM_Source=x&Topic=AI#section"
    expected = canonicalize_url(raw_url)
    registry = ToolRegistry()
    register_source_tools(registry)

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="source.normalize_url", arguments={"url": raw_url}),
        ToolPolicy(allowed_tools=["source.normalize_url"]),
    )
    source = SourceDefinition(
        source_id="html-source",
        name="HTML source",
        source_type="html",
        url="https://Example.com/base/index.html",
    )
    html = f"""<html><head><title>Identity</title><link rel="canonical" href="{raw_url}" /></head>
    <body><p>Canonical identity contract content.</p></body></html>"""
    items = HtmlConnector().parse(source, html)

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["canonical_url"] == expected
    assert items[0].url == expected
    assert items[0].metadata["canonical_url"] == expected


def test_analysis_quality_reader_matches_historical_source_url_aliases() -> None:
    bundle = AnalysisEvidenceBundle(
        bundle_id="bundle",
        items=[
            AnalysisEvidenceItem(
                evidence_id="ev-legacy",
                source_url="https://example.com/News/?topic=AI",
                title="Legacy source",
                summary="Legacy source summary",
                confidence=0.9,
                source_id="source",
            )
        ],
    )
    report = {
        "sections": [
            {
                "title": "Summary",
                "sources": ["https://example.com/News?Topic=AI"],
            }
        ]
    }

    result = citation_check(report, bundle)

    assert result.unknown_urls == []
    assert result.unsupported_urls == []
