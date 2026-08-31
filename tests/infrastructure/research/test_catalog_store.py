from __future__ import annotations

import json

from backend.research.domain import ResearchPaper
from infrastructure.research.catalog_store import (
    CATALOG_STORE_SCHEMA_VERSION,
    FilesystemResearchCatalogStore,
    _checksum,
)


def test_catalog_store_migrates_legacy_state_and_persists_schema(tmp_path) -> None:
    store = FilesystemResearchCatalogStore(tmp_path)
    store.save(
        ResearchPaper(
            paper_id="paper-1",
            title="A paper",
            metadata={"actor_scope": {"tenant_id": "tenant-a"}},
        )
    )

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    payload.pop("sota_claims", None)
    unsigned = {key: value for key, value in payload.items() if key != "checksum"}
    payload["checksum"] = _checksum(unsigned)
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    assert store.get_paper("paper-1", actor_scope={"tenant_id": "tenant-a"}) is not None
    migrated = json.loads(store.path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == CATALOG_STORE_SCHEMA_VERSION
    assert migrated["sota_claims"] == {}
    assert migrated["checksum"] == _checksum({key: value for key, value in migrated.items() if key != "checksum"})


def test_catalog_store_keeps_actor_scopes_isolated(tmp_path) -> None:
    store = FilesystemResearchCatalogStore(tmp_path)
    store.save(ResearchPaper(paper_id="paper-a", title="A", metadata={"actor_scope": {"tenant_id": "a"}}))
    store.save(ResearchPaper(paper_id="paper-b", title="B", metadata={"actor_scope": {"tenant_id": "b"}}))

    assert store.get_paper("paper-a", actor_scope={"tenant_id": "b"}) is None
    assert store.get_paper("paper-a", actor_scope={"tenant_id": "a"}) is not None
