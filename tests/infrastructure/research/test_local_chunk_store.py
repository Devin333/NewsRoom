from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from business.research.ports.chunk_payload_store import ChunkPayloadStorePort
from infrastructure.research import local_chunk_store as local_store_module
from infrastructure.research.local_chunk_store import (
    LOCAL_CHUNK_STORE_SCHEMA_VERSION,
    LocalChunkPayloadStore,
    LocalChunkStoreCorruptionError,
    LocalChunkStoreValidationError,
)


def _payload(
    chunk_id: str,
    *,
    paper_id: str = "paper-1",
    content: str = "bounded evidence retrieval",
    run_id: str = "run-1",
    tenant_id: str = "tenant-a",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chunk_metadata = {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "source_ref": f"paper://{paper_id}/{chunk_id}",
    }
    if metadata:
        chunk_metadata.update(metadata)
    return {
        "chunk_id": chunk_id,
        "paper_id": paper_id,
        "content": content,
        "run_id": run_id,
        "tenant_id": tenant_id,
        "section_title": "Method",
        "metadata": chunk_metadata,
    }


def _read_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _index_payload_in_process(
    root: str,
    chunk_id: str,
    start_barrier: Any,
) -> None:
    store = LocalChunkPayloadStore(root)
    start_barrier.wait(timeout=20)
    store.index_payloads([_payload(chunk_id)])


def _read_payloads_in_process(
    root: str,
    started: Any,
    finished: Any,
    output: Any,
) -> None:
    started.set()
    try:
        payloads = LocalChunkPayloadStore(root).list_paper_payloads("paper-1")
        output.put(("ok", [payload["chunk_id"] for payload in payloads]))
    except Exception as exc:
        output.put(("error", type(exc).__name__, str(exc)))
    finally:
        finished.set()


def test_local_chunk_store_is_raw_payload_port_and_survives_restart(tmp_path) -> None:
    store = LocalChunkPayloadStore(tmp_path, collection="paper_chunks")
    assert isinstance(store, ChunkPayloadStorePort)

    store.ensure_collection()
    store.index_payloads(
        [
            _payload("chunk-b"),
            _payload("chunk-a"),
            _payload("other-paper", paper_id="paper-2"),
        ]
    )

    state = _read_state(store.path)
    assert state["schema_version"] == LOCAL_CHUNK_STORE_SCHEMA_VERSION
    assert state["collection"] == "paper_chunks"
    assert state["checksum"].startswith("sha256:")
    assert [item["chunk_id"] for item in state["payloads"]] == [
        "chunk-a",
        "chunk-b",
        "other-paper",
    ]

    reopened = LocalChunkPayloadStore(tmp_path, collection="paper_chunks")
    assert reopened.get_payload("chunk-a") == _payload("chunk-a")
    assert [
        item["chunk_id"] for item in reopened.list_paper_payloads("paper-1")
    ] == ["chunk-a", "chunk-b"]


def test_local_chunk_store_returns_copies_instead_of_mutable_store_state(tmp_path) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads([_payload("chunk-a")])

    loaded = store.get_payload("chunk-a")
    assert loaded is not None
    loaded["metadata"]["run_id"] = "mutated"
    loaded["content"] = "mutated"

    assert store.get_payload("chunk-a") == _payload("chunk-a")


def test_local_chunk_store_serializes_concurrent_writes_across_instances(tmp_path) -> None:
    stores = [LocalChunkPayloadStore(tmp_path), LocalChunkPayloadStore(tmp_path)]
    payloads = [_payload(f"chunk-{index:02d}") for index in range(20)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(stores[index % 2].index_payloads, [payload])
            for index, payload in enumerate(payloads)
        ]
        for future in futures:
            future.result(timeout=10)

    assert [
        payload["chunk_id"] for payload in stores[0].list_paper_payloads("paper-1")
    ] == [f"chunk-{index:02d}" for index in range(20)]


def test_local_chunk_store_serializes_concurrent_writes_across_processes(
    tmp_path,
) -> None:
    context = multiprocessing.get_context("spawn")
    process_count = 4
    start_barrier = context.Barrier(process_count)
    processes = [
        context.Process(
            target=_index_payload_in_process,
            args=(str(tmp_path), f"process-{index}", start_barrier),
        )
        for index in range(process_count)
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    reopened = LocalChunkPayloadStore(tmp_path)
    assert [
        payload["chunk_id"]
        for payload in reopened.list_paper_payloads("paper-1")
    ] == [f"process-{index}" for index in range(process_count)]


def test_cross_process_reader_waits_for_atomic_writer_transaction(tmp_path) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads([_payload("committed")])
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    finished = context.Event()
    output = context.Queue()
    process = context.Process(
        target=_read_payloads_in_process,
        args=(str(tmp_path), started, finished, output),
    )

    try:
        with local_store_module._exclusive_file_lock(store._lock_path):
            process.start()
            assert started.wait(timeout=10)
            current = store._read_payloads() or []
            store._write_payloads([*current, _payload("writer")])
            assert finished.wait(timeout=0.5) is False
        process.join(timeout=20)
        assert process.exitcode == 0
        assert output.get(timeout=5) == ("ok", ["committed", "writer"])
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        output.close()


def test_lexical_search_filters_paper_run_and_tenant_with_stable_ties(
    tmp_path,
) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads(
        [
            _payload("tie-b"),
            _payload("tie-a"),
            _payload(
                "strong",
                content="bounded bounded evidence retrieval",
            ),
            _payload("wrong-run", run_id="run-2"),
            _payload("wrong-tenant", tenant_id="tenant-b"),
            _payload("wrong-paper", paper_id="paper-2"),
        ]
    )

    expected = ["strong", "tie-a", "tie-b"]
    first = store.search_payloads_with_scores(
        "paper-1",
        "bounded evidence",
        filters={"run_id": "run-1", "tenant_id": "tenant-a"},
        limit=10,
    )
    second = LocalChunkPayloadStore(tmp_path).search_payloads_with_scores(
        "paper-1",
        "bounded evidence",
        filters={"run_id": "run-1", "tenant_id": "tenant-a"},
        limit=10,
    )

    assert [payload["chunk_id"] for payload, _score in first] == expected
    assert second == first
    assert all(score > 0 for _payload, score in first)


def test_lexical_search_offset_pages_the_stable_ranking(tmp_path) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads(
        [
            _payload("tie-c"),
            _payload("tie-a"),
            _payload("tie-b"),
            _payload("strong", content="bounded bounded evidence retrieval"),
        ]
    )

    ranked = store.search_payloads_with_scores(
        "paper-1",
        "bounded evidence",
        filters={"run_id": "run-1", "tenant_id": "tenant-a"},
        limit=10,
    )
    page = store.search_payloads_with_scores(
        "paper-1",
        "bounded evidence",
        filters={"run_id": "run-1", "tenant_id": "tenant-a"},
        limit=2,
        offset=1,
    )

    assert page == ranked[1:3]
    assert store.search_payloads(
        "paper-1",
        "bounded evidence",
        filters={"run_id": "run-1", "tenant_id": "tenant-a"},
        limit=2,
        offset=1,
    ) == [payload for payload, _score in ranked[1:3]]


def test_lexical_search_supports_nested_metadata_filter_and_threshold(tmp_path) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads(
        [
            _payload(
                "method",
                content="unrelated body",
                metadata={"section": "methods", "caption": "retrieval ablation"},
            ),
            _payload(
                "experiment",
                content="retrieval ablation",
                metadata={"section": "experiments"},
            ),
        ]
    )

    scored = store.search_payloads_with_scores(
        "paper-1",
        "retrieval ablation",
        filters={"metadata.section": "methods"},
        limit=5,
    )
    assert [payload["chunk_id"] for payload, _score in scored] == ["method"]
    threshold = scored[0][1]
    assert store.search_payloads(
        "paper-1",
        "retrieval ablation",
        filters={"section": "methods"},
        limit=5,
        score_threshold=threshold,
    ) == [scored[0][0]]
    assert store.search_payloads(
        "paper-1",
        "retrieval ablation",
        filters={"section": "methods"},
        limit=5,
        score_threshold=threshold + 0.001,
    ) == []


def test_delete_paper_chunks_preserves_other_papers(tmp_path) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads(
        [
            _payload("paper-1-a"),
            _payload("paper-1-b"),
            _payload("paper-2-a", paper_id="paper-2"),
        ]
    )

    store.delete_paper_chunks("paper-1")

    assert store.list_paper_payloads("paper-1") == []
    assert store.get_payload("paper-1-a") is None
    assert store.list_paper_payloads("paper-2") == [
        _payload("paper-2-a", paper_id="paper-2")
    ]


@pytest.mark.parametrize(
    "payloads, message",
    [
        ([{"chunk_id": "c", "paper_id": "p"}], "content"),
        ([_payload("duplicate"), _payload("duplicate")], "duplicate chunk_id"),
        ([_payload("not-finite", metadata={"score": float("nan")})], "finite JSON"),
    ],
)
def test_local_chunk_store_rejects_invalid_payloads_without_committing(
    tmp_path,
    payloads,
    message,
) -> None:
    store = LocalChunkPayloadStore(tmp_path)

    with pytest.raises(LocalChunkStoreValidationError, match=message):
        store.index_payloads(payloads)

    assert store.path.exists() is False


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda state: state["payloads"][0].update(content="tampered"), "checksum"),
        (lambda state: state.update(checksum="invalid"), "checksum"),
        (lambda state: state.update(schema_version=99), "schema version"),
        (lambda state: state.update(collection="other"), "collection identity"),
    ],
)
def test_local_chunk_store_rejects_tampered_snapshot(
    tmp_path,
    mutate,
    message,
) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads([_payload("chunk-a")])
    state = _read_state(store.path)
    mutate(state)
    store.path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(LocalChunkStoreCorruptionError, match=message):
        LocalChunkPayloadStore(tmp_path).get_payload("chunk-a")


