from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from framework.agent.loop import AgentLoop
from framework.agent.models import AgentLoopPolicy, AgentLoopStatus, AgentSpec
from framework.llm import (
    LOCAL_STRUCTURED_OUTPUT_DIALECT,
    CacheLookupStatus,
    CacheMode,
    InMemoryLLMCache,
    LLMCacheKeyFactory,
    LLMCachePolicy,
    LLMCacheRuntime,
    LLMRequest,
    LLMResponse,
    LLMRouteError,
    LLMRouter,
    LLMStreamEvent,
    ModelContextProfile,
    ModelDeployment,
    ModelRoute,
    ProviderStructuredOutputCapability,
    StructuredOutputCacheIdentity,
    StructuredOutputEvent,
    compile_structured_output_contract,
    managed_validation_metadata,
    project_structured_output_contract,
    project_structured_output_metrics,
    structured_output_enforcement_keywords,
)
from tests.framework.llm._structured_output_release import (
    approved_structured_output_release,
)
from framework.llm.cache import CacheEntry
from framework.llm.clients.openai_compatible import LLMProviderError
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.tool import ToolExecutor, ToolRegistry


_SCHEMA = {
    "type": "object",
    "properties": {"output": {"type": "string"}},
    "required": ["output"],
    "additionalProperties": False,
}


def test_structured_cache_binds_identity_and_revalidates_corruption() -> None:
    cache = InMemoryLLMCache()
    runtime = _cache_runtime(cache)
    request = _managed_request(schema_revision="schema-v1")
    preparation = runtime.prepare(
        request=request,
        deployment_id="deployment",
        provider="provider",
        model="model",
    )

    assert preparation.eligible is True
    assert preparation.key is not None
    identity = preparation.key.structured_output_identity
    assert isinstance(identity, StructuredOutputCacheIdentity)
    response = _managed_response(identity, {"output": "accepted"})
    assert runtime.write(preparation, request=request, response=response).stored
    assert runtime.read(preparation, request=request).hit

    revised = _managed_request(schema_revision="schema-v2")
    revised_preparation = runtime.prepare(
        request=revised,
        deployment_id="deployment",
        provider="provider",
        model="model",
    )
    assert revised_preparation.key is not None
    assert revised_preparation.key.request_digest != preparation.key.request_digest
    assert runtime.read(revised_preparation, request=revised).lookup.status is CacheLookupStatus.MISS

    valid_entry = CacheEntry.from_response(
        key=preparation.key,
        request=request,
        response=response,
    )
    corrupt_payload = deepcopy(valid_entry.response)
    corrupt_payload["structured_output"] = {"output": 7}
    corrupt_entry = replace(valid_entry, response=corrupt_payload)
    assert cache.put(preparation.key, corrupt_entry, ttl_seconds=60).stored

    corrupted = runtime.read(preparation, request=request)

    assert corrupted.lookup.status is CacheLookupStatus.CORRUPT
    assert corrupted.lookup.reason == "entry_validation_failed"
    assert cache.entry_count == 0


def test_unmanaged_structured_request_is_not_cache_eligible() -> None:
    runtime = _cache_runtime(InMemoryLLMCache())
    request = LLMRequest(
        messages=[{"role": "user", "content": "stable"}],
        temperature=0,
        output_schema=_SCHEMA,
        metadata=_cache_metadata(),
    )

    preparation = runtime.prepare(
        request=request,
        deployment_id="deployment",
        provider="provider",
        model="model",
    )

    assert preparation.eligible is False
    assert preparation.eligibility.reason == "unmanaged_structured_output"


