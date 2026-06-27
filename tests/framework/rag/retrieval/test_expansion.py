from __future__ import annotations

import pytest

from framework.rag.retrieval import ExpansionMetadata, expansion_metadata


def test_expansion_metadata_uses_standard_kernel_keys():
    metadata = expansion_metadata(
        expanded_from_id="chunk-1",
        reason="nearby_context",
        edge="nearby_context_chunk_id",
        rank=2,
        metadata={"source": "test"},
    )

    assert metadata == {
        "expanded_from_chunk_id": "chunk-1",
        "expansion_reason": "nearby_context",
        "expansion_edge": "nearby_context_chunk_id",
        "expansion_rank": 2,
        "source": "test",
    }


def test_expansion_metadata_validates_required_fields():
    with pytest.raises(ValueError, match="expanded_from_id is required"):
        ExpansionMetadata(expanded_from_id="", reason="reason", edge="edge", rank=1)

    with pytest.raises(ValueError, match="rank must be greater than or equal to zero"):
        ExpansionMetadata(expanded_from_id="chunk-1", reason="reason", edge="edge", rank=-1)
