from __future__ import annotations

from interfaces.services.mcp_service import MCPApplicationService


STABLE_TOOLS = {
    "news.daily.run",
    "news.daily.enqueue",
    "news.report.latest",
    "news.report.list",
    "news.report.get",
    "news.report.search",
    "news.memory.search",
    "news.source.health",
    "news.worker.status",
    "news.queue.status",
    "news.run.diagnostics",
    "news.run.events",
    "news.approval.list",
}

DANGEROUS_TOOLS = {
    "news.report.publish",
    "news.run.cancel",
    "news.run.rerun_from_step",
    "news.approval.approve",
    "news.approval.reject",
}

STABLE_RESOURCES = {
    "news://reports/latest",
    "news://reports/{report_id}",
    "news://runs/{run_id}/manifest",
    "news://runs/{run_id}/events",
    "news://runs/{run_id}/replay",
    "news://runs/{run_id}/lineage",
    "news://runs/{run_id}/artifacts/{artifact_key}",
    "news://memory/{document_id}",
    "news://sources/health",
    "news://workers",
    "news://queues",
    "news://storage/metrics",
}

STABLE_PROMPTS = {
    "news.daily.briefing",
    "news.report.review",
    "news.run.diagnose",
    "news.source.triage",
}


def test_mcp_catalog_contains_stable_contract_surface() -> None:
    catalog = MCPApplicationService().catalog().to_dict()

    tool_names = {tool["name"] for tool in catalog["tools"]}
    resource_uris = {resource["uri"] for resource in catalog["resources"]}
    prompt_names = {prompt["name"] for prompt in catalog["prompts"]}

    assert STABLE_TOOLS <= tool_names
    assert DANGEROUS_TOOLS <= tool_names
    assert STABLE_RESOURCES <= resource_uris
    assert STABLE_PROMPTS <= prompt_names


def test_mcp_manifest_capabilities_match_catalog() -> None:
    service = MCPApplicationService()
    catalog = service.catalog().to_dict()
    manifest = service.capability_manifest().to_dict()

    catalog_names = {
        *{tool["name"] for tool in catalog["tools"]},
        *{resource["uri"] for resource in catalog["resources"]},
        *{prompt["name"] for prompt in catalog["prompts"]},
    }
    capability_names = {capability["name"] for capability in manifest["capabilities"]}

    assert manifest["version"] == "1.0"
    assert manifest["capability_count"] == len(manifest["capabilities"])
    assert catalog_names == capability_names


def test_mcp_dangerous_tools_have_confirmation_metadata() -> None:
    manifest = MCPApplicationService().capability_manifest().to_dict()
    capabilities = {capability["name"]: capability for capability in manifest["capabilities"]}

    for tool_name in DANGEROUS_TOOLS:
        capability = capabilities[tool_name]
        metadata = capability["metadata"]

        assert capability["kind"] == "tool"
        assert capability["read_only"] is False
        assert capability["risk_level"] == "high"
        assert metadata["requires_confirmation"] is True
        assert metadata["side_effect_level"] == "external_write"

    assert capabilities["news.report.publish"]["requires_approval"] is True


def test_mcp_unknown_tool_and_resource_return_structured_errors() -> None:
    service = MCPApplicationService()

    tool = service.call_tool("news.unknown", {})
    resource = service.read_resource("news://unknown")

    assert tool.success is False
    assert tool.error_type == "MCPToolNotFound"
    assert "news.unknown" in str(tool.error_message)
    assert resource.success is False
    assert resource.error_type == "MCPResourceNotFound"
    assert "news://unknown" in str(resource.error_message)


def test_mcp_run_operation_tools_delegate_to_application_service() -> None:
    fake_service = _FakeRunOperationService()
    service = MCPApplicationService(run_operation_service_factory=lambda: fake_service)

    cancelled = service.call_tool(
        "news.run.cancel",
        {
            "run_id": "run-1",
            "reason": "manual stop",
            "actor_id": "operator",
            "metadata": {"source": "mcp"},
        },
    )
    rerun = service.call_tool(
        "news.run.rerun_from_step",
        {
            "run_id": "run-1",
            "step_id": "write_report",
            "actor_id": "operator",
            "metadata": {"source": "mcp"},
        },
    )

    assert cancelled.success is True
    assert rerun.success is True
    assert fake_service.calls == [
        (
            "cancel_run",
            {
                "run_id": "run-1",
                "reason": "manual stop",
                "actor_id": "operator",
                "metadata": {"source": "mcp"},
            },
        ),
        (
            "rerun_from_step",
            {
                "run_id": "run-1",
                "step_id": "write_report",
                "actor_id": "operator",
                "metadata": {"source": "mcp"},
            },
        ),
    ]
    assert cancelled.data["operation_type"] == "cancel_run"
    assert rerun.data["operation_type"] == "rerun_from_step"


class _FakeRunOperationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def cancel_run(self, run_id, *, reason=None, actor_id=None, metadata=None):
        self.calls.append(
            (
                "cancel_run",
                {
                    "run_id": run_id,
                    "reason": reason,
                    "actor_id": actor_id,
                    "metadata": dict(metadata or {}),
                },
            )
        )
        return _FakeOperationResult("cancel_run")

    def rerun_from_step(self, run_id, *, step_id, actor_id=None, metadata=None):
        self.calls.append(
            (
                "rerun_from_step",
                {
                    "run_id": run_id,
                    "step_id": step_id,
                    "actor_id": actor_id,
                    "metadata": dict(metadata or {}),
                },
            )
        )
        return _FakeOperationResult("rerun_from_step")


class _FakeOperationResult:
    def __init__(self, operation_type: str) -> None:
        self.operation_type = operation_type

    def to_dict(self):
        return {
            "operation_id": "op-test",
            "operation_type": self.operation_type,
            "status": "accepted",
        }
