from __future__ import annotations

from framework.rag.context import collect_nearby_context_ids


def test_collect_nearby_context_ids_reads_direct_parent_and_referenced_edges():
    result = collect_nearby_context_ids(
        metadata={
            "nearby_context_chunk_id": "near-1",
            "parent_table_chunk_id": "table-parent",
            "referenced_by_chunks": [
                {"chunk_id": "ref-1"},
                {"chunk_id": "near-1"},
                {"chunk_id": ""},
            ],
        },
        parent_id="parent-1",
    )

    assert result.ids == ("near-1", "table-parent", "parent-1", "ref-1")
    assert result.by_edge["nearby_context_chunk_id"] == ("near-1",)
    assert result.by_edge["referenced_by_chunks"] == ("ref-1", "near-1")


def test_collect_nearby_context_ids_can_include_plain_references():
    result = collect_nearby_context_ids(
        metadata={},
        references=("ref-1", "ref-2", "ref-1"),
        include_references=True,
        include_parent=False,
    )

    assert result.ids == ("ref-1", "ref-2")
    assert result.by_edge["references"] == ("ref-1", "ref-2")


def test_collect_nearby_context_ids_accepts_custom_edge_keys():
    result = collect_nearby_context_ids(
        metadata={"custom_context_id": "custom-1"},
        direct_keys=("custom_context_id",),
        reference_list_keys=(),
        include_parent=False,
    )

    assert result.to_dict() == {
        "ids": ["custom-1"],
        "by_edge": {"custom_context_id": ["custom-1"]},
    }
