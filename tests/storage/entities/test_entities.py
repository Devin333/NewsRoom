import pytest

from storage.entities import LocalJsonTrackedEntityStore, TrackedEntity


def test_tracked_entity_round_trips_and_deduplicates_aliases() -> None:
    entity = TrackedEntity(
        entity_id="company:openai",
        name="OpenAI",
        aliases=["OpenAI", "ChatGPT", "chatgpt"],
        kind="company",
        metadata={"ticker": "private"},
    )
    restored = TrackedEntity.from_dict(entity.to_dict())

    assert restored.entity_id == "company:openai"
    assert restored.kind.value == "company"
    assert restored.aliases == ["ChatGPT"]
    assert restored.metadata == {"ticker": "private"}


def test_tracked_entity_rejects_secret_metadata() -> None:
    with pytest.raises(ValueError, match="secret-like key"):
        TrackedEntity(
            entity_id="company:openai",
            name="OpenAI",
            metadata={"api_key": "hidden"},
        )


def test_local_json_tracked_entity_store_persists_records(tmp_path) -> None:
    store_path = tmp_path / "entities.json"
    store = LocalJsonTrackedEntityStore(store_path)
    entity = TrackedEntity(entity_id="company:openai", name="OpenAI", aliases=["ChatGPT"])

    store.upsert_entity(entity)
    restored = LocalJsonTrackedEntityStore(store_path).get_entity("company:openai")
    listed = LocalJsonTrackedEntityStore(store_path).list_entities(kind="company")

    assert restored.name == "OpenAI"
    assert listed == [restored]
    assert store_path.exists()


def test_local_json_tracked_entity_store_enable_disable_delete(tmp_path) -> None:
    store = LocalJsonTrackedEntityStore(tmp_path / "entities.json")
    store.upsert_entity(TrackedEntity(entity_id="company:openai", name="OpenAI"))

    disabled = store.set_enabled("company:openai", enabled=False)
    enabled = store.set_enabled("company:openai", enabled=True)
    deleted = store.delete_entity("company:openai")

    assert disabled.enabled is False
    assert enabled.enabled is True
    assert deleted is True