def test_local_chunk_store_rejects_malformed_json(tmp_path) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.ensure_collection()
    store.path.write_bytes(b"{not-json")

    with pytest.raises(LocalChunkStoreCorruptionError, match="JSON"):
        store.list_paper_payloads("paper-1")


def test_local_chunk_store_rejects_non_regular_snapshot_node(tmp_path) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.mkdir()

    with pytest.raises(LocalChunkStoreCorruptionError, match="regular file"):
        store.ensure_collection()


def test_local_chunk_store_rejects_file_identity_swap_during_open(
    tmp_path,
    monkeypatch,
) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads([_payload("chunk-a")])
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(store.path.read_bytes())
    real_open = Path.open

    def open_replacement(path, *args, **kwargs):
        selected = replacement if path == store.path else path
        return real_open(selected, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_replacement)
    with pytest.raises(LocalChunkStoreCorruptionError, match="identity changed"):
        store.get_payload("chunk-a")


def test_local_chunk_store_rejects_unsafe_collection_and_file_root(tmp_path) -> None:
    with pytest.raises(LocalChunkStoreValidationError, match="collection"):
        LocalChunkPayloadStore(tmp_path, collection="../outside")

    file_root = tmp_path / "root-file"
    file_root.write_text("not a directory", encoding="utf-8")
    with pytest.raises(LocalChunkStoreValidationError, match="directory"):
        LocalChunkPayloadStore(file_root)


def test_collection_identity_is_validated_when_snapshot_is_misplaced(tmp_path) -> None:
    source = LocalChunkPayloadStore(tmp_path, collection="source_chunks")
    source.index_payloads([_payload("chunk-a")])
    target = LocalChunkPayloadStore(tmp_path, collection="target_chunks")
    target.path.write_bytes(source.path.read_bytes())

    with pytest.raises(LocalChunkStoreCorruptionError, match="collection identity"):
        target.get_payload("chunk-a")


def test_atomic_replace_failure_preserves_prior_snapshot_and_cleans_temp(
    tmp_path,
    monkeypatch,
) -> None:
    store = LocalChunkPayloadStore(tmp_path)
    store.index_payloads([_payload("committed", content="old content")])
    committed = store.path.read_bytes()

    def fail_replace(_source, _destination) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(local_store_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.index_payloads([_payload("pending", content="new content")])

    assert store.path.read_bytes() == committed
    assert list(tmp_path.glob("*.tmp")) == []
    assert store.get_payload("committed") == _payload(
        "committed",
        content="old content",
    )
    assert store.get_payload("pending") is None