def test_structured_stream_cache_preserves_terminal_identity_and_revalidates() -> None:
    contract = compile_structured_output_contract(_SCHEMA, schema_name="stream_output")
    capability = ProviderStructuredOutputCapability(
        provider="provider",
        deployment="deployment",
        mode="native_strict",
        supported_dialect=LOCAL_STRUCTURED_OUTPUT_DIALECT,
        supported_keywords=structured_output_enforcement_keywords(
            contract.canonical_schema
        ),
        supports_local_refs=True,
        supports_stream_terminal_validation=True,
        revision="stream-capability-v1",
        release=approved_structured_output_release(
            provider="provider",
            deployment="deployment",
            capability_revision="stream-capability-v1",
        ),
    )
    client = _ManagedStreamClient()
    store = InMemoryLLMCache()
    recorded = []
    router = LLMRouter(
        routes=[ModelRoute(route_id="route", primary_deployment_id="deployment")],
        deployments=[
            ModelDeployment(
                deployment_id="deployment",
                provider="provider",
                model="model",
                client=client,
                structured_output_capability=capability,
                context_profile=ModelContextProfile(
                    deployment_id="deployment",
                    provider="provider",
                    model="model",
                    physical_context_window_tokens=16_000,
                    max_output_tokens=1_024,
                    default_output_tokens=128,
                    tokenizer_family="test",
                    tokenizer_revision="test-v1",
                    normalizer_revision="canonical-request-v1",
                    profile_revision="profile-v1",
                    operational_input_fraction=1.0,
                    allow_conservative_fallback=True,
                ),
            )
        ],
        cache_runtime=_cache_runtime(store),
        event_sink=recorded.append,
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "stable"}],
        temperature=0,
        output_schema=_SCHEMA,
        output_schema_name="stream_output",
        metadata=_cache_metadata(),
    )

    first = list(router.stream("route", request))
    second = list(router.stream("route", request))

    assert client.call_count == 1
    assert store.entry_count == 1
    assert first[-1].structured_output == {"output": "streamed"}
    assert second[-1].structured_output == {"output": "streamed"}
    cache_events = [
        event
        for event in recorded
        if event.event_type == "structured_output_cache_validation"
    ]
    assert any(event.metadata["outcome"] == "stored" for event in cache_events)
    assert any(event.metadata["outcome"] == "validated_hit" for event in cache_events)


def test_router_records_schema_preflight_failure_before_provider_call() -> None:
    client = _NeverCalledClient()
    recorded = []
    router = LLMRouter(
        routes=[ModelRoute(route_id="route", primary_deployment_id="deployment")],
        deployments=[
            ModelDeployment(
                deployment_id="deployment",
                provider="provider",
                model="model",
                client=client,
            )
        ],
        event_sink=recorded.append,
    )

    try:
        router.complete(
            "route",
            LLMRequest(messages=[], output_schema={"type": "array"}),
        )
    except LLMRouteError as exc:
        assert exc.error_type == "structured_output_schema_error"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("invalid schema must fail before provider call")

    assert client.call_count == 0
    assert [event.event_type for event in recorded] == [
        "structured_output_schema_preflight_failed"
    ]
    points = project_structured_output_metrics(event.to_dict() for event in recorded)
    assert [point.name for point in points] == [
        "structured_output_schema_preflight_failures_total"
    ]


def test_agent_loop_halts_repeated_unchanged_structured_failure() -> None:
    rejected_marker = "RAW-REJECTED-CANDIDATE"
    client = _RejectingStructuredClient(
        fingerprints=["sha256:" + "a" * 64, "sha256:" + "a" * 64],
        raw_marker=rejected_marker,
    )
    agent = AgentSpec(
        agent_id="structured-repair-agent",
        name="Structured Repair Agent",
        instructions="Return the requested object.",
        output_schema=_SCHEMA,
        loop_policy=AgentLoopPolicy(max_iterations=5, max_judge_retries=4),
    )

    result = AgentLoop(
        llm_client=client,
        tool_executor=ToolExecutor(ToolRegistry()),
    ).run(agent, {}, [], run_id="run-structured-repair", standalone=True)

    assert result.success is False
    assert result.status is AgentLoopStatus.RETRY_EXHAUSTED
    assert client.call_count == 2
    event_types = [event["event_type"] for event in result.events]
    assert event_types.count("structured_output_repair_requested") == 1
    assert event_types.count("structured_output_repair_budget_exhausted") == 1
    assert result.metrics.structured_output_repairs == 1
    assert result.metrics.structured_output_repair_budget_exhausted == 1
    assert rejected_marker not in str(result.to_dict())


def test_agent_loop_repairs_once_then_accepts_managed_terminal_output() -> None:
    client = _RepairingStructuredClient()
    agent = AgentSpec(
        agent_id="repair-success-agent",
        name="Repair Success Agent",
        instructions="Return the requested object.",
        output_schema=_SCHEMA,
        loop_policy=AgentLoopPolicy(max_iterations=3, max_judge_retries=2),
    )

    result = AgentLoop(
        llm_client=client,
        tool_executor=ToolExecutor(ToolRegistry()),
    ).run(agent, {}, [], run_id="run-repair-success", standalone=True)

    assert result.success is True
    assert client.call_count == 2
    assert result.output == {"output": "repaired"}
    event_types = [event["event_type"] for event in result.events]
    assert event_types.count("structured_output_repair_requested") == 1
    assert event_types.count("structured_output_validation_accepted") == 1
    assert result.metrics.structured_output_validation_accepts == 1


