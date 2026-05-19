import pytest

from core.framework.memory import (
    InMemoryMemoryStore,
    MemoryKind,
    MemoryPolicy,
    MemoryRecord,
    MemoryScope,
    MemoryWriteMode,
    MemoryWriteRequest,
    MemoryWriter,
)


def test_memory_writer_appends_valid_records_and_reports_policy_skips() -> None:
    store = InMemoryMemoryStore()
    writer = MemoryWriter()
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW, MemoryScope.GLOBAL],
        allowed_kinds=[MemoryKind.SEMANTIC],
        allow_global_write=False,
    )

    result = writer.write(
        MemoryWriteRequest(
            records=[
                MemoryRecord(
                    memory_id="mem-valid",
                    content="valid workflow memory",
                    scope=MemoryScope.WORKFLOW,
                    kind=MemoryKind.SEMANTIC,
                    refs={"run_id": "run-1"},
                ),
                MemoryRecord(
                    memory_id="mem-global",
                    content="blocked global memory",
                    scope=MemoryScope.GLOBAL,
                    kind=MemoryKind.SEMANTIC,
                    refs={"run_id": "run-1"},
                ),
            ]
        ),
        store=store,
        policy=policy,
    )

    assert result.accepted_count == 2
    assert result.written_count == 1
    assert result.skipped_count == 1
    assert result.errors == ["global memory writes are disabled by policy"]
    assert store.get("mem-valid") is not None
    assert store.get("mem-global") is None


def test_memory_writer_upserts_existing_and_new_records() -> None:
    store = InMemoryMemoryStore(
        [
            MemoryRecord(
                memory_id="mem-existing",
                content="old content",
                scope=MemoryScope.WORKFLOW,
                kind=MemoryKind.SEMANTIC,
                refs={"run_id": "run-1"},
            )
        ]
    )
    writer = MemoryWriter()
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.SEMANTIC],
    )

    result = writer.write(
        MemoryWriteRequest(
            records=[
                MemoryRecord(
                    memory_id="mem-existing",
                    content="new content",
                    summary="updated",
                    scope=MemoryScope.WORKFLOW,
                    kind=MemoryKind.SEMANTIC,
                    refs={"run_id": "run-2"},
                    embedding=[0.2, 0.4],
                ),
                MemoryRecord(
                    memory_id="mem-new",
                    content="new memory",
                    scope=MemoryScope.WORKFLOW,
                    kind=MemoryKind.SEMANTIC,
                    refs={"run_id": "run-2"},
                ),
            ],
            mode=MemoryWriteMode.UPSERT,
        ),
        store=store,
        policy=policy,
    )

    assert result.written_count == 2
    assert result.memory_ids == ["mem-existing", "mem-new"]
    assert store.get("mem-existing").content == "new content"
    assert store.get("mem-existing").summary == "updated"
    assert store.get("mem-existing").embedding == [0.2, 0.4]
    assert store.get("mem-new").content == "new memory"


@pytest.mark.parametrize(
    "mode",
    [
        MemoryWriteMode.REPLACE,
    ],
)
def test_memory_writer_rejects_unimplemented_write_modes(mode: MemoryWriteMode) -> None:
    store = InMemoryMemoryStore()
    writer = MemoryWriter()
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.SEMANTIC],
    )

    with pytest.raises(NotImplementedError, match=mode.value):
        writer.write(
            MemoryWriteRequest(
                records=[
                    MemoryRecord(
                        memory_id="mem-merge",
                        content="merge memory",
                        scope=MemoryScope.WORKFLOW,
                        kind=MemoryKind.SEMANTIC,
                        refs={"run_id": "run-1"},
                    )
                ],
                mode=mode,
            ),
            store=store,
            policy=policy,
        )

    assert store.get("mem-merge") is None


def test_memory_writer_merges_existing_records() -> None:
    store = InMemoryMemoryStore(
        [
            MemoryRecord(
                memory_id="mem-merge",
                content="old content",
                scope=MemoryScope.WORKFLOW,
                kind=MemoryKind.SEMANTIC,
                metadata={"old": True},
                refs={"run_id": "run-1"},
                tags=["old"],
                confidence=0.3,
            )
        ]
    )
    writer = MemoryWriter()
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.SEMANTIC],
    )

    result = writer.write(
        MemoryWriteRequest(
            records=[
                MemoryRecord(
                    memory_id="mem-merge",
                    content="new content",
                    scope=MemoryScope.WORKFLOW,
                    kind=MemoryKind.SEMANTIC,
                    metadata={"new": True},
                    refs={"run_id": "run-2"},
                    tags=["new"],
                    confidence=0.8,
                )
            ],
            mode=MemoryWriteMode.MERGE,
        ),
        store=store,
        policy=policy,
    )

    merged = store.get("mem-merge")
    assert result.written_count == 1
    assert merged.content == "new content"
    assert merged.metadata == {"old": True, "new": True}
    assert merged.tags == ["new", "old"]
    assert merged.confidence == 0.8


def test_memory_writer_promotes_record_scope() -> None:
    store = InMemoryMemoryStore()
    writer = MemoryWriter()
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.SESSION, MemoryScope.AGENT],
        allowed_kinds=[MemoryKind.SEMANTIC],
    )

    result = writer.write(
        MemoryWriteRequest(
            records=[
                MemoryRecord(
                    memory_id="mem-promote",
                    content="promote memory",
                    scope=MemoryScope.SESSION,
                    kind=MemoryKind.SEMANTIC,
                    refs={"run_id": "run-1"},
                )
            ],
            mode=MemoryWriteMode.PROMOTE,
        ),
        store=store,
        policy=policy,
    )

    assert result.written_count == 1
    assert store.get("mem-promote").scope == MemoryScope.AGENT


def test_memory_writer_invalidates_existing_records() -> None:
    store = InMemoryMemoryStore(
        [
            MemoryRecord(
                memory_id="mem-invalidate",
                content="invalidate memory",
                scope=MemoryScope.WORKFLOW,
                kind=MemoryKind.SEMANTIC,
                refs={"run_id": "run-1"},
            )
        ]
    )
    writer = MemoryWriter()
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.SEMANTIC],
    )

    result = writer.write(
        MemoryWriteRequest(
            records=[
                MemoryRecord(
                    memory_id="mem-invalidate",
                    content="invalidate memory",
                    scope=MemoryScope.WORKFLOW,
                    kind=MemoryKind.SEMANTIC,
                    refs={"run_id": "run-2"},
                )
            ],
            mode=MemoryWriteMode.INVALIDATE,
        ),
        store=store,
        policy=policy,
    )

    assert result.written_count == 1
    assert store.get("mem-invalidate").metadata["invalidated"] is True
