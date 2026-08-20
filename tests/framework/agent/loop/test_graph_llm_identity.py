from __future__ import annotations

from collections.abc import Iterator

import pytest

from framework.agent.loop import AgentLoop
from framework.agent.loop.events import AgentLoopEventRecorder
from framework.agent.models import AgentLoopMetrics, AgentLoopPolicy, AgentSpec
from framework.llm import (
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    TokenUsage,
)
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.tool import ToolExecutor, ToolRegistry


IDENTITY = GraphExecutionIdentity(
    run_id="run-agent-identity",
    graph_id="graph-agent",
    graph_version="v1",
    graph_ref="graph-agent@v1",
    graph_checksum="sha256:" + "a" * 64,
    node_id="agent-node",
    node_instance_id="agent-node-instance",
    activity_id="agent-activity",
    attempt=1,
)


class _DirectClient:
    def __init__(
        self,
        response_identity: GraphExecutionIdentity | None,
        event_identities: tuple[GraphExecutionIdentity | None, ...] = (),
    ) -> None:
        self.response_identity = response_identity
        self.event_identities = event_identities

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content="ok",
            usage=TokenUsage(output_tokens=1),
            execution_identity=self.response_identity,
        )

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamEvent]:
        identities = self.event_identities or (self.response_identity,) * 4
        yield LLMStreamEvent(
            event_type="message_start",
            execution_identity=identities[0],
        )
        yield LLMStreamEvent(
            event_type="text_delta",
            text_delta="ok",
            execution_identity=identities[1],
        )
        yield LLMStreamEvent(
            event_type="usage_delta",
            usage_delta=TokenUsage(output_tokens=1),
            execution_identity=identities[2],
        )
        yield LLMStreamEvent(
            event_type="message_complete",
            execution_identity=identities[3],
        )


def _agent(*, streaming: bool) -> AgentSpec:
    return AgentSpec(
        agent_id="agent-identity",
        name="Identity Agent",
        instructions="Return the answer.",
        loop_policy=AgentLoopPolicy(llm_streaming_enabled=streaming),
    )


def _loop(client: _DirectClient) -> AgentLoop:
    return AgentLoop(
        llm_client=client,
        tool_executor=ToolExecutor(ToolRegistry()),
    )


def _events() -> AgentLoopEventRecorder:
    return AgentLoopEventRecorder(
        agent_id="agent-identity",
        run_id=IDENTITY.run_id,
    )


def test_graph_direct_complete_rejects_missing_response_identity() -> None:
    with pytest.raises(ValueError, match="Graph identity"):
        _loop(_DirectClient(None))._complete_llm_request(
            LLMRequest(messages=[], execution_identity=IDENTITY),
            agent=_agent(streaming=False),
            iteration=1,
            metrics=AgentLoopMetrics(),
            events=_events(),
        )


def test_graph_direct_stream_rejects_missing_event_identity() -> None:
    with pytest.raises(ValueError, match="Graph identity"):
        _loop(
            _DirectClient(
                IDENTITY,
                event_identities=(IDENTITY, None, IDENTITY, IDENTITY),
            )
        )._complete_llm_request(
            LLMRequest(messages=[], execution_identity=IDENTITY),
            agent=_agent(streaming=True),
            iteration=1,
            metrics=AgentLoopMetrics(),
            events=_events(),
        )


def test_graph_direct_stream_rejects_cross_activity_event_identity() -> None:
    other = GraphExecutionIdentity(
        run_id=IDENTITY.run_id,
        graph_id=IDENTITY.graph_id,
        graph_version=IDENTITY.graph_version,
        graph_ref=IDENTITY.graph_ref,
        graph_checksum=IDENTITY.graph_checksum,
        node_id=IDENTITY.node_id,
        node_instance_id="other-node-instance",
        activity_id=IDENTITY.activity_id,
        attempt=IDENTITY.attempt,
    )

    with pytest.raises(ValueError, match="Graph identity"):
        _loop(
            _DirectClient(
                IDENTITY,
                event_identities=(IDENTITY, other, IDENTITY, IDENTITY),
            )
        )._complete_llm_request(
            LLMRequest(messages=[], execution_identity=IDENTITY),
            agent=_agent(streaming=True),
            iteration=1,
            metrics=AgentLoopMetrics(),
            events=_events(),
        )
