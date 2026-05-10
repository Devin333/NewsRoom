from interfaces.services.mcp_service import MCPApplicationService


def test_mcp_catalog_lists_tools_without_calling_factories() -> None:
    service = MCPApplicationService(
        worker_service_factory=_raising_factory,
        report_service_factory=_raising_factory,
        source_service_factory=_raising_factory,
        memory_service_factory=_raising_factory,
        diagnostic_service_factory=_raising_factory,
    )

    catalog = service.catalog().to_dict()

    assert "news.daily.enqueue" in [tool["name"] for tool in catalog["tools"]]
    assert "news://reports/latest" in [resource["uri"] for resource in catalog["resources"]]
    assert "news.evidence_audit" in [prompt["name"] for prompt in catalog["prompts"]]


def test_mcp_source_health_tool_calls_source_service() -> None:
    service = MCPApplicationService(source_service_factory=lambda: _FakeSourceService())

    result = service.call_tool("news.source.health", {"include_disabled": True})

    assert result.success is True
    assert result.to_dict()["data"]["health"][0]["source_id"] == "source-1"


def test_mcp_unknown_tool_fails_safely() -> None:
    service = MCPApplicationService()

    result = service.call_tool("news.unknown")

    assert result.success is False
    assert result.error_type == "MCPToolNotFound"


def test_mcp_memory_search_requires_query() -> None:
    service = MCPApplicationService(memory_service_factory=lambda: _FakeMemoryService())

    result = service.call_tool("news.memory.search", {})

    assert result.success is False
    assert result.error_type == "ValueError"
    assert "query is required" in result.error_message


def _raising_factory():
    raise AssertionError("factory should not be called")


class _FakeSourceService:
    def source_health(self, *, enabled_only):
        return _FakeResult(
            {
                "source_count": 1,
                "health": [
                    {
                        "source_id": "source-1",
                        "status": "healthy",
                        "consecutive_failures": 0,
                        "last_success_at": None,
                        "last_failure_at": None,
                        "cooldown_until": None,
                        "last_error": None,
                    }
                ],
            }
        )


class _FakeMemoryService:
    def search(self, **kwargs):
        return _FakeResult({"result_count": 0, "results": []})


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
