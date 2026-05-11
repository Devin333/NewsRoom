from interfaces.api.schema import export_openapi_schema, summarize_openapi_schema


def test_export_openapi_schema_includes_known_api_routes() -> None:
    schema = export_openapi_schema()

    assert schema["info"]["title"] == "NewsRoom API"
    assert schema["info"]["version"] == "0.1.0"
    assert "/api/v1/runs/daily" in schema["paths"]
    assert "/api/v1/memory/search" in schema["paths"]
    assert "DailyRunRequest" in schema["components"]["schemas"]
    assert "MemorySearchRequest" in schema["components"]["schemas"]


def test_summarize_openapi_schema_counts_paths_and_schemas() -> None:
    summary = summarize_openapi_schema(export_openapi_schema())

    assert summary["title"] == "NewsRoom API"
    assert summary["version"] == "0.1.0"
    assert summary["openapi"].startswith("3.")
    assert summary["path_count"] >= 1
    assert summary["schema_count"] >= 1
