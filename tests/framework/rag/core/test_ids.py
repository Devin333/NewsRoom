from __future__ import annotations

from framework.rag.core import (
    build_chunk_semantic_key,
    build_rag_stable_id,
    content_fingerprint,
    normalize_rag_key,
    normalize_semantic_text,
)


def test_build_rag_stable_id_normalizes_parts_and_prefix():
    assert build_rag_stable_id("Chunk", "Paper", "Method") == build_rag_stable_id(
        "chunk",
        " paper ",
        "method",
    )
    assert build_rag_stable_id("Page Visual", "p1").startswith("page_visual_")


def test_content_fingerprint_ignores_case_and_whitespace():
    assert content_fingerprint("Target   Paragraph") == content_fingerprint("target paragraph")
    assert normalize_semantic_text(" A\nB ") == "a b"
    assert normalize_rag_key("Page & Visual") == "page_and_visual"


def test_build_chunk_semantic_key_records_stable_parts():
    semantic = build_chunk_semantic_key(
        document_id="p1",
        chunk_type="paragraph",
        section_title=" Methods ",
        source_locator="paper://p1#page=2",
        content="Target paragraph.",
    )

    assert semantic.key.startswith("chunk_semantic_")
    assert semantic.parts == {
        "chunk_type": "paragraph",
        "section_title": "methods",
        "source_locator": "paper://p1#page=2",
        "content_hash": semantic.content_hash,
    }


def test_build_chunk_semantic_key_can_reuse_existing_content_hash():
    semantic = build_chunk_semantic_key(
        document_id="p1",
        chunk_type="paragraph",
        section_title="Methods",
        source_locator="paper://p1#page=2",
        content="Changed parser text.",
        content_hash="existing-hash",
    )

    assert semantic.content_hash == "existing-hash"
    assert semantic.parts["content_hash"] == "existing-hash"
