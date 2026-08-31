from __future__ import annotations

import json

from backend.research.domain import ResearchPaper
from infrastructure.research.catalog_store import (
    CATALOG_STORE_SCHEMA_VERSION,
    FilesystemResearchCatalogStore,
    FilesystemResearchEventSink,
    ResearchCatalogArtifactNotFoundError,
    ResearchCatalogArtifactScopeError,
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


def test_catalog_artifact_read_requires_scope_and_commit_marker(tmp_path) -> None:
    store = FilesystemResearchCatalogStore(tmp_path)
    ref = store.publish(
        artifact_type="research-document",
        payload={"text": "paper body"},
        metadata={
            "paper_id": "paper-1",
            "actor_scope": {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
                "memory_namespace": "research:tenant:tenant-a:user:user-a",
            },
        },
    )

    summary = store.read(
        ref,
        actor_scope={
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "memory_namespace": "research:tenant:tenant-a:user:user-a",
        },
    )
    assert summary["artifactRef"] == ref
    assert "payload" not in summary
    assert store.read(
        ref,
        actor_scope={
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "memory_namespace": "research:tenant:tenant-a:user:user-a",
        },
        include_payload=True,
    )["payload"] == {"text": "paper body"}

    try:
        store.read(ref, actor_scope={"tenant_id": "tenant-b"})
    except ResearchCatalogArtifactScopeError:
        pass
    else:
        raise AssertionError("cross-tenant artifact read must be denied")

    try:
        store.read("artifact://research/research-document/" + "0" * 64, actor_scope={"tenant_id": "tenant-a"})
    except ResearchCatalogArtifactNotFoundError:
        pass
    else:
        raise AssertionError("unknown artifact must be hidden")


def test_research_event_sink_assigns_sequences_and_scans_incomplete_runs(tmp_path) -> None:
    sink = FilesystemResearchEventSink(tmp_path)
    scope = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "memory_namespace": "research:tenant:tenant-a:user:user-a",
    }
    sink.create_run_intent("run-1", request_fingerprint="fp", actor_scope=scope)
    sink.append("run-1", {"event_id": "run-1:e1", "event_type": "research_parse_phase", "actor_scope": scope})
    sink.append("run-1", {"event_id": "run-1:e2", "event_type": "research_parse_phase", "actor_scope": scope})

    history = sink.read_history("run-1", actor_scope=scope)
    assert [item["sequence"] for item in history] == [1, 2]
    assert sink.scan_incomplete_runs()[0]["run_id"] == "run-1"

    sink.finalize("run-1", {"status": "parsed", "actor_scope": scope})
    assert sink.scan_incomplete_runs() == ()
