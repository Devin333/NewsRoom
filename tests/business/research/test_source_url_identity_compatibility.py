from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from business.foundation.primitives.source_ref import source_url_read_aliases
from business.research.code_repository.models import CodeRepositoryProfile
from business.research.domain.paper import ResearchPaper
from business.research.paper_card.models import ResearchPaperCard


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PERSISTENCE_FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "research_source_url_persistence"


@dataclass(frozen=True)
class ResearchUrlFixture:
    name: str
    path: Path
    model_type: type[Any]
    url_field: str
    golden_url: str
    rollback_aliases: tuple[str, ...]
    new_url: str


RESEARCH_URL_FIXTURES = (
    ResearchUrlFixture(
        name="paper",
        path=PERSISTENCE_FIXTURE_ROOT / "legacy_research_paper.json",
        model_type=ResearchPaper,
        url_field="source_url",
        golden_url="https://example.com/research/paper?topic=AI",
        rollback_aliases=(
            "https://example.com/research/paper/?topic=AI",
            "https://example.com/research/paper?topic=AI",
        ),
        new_url="https://EXAMPLE.com/research/paper/?UTM_Source=write&topic=AI#fragment",
    ),
    ResearchUrlFixture(
        name="repository",
        path=PERSISTENCE_FIXTURE_ROOT / "legacy_repository_profile.json",
        model_type=CodeRepositoryProfile,
        url_field="repo_url",
        golden_url="https://github.com/NewsRoom/Runtime",
        rollback_aliases=(
            "https://github.com/NewsRoom/Runtime/",
            "https://github.com/NewsRoom/Runtime",
        ),
        new_url="https://GITHUB.com/NewsRoom/Runtime/",
    ),
    ResearchUrlFixture(
        name="paper-card",
        path=PERSISTENCE_FIXTURE_ROOT / "legacy_paper_card.json",
        model_type=ResearchPaperCard,
        url_field="source_url",
        golden_url="https://example.com/research/paper?Topic=AI",
        rollback_aliases=(
            "https://example.com/research/paper?Topic=AI&UTM_Source=legacy",
            "https://example.com/research/paper?Topic=AI",
            "https://example.com/research/paper?topic=AI",
        ),
        new_url="https://EXAMPLE.com/research/paper/?UTM_Source=write&Topic=AI#fragment",
    ),
)


def test_research_source_url_payloads_accept_historical_forms_without_mutating_payloads() -> None:
    historical_url = "https://Example.com/paper/?topic=AI"
    expected_url = "https://example.com/paper?topic=AI"
    paper_payload = {
        "paper_id": "paper-1",
        "title": "Paper",
        "source_url": historical_url,
    }
    repository_payload = {
        "repo_url": "https://GitHub.com/NewsRoom/Runtime/",
        "owner": "NewsRoom",
        "name": "Runtime",
    }
    card_payload = {
        "paper_id": "paper-1",
        "title": "Paper",
        "source_url": historical_url,
    }
    persisted_payloads = [paper_payload, repository_payload, card_payload]
    snapshots = deepcopy(persisted_payloads)

    paper = ResearchPaper.model_validate(paper_payload)
    repository = CodeRepositoryProfile.model_validate(repository_payload)
    card = ResearchPaperCard.model_validate(card_payload)

    assert paper.source_url == expected_url
    assert repository.repo_url == "https://github.com/NewsRoom/Runtime"
    assert card.source_url == expected_url
    assert historical_url == source_url_read_aliases(historical_url)[0]
    assert expected_url in source_url_read_aliases(historical_url)
    assert persisted_payloads == snapshots


@pytest.mark.parametrize(
    "case",
    RESEARCH_URL_FIXTURES,
    ids=[case.name for case in RESEARCH_URL_FIXTURES],
)
def test_persisted_research_url_fixture_reads_aliases_exact_first_without_rewrite(
    case: ResearchUrlFixture,
) -> None:
    """Historical Research JSON is read in memory; the fixture remains byte-for-byte stable."""

    before = case.path.read_bytes()
    payload = json.loads(before)
    snapshot = deepcopy(payload)
    stored_url = payload[case.url_field]

    model = case.model_type.model_validate(payload)
    aliases = source_url_read_aliases(stored_url, raw_url=case.golden_url)

    assert aliases[0] == stored_url
    assert case.golden_url in aliases
    assert set(case.rollback_aliases).issubset(set(aliases))
    assert getattr(model, case.url_field) == case.golden_url
    assert payload == snapshot
    assert case.path.read_bytes() == before
    assert model.metadata["canonical_url_hash"] == payload["metadata"]["canonical_url_hash"]
    assert model.metadata["artifact_ref"] == payload["metadata"]["artifact_ref"]


@pytest.mark.parametrize(
    "case",
    RESEARCH_URL_FIXTURES,
    ids=[case.name for case in RESEARCH_URL_FIXTURES],
)
def test_new_research_json_write_uses_one_golden_url_without_dual_write(
    case: ResearchUrlFixture,
    tmp_path: Path,
) -> None:
    """A new serialized payload emits the golden identity and no compatibility aliases."""

    original_bytes = case.path.read_bytes()
    payload = json.loads(original_bytes)
    payload[case.url_field] = case.new_url
    model = case.model_type.model_validate(payload)
    serialized = model.to_dict()

    assert serialized[case.url_field] == case.golden_url
    assert _compatibility_alias_keys(serialized) == []

    output_path = tmp_path / f"{case.name}.json"
    output_path.write_text(json.dumps(serialized, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    output_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert output_payload[case.url_field] == case.golden_url
    assert case.path.read_bytes() == original_bytes


@pytest.mark.parametrize(
    "case",
    RESEARCH_URL_FIXTURES,
    ids=[case.name for case in RESEARCH_URL_FIXTURES],
)
def test_rollback_read_keeps_historical_research_url_and_identity_fields(
    case: ResearchUrlFixture,
    tmp_path: Path,
) -> None:
    """A rollback payload can remain on the old URL while the current reader sees the golden alias."""

    rollback_path = tmp_path / f"{case.name}-rollback.json"
    original_bytes = case.path.read_bytes()
    rollback_path.write_bytes(original_bytes)
    rollback_before = rollback_path.read_bytes()
    rollback_payload = json.loads(rollback_before)
    restored = case.model_type.model_validate(rollback_payload)
    aliases = source_url_read_aliases(rollback_payload[case.url_field])

    assert restored.metadata["canonical_url_hash"] == rollback_payload["metadata"]["canonical_url_hash"]
    assert restored.metadata["artifact_ref"] == rollback_payload["metadata"]["artifact_ref"]
    assert rollback_payload[case.url_field] == case.rollback_aliases[0]
    assert case.golden_url in aliases
    assert rollback_path.read_bytes() == rollback_before


def _compatibility_alias_keys(payload: object, prefix: str = "") -> list[str]:
    """Find accidental dual-write fields without treating normal URL fields as aliases."""

    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            lowered = str(key).casefold()
            if "alias" in lowered or lowered in {"legacy_url", "historical_url"}:
                found.append(path)
            found.extend(_compatibility_alias_keys(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_compatibility_alias_keys(value, f"{prefix}[{index}]"))
    return found