def test_structured_output_metrics_use_only_bounded_low_cardinality_labels() -> None:
    digest = "sha256:" + "f" * 64
    points = project_structured_output_metrics(
        [
            {
                "event_type": "structured_output_contract_compiled",
                "metadata": {"schema_digest": digest, "schema_bytes": 420},
            },
            {
                "event_type": "structured_output_local_validation_failed",
                "metadata": {
                    "issue_code": "structured_output_validation_error",
                    "validator": "required",
                    "instance_path": ["private", "path"],
                    "schema_digest": digest,
                },
            },
            {
                "event_type": "structured_output_cache_validation",
                "metadata": {"outcome": "validated_hit", "schema_digest": digest},
            },
        ]
    )

    assert {point.name for point in points} >= {
        "structured_output_requests_total",
        "structured_output_schema_bytes",
        "structured_output_validation_failures_total",
        "structured_output_cache_validation_total",
        "structured_output_provider_vs_local_failure_total",
    }
    labels = {key for point in points for key in point.labels}
    assert labels <= {"mode", "outcome", "code", "validator", "provider"}
    assert digest not in str([dict(point.labels) for point in points])
    assert "private" not in str([dict(point.labels) for point in points])


def test_structured_output_event_envelope_is_allowlisted_and_bounded() -> None:
    event = StructuredOutputEvent(
        event_type="structured_output_local_validation_failed",
        run_id="run-1",
        attempt_ref="2",
        issue_code="structured_output_validation_error",
        instance_path=("output",),
        issue_count=1,
        response_fingerprint="sha256:" + "a" * 64,
        budget_disposition="repair_authorized",
    )

    payload = event.to_dict()
    assert payload["event_type"] == "structured_output_local_validation_failed"
    assert payload["instance_path"] == ["output"]
    assert set(payload).isdisjoint({"raw_output", "schema", "prompt", "evidence"})
    with pytest.raises(ValueError):
        StructuredOutputEvent(event_type="unreviewed_event")
    with pytest.raises(ValueError):
        StructuredOutputEvent(
            event_type="structured_output_local_validation_failed",
            issue_count=21,
        )


def test_graph_structured_output_event_carries_exact_execution_identity() -> None:
    identity = GraphExecutionIdentity(
        run_id="structured-run",
        graph_id="structured-graph",
        graph_version="1",
        graph_ref="structured-graph@1",
        graph_checksum="sha256:" + "3" * 64,
        node_id="agent",
        node_instance_id="agent-instance",
        activity_id="agent-activity",
        attempt=2,
    )
    event = StructuredOutputEvent(
        event_type="structured_output_validation_accepted",
        execution_identity=identity,
        attempt_ref="2",
    )

    assert event.to_payload()["execution_identity"] == identity.to_dict()
    assert event.run_id == identity.run_id


def test_production_has_no_unmanaged_structured_output_parser_or_validator() -> None:
    root = Path(__file__).resolve().parents[3]
    production_roots = [root / name for name in ("backend", "framework", "infrastructure", "interfaces")]
    approved_validator_owner = (
        root / "framework" / "llm" / "structured_output" / "validator.py"
    ).resolve()
    violations: list[str] = []
    for production_root in production_roots:
        for source_path in production_root.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call_name = _call_name(node.func)
                if (
                    call_name == "validate_structured_output"
                    and source_path.resolve() != approved_validator_owner
                ):
                    violations.append(f"{source_path}:{node.lineno}:compat_validator")
                if call_name.endswith("json.loads") and node.args and _is_response_content(node.args[0]):
                    violations.append(f"{source_path}:{node.lineno}:response_content_json")
    assert violations == []


class _RejectingStructuredClient:
    def __init__(self, *, fingerprints: list[str], raw_marker: str) -> None:
        self._fingerprints = list(fingerprints)
        self.raw_marker = raw_marker
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        fingerprint = self._fingerprints[self.call_count]
        self.call_count += 1
        raise LLMProviderError(
            f"structured output rejected {self.raw_marker}",
            provider="recorded",
            model="recorded-model",
            error_type="structured_output_validation_error",
            retryable=False,
            diagnostics=(
                {
                    "code": "structured_output_validation_error",
                    "message": self.raw_marker,
                    "instance_path": ["output"],
                    "schema_path": ["properties", "output", "type"],
                    "validator": "type",
                },
            ),
            response_fingerprint=fingerprint,
        )


