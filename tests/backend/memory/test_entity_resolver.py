from backend.memory.entity_resolver import EntityResolver
from backend.memory.intelligence_models import EvidenceMemory, IntelligenceMemoryBundle


def test_entity_resolver_merges_aliases() -> None:
    resolver = EntityResolver(alias_map={"open ai": "OpenAI", "openai": "OpenAI"})

    result = resolver.resolve_texts(
        [
            "Open AI released a new model.",
            "OpenAI announced updates.",
        ]
    )

    names = [entity.canonical_name for entity in result.entities]
    assert names.count("OpenAI") == 1
    assert result.aliases_used


def test_entity_resolver_extracts_topic_entity() -> None:
    result = EntityResolver().resolve_bundle(IntelligenceMemoryBundle(run_id="run-1", topic="AI policy"))

    assert result.entities[0].entity_type == "topic"
    assert result.entities[0].canonical_name == "AI policy"


def test_entity_resolver_extracts_metadata_entities() -> None:
    bundle = IntelligenceMemoryBundle(
        run_id="run-1",
        evidence=[
            EvidenceMemory(
                evidence_id="ev-1",
                run_id="run-1",
                title="Repo update",
                summary="Paper update",
                source_urls=[],
                source_item_ids=[],
                source_name="Example Source",
                metadata={"github_repo": "openai/newsroom", "arxiv_id": "2401.00001"},
            )
        ],
    )

    result = EntityResolver().resolve_bundle(bundle)

    assert {"source", "repository", "paper"} <= {entity.entity_type for entity in result.entities}
