from infrastructure.storage.vector import FakeEmbeddingAdapter, InMemoryVectorStore, VectorDocument, VectorSearchQuery


def test_in_memory_vector_store_searches_by_similarity() -> None:
    store = InMemoryVectorStore(embedding_model=FakeEmbeddingAdapter())
    store.upsert_documents(
        [
            VectorDocument(
                document_id="agent-runtime",
                collection="report_sections",
                text="Agent runtime framework memory and workflow execution",
                payload={"topic": "agents"},
                source_type="report_section",
                run_id="run-1",
            ),
            VectorDocument(
                document_id="chip-supply",
                collection="report_sections",
                text="Semiconductor supply chain pricing update",
                payload={"topic": "chips"},
                source_type="report_section",
                run_id="run-2",
            ),
        ]
    )

    results = store.search(VectorSearchQuery(collection="report_sections", text="agent runtime workflow"))

    assert results[0].document_id == "agent-runtime"
    assert results[0].score >= results[1].score


def test_in_memory_vector_store_filters_payload() -> None:
    store = InMemoryVectorStore()
    store.upsert_documents(
        [
            VectorDocument(
                document_id="ai",
                collection="evidence_items",
                text="AI model launch",
                payload={"topic": "AI", "category": "models"},
                source_type="evidence_item",
            ),
            VectorDocument(
                document_id="policy",
                collection="evidence_items",
                text="Policy consultation",
                payload={"topic": "policy", "category": "regulation"},
                source_type="evidence_item",
            ),
        ]
    )

    results = store.search(
        VectorSearchQuery(
            collection="evidence_items",
            text="model",
            filters={"topic": "AI"},
        )
    )

    assert [result.document_id for result in results] == ["ai"]


def test_in_memory_vector_store_ensure_collections_is_idempotent() -> None:
    store = InMemoryVectorStore()

    created = store.ensure_collections(["report_sections", "evidence_items"])
    existing = store.ensure_collections(["report_sections"])

    assert [status.to_dict() for status in created] == [
        {
            "collection": "report_sections",
            "vector_size": 64,
            "existed_before": False,
            "created": True,
        },
        {
            "collection": "evidence_items",
            "vector_size": 64,
            "existed_before": False,
            "created": True,
        },
    ]
    assert existing[0].to_dict() == {
        "collection": "report_sections",
        "vector_size": 64,
        "existed_before": True,
        "created": False,
    }


def test_in_memory_vector_store_delete_by_filter() -> None:
    store = InMemoryVectorStore()
    store.upsert_documents(
        [
            VectorDocument(
                document_id="run-1-doc",
                collection="topic_summaries",
                text="First run",
                payload={},
                source_type="topic_summary",
                run_id="run-1",
            ),
            VectorDocument(
                document_id="run-2-doc",
                collection="topic_summaries",
                text="Second run",
                payload={},
                source_type="topic_summary",
                run_id="run-2",
            ),
        ]
    )

    deleted = store.delete_by_filter("topic_summaries", {"run_id": "run-1"})
    remaining = store.search(VectorSearchQuery(collection="topic_summaries", text="run"))

    assert deleted == 1
    assert [result.document_id for result in remaining] == ["run-2-doc"]