class _RepairingStructuredClient:
    call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        if self.call_count == 1:
            raise LLMProviderError(
                "structured output rejected",
                provider="recorded",
                model="recorded-model",
                error_type="structured_output_validation_error",
                retryable=False,
                diagnostics=(
                    {
                        "code": "structured_output_validation_error",
                        "instance_path": ["output"],
                        "schema_path": ["properties", "output", "type"],
                        "validator": "type",
                    },
                ),
                response_fingerprint="sha256:" + "1" * 64,
            )
        contract = compile_structured_output_contract(
            request.structured_output_schema_source(),
            schema_name=request.output_schema_name,
        )
        identity = StructuredOutputCacheIdentity(
            schema_name=contract.schema_name,
            schema_digest=contract.schema_digest,
            schema_revision=contract.schema_revision,
            schema_dialect=contract.dialect,
            typed_adapter_revision=contract.typed_adapter_revision,
            projection_digest="sha256:" + "2" * 64,
            projection_mode="native_strict",
            provider_capability_revision="recorded-v1",
        )
        value = {"output": "repaired"}
        return _managed_response(identity, value)


class _ManagedStreamClient:
    call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("structured stream test must not call complete")

    def stream(self, request: LLMRequest):  # type: ignore[no-untyped-def]
        self.call_count += 1
        identity = StructuredOutputCacheIdentity.from_request(request)
        assert identity is not None
        value = {"output": "streamed"}
        yield LLMStreamEvent(event_type="message_start")
        yield LLMStreamEvent(
            event_type="text_delta",
            text_delta='{"output":"streamed"}',
            metadata={"provisional": True},
        )
        yield LLMStreamEvent(
            event_type="message_complete",
            structured_output=value,
            metadata={
                "provisional": False,
                "structured_output_validation": managed_validation_metadata(
                    identity=identity,
                    value=value,
                ),
            },
        )


class _NeverCalledClient:
    call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        raise AssertionError("provider call must not occur")


def _managed_request(*, schema_revision: str) -> LLMRequest:
    contract = compile_structured_output_contract(
        _SCHEMA,
        schema_name="cache_output",
        schema_revision=schema_revision,
    )
    capability = ProviderStructuredOutputCapability(
        provider="provider",
        deployment="deployment",
        mode="native_strict",
        supported_dialect=LOCAL_STRUCTURED_OUTPUT_DIALECT,
        supported_keywords=structured_output_enforcement_keywords(
            contract.canonical_schema
        ),
        supports_local_refs=True,
        supports_stream_terminal_validation=True,
        revision="capability-v1",
        release=approved_structured_output_release(
            provider="provider",
            deployment="deployment",
            capability_revision="capability-v1",
        ),
    )
    projection = project_structured_output_contract(contract, capability)
    request = LLMRequest(
        messages=[{"role": "user", "content": "stable"}],
        temperature=0,
        output_schema=_SCHEMA,
        output_schema_name="cache_output",
        metadata=_cache_metadata(),
    )
    return request.with_structured_output_execution(
        contract=contract,
        projection=projection,
    )


def _managed_response(
    identity: StructuredOutputCacheIdentity,
    value: dict[str, object],
) -> LLMResponse:
    return LLMResponse(
        content='{"output":"accepted"}',
        structured_output=dict(value),
        metadata={
            "structured_output_validation": managed_validation_metadata(
                identity=identity,
                value=value,
            )
        },
    )


def _cache_runtime(cache: InMemoryLLMCache) -> LLMCacheRuntime:
    return LLMCacheRuntime(
        policy=LLMCachePolicy(
            mode=CacheMode.READ_WRITE,
            cacheable_task_types=("classify",),
            required_dependencies=("prompt_revision",),
        ),
        key_factory=LLMCacheKeyFactory(secret="0123456789abcdef"),
        store=cache,
        coordinator=cache,
    )


def _cache_metadata() -> dict[str, object]:
    return {
        "task_type": "classify",
        "llm_cache": {
            "scope": {
                "tenant_id": "tenant",
                "project_id": "project",
                "policy_scope": "policy",
            },
            "dependencies": {"prompt_revision": "prompt-v1"},
        },
    }


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_response_content(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "content"
        and isinstance(node.value, ast.Name)
        and node.value.id in {"response", "llm_response"}
    )
