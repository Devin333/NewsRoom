from interfaces.api.schema import export_openapi_schema, summarize_openapi_schema


def test_export_openapi_schema_includes_known_api_routes() -> None:
    schema = export_openapi_schema()

    assert schema["info"]["title"] == "NewsRoom API"
    assert schema["info"]["version"] == "0.1.0"
    assert "/api/v1/research/papers/analyze" in schema["paths"]
    assert "/api/v1/research/papers/{paper_id}/analysis" in schema["paths"]
    assert "/api/v1/research/papers/{paper_id}/reader" in schema["paths"]
    assert "/api/v1/research/papers/{paper_id}/ask" in schema["paths"]
    assert "/api/v1/research/runs/{run_id}/trace" in schema["paths"]
    assert "/api/v1/runs/daily" not in schema["paths"]
    assert "/api/v1/runs/weekly" not in schema["paths"]
    assert "/api/v1/papers" not in schema["paths"]
    assert "/api/v1/boards" not in schema["paths"]
    assert "/api/v1/memory/search" in schema["paths"]
    assert "/api/v1/mcp/capabilities" in schema["paths"]
    assert "/api/v1/runs/{run_id}/progress" in schema["paths"]
    assert "ResearchAnalyzeRequest" in schema["components"]["schemas"]
    assert "ResearchAskRequest" in schema["components"]["schemas"]
    assert "MemorySearchRequest" in schema["components"]["schemas"]
    assert "ApiResponse" in schema["components"]["schemas"]
    assert "RunResponse" in schema["components"]["schemas"]
    progress_responses = schema["paths"]["/api/v1/runs/{run_id}/progress"]["get"]["responses"]
    assert "text/event-stream" in progress_responses["200"]["content"]


def test_summarize_openapi_schema_counts_paths_and_schemas() -> None:
    summary = summarize_openapi_schema(export_openapi_schema())

    assert summary["title"] == "NewsRoom API"
    assert summary["version"] == "0.1.0"
    assert summary["openapi"].startswith("3.")
    assert summary["path_count"] >= 1
    assert summary["schema_count"] >= 1
