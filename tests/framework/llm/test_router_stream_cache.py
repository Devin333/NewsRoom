from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest

from framework.llm import (
    CacheMode,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    InMemoryLLMCache,
    InMemoryLLMCooldownTracker,
    LLMCooldownPolicy,
    LLMCacheKeyFactory,
    LLMCachePolicy,
    LLMCacheRuntime,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMRouteError,
    LLMRouter,
    LLMRouterEvent,
    LLMStreamAccumulator,
    LLMStreamEvent,
    LLMToolCall,
    ModelContextProfile,
    ModelDeployment,
    ModelRoute,
    SingleFlightAcquireResult,
    SingleFlightAcquireStatus,
    TokenUsage,
)


class _ScriptedStreamClient:
    def __init__(
        self,
        events: list[Any],
        *,
        trailing_error: BaseException | None = None,
    ) -> None:
        self.events = list(events)
        self.trailing_error = trailing_error
        self.stream_calls = 0
        self.produced: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("stream cache tests must not call complete")

    def stream(self, request: LLMRequest) -> Iterator[Any]:
        self.stream_calls += 1
        for event in self.events:
            event_type = (
                event.get("event_type")
                if isinstance(event, dict)
                else getattr(event, "event_type", type(event).__name__)
            )
            self.produced.append(str(event_type))
            yield event
        if self.trailing_error is not None:
            raise self.trailing_error


class _RecordingStore(InMemoryLLMCache):
    def __init__(self, *, fail_put: bool = False) -> None:
        super().__init__(max_entries=20, default_ttl_seconds=60)
        self.fail_put = fail_put
        self.put_count = 0
        self.acquire_count = 0
        self.release_count = 0

    def put(self, key, entry, *, ttl_seconds):  # type: ignore[no-untyped-def]
        self.put_count += 1
        if self.fail_put:
            raise RuntimeError("simulated cache backend failure")
        return super().put(key, entry, ttl_seconds=ttl_seconds)

    def acquire_singleflight(  # type: ignore[no-untyped-def]
        self,
        key,
        *,
        owner_token,
        ttl_seconds,
    ):
        self.acquire_count += 1
        return super().acquire_singleflight(
            key,
            owner_token=owner_token,
            ttl_seconds=ttl_seconds,
        )

    def release_singleflight(self, lease):  # type: ignore[no-untyped-def]
        self.release_count += 1
        return super().release_singleflight(lease)


class _BusyStore(_RecordingStore):
    def acquire_singleflight(  # type: ignore[no-untyped-def]
        self,
        key,
        *,
        owner_token,
        ttl_seconds,
    ):
        self.acquire_count += 1
        return SingleFlightAcquireResult(status=SingleFlightAcquireStatus.BUSY)


def _profile() -> ModelContextProfile:
    return ModelContextProfile(
        deployment_id="primary",
        provider="test",
        model="model",
        physical_context_window_tokens=32_000,
        max_output_tokens=1_024,
        default_output_tokens=128,
        tokenizer_family="test",
        tokenizer_revision="test-v1",
        normalizer_revision="canonical-request-v1",
        profile_revision="profile-v1",
        operational_input_fraction=1.0,
        allow_conservative_fallback=True,
    )


def _request(
    *,
    content: str = "cache this stream",
    deadline_monotonic: float | None = None,
) -> LLMRequest:
    cache_envelope: dict[str, Any] = {
        "scope": {
            "tenant_id": "tenant-a",
            "project_id": "project-a",
            "policy_scope": "policy-v1",
        },
        "dependencies": {"prompt_revision": "prompt-v1"},
    }
    if deadline_monotonic is not None:
        cache_envelope["deadline_monotonic"] = deadline_monotonic
    return LLMRequest(
        messages=[{"role": "user", "content": content}],
        temperature=0,
        metadata={
            "task_type": "classify",
            "llm_cache": cache_envelope,
        },
    )


def _runtime(
    store: InMemoryLLMCache,
    *,
    replay_chunk_size: int = 3,
    max_entry_bytes: int = 1_048_576,
    clock=None,  # type: ignore[no-untyped-def]
    sleep=None,  # type: ignore[no-untyped-def]
    singleflight_wait_timeout_ms: int = 2_500,
    singleflight_poll_interval_ms: int = 50,
) -> LLMCacheRuntime:
    return LLMCacheRuntime(
        policy=LLMCachePolicy(
            mode=CacheMode.READ_WRITE,
            ttl_seconds=60,
            max_entry_bytes=max_entry_bytes,
            cacheable_task_types=("classify",),
            required_dependencies=("prompt_revision",),
        ),
        key_factory=LLMCacheKeyFactory(secret="0123456789abcdef"),
        store=store,
        coordinator=store,
        replay_chunk_size=replay_chunk_size,
        clock=clock,
        sleep=sleep,
        singleflight_wait_timeout_ms=singleflight_wait_timeout_ms,
        singleflight_poll_interval_ms=singleflight_poll_interval_ms,
    )


def _router(
    client: _ScriptedStreamClient,
    store: InMemoryLLMCache,
    *,
    event_sink=None,  # type: ignore[no-untyped-def]
    budget: GlobalBudgetTracker | None = None,
    cooldown: InMemoryLLMCooldownTracker | None = None,
    replay_chunk_size: int = 3,
    max_entry_bytes: int = 1_048_576,
    cache_clock=None,  # type: ignore[no-untyped-def]
    cache_sleep=None,  # type: ignore[no-untyped-def]
    singleflight_wait_timeout_ms: int = 2_500,
    singleflight_poll_interval_ms: int = 50,
) -> LLMRouter:
    return LLMRouter(
        routes=[ModelRoute(route_id="route", primary_deployment_id="primary")],
        deployments=[
            ModelDeployment(
                deployment_id="primary",
                provider="test",
                model="model",
                client=client,
                context_profile=_profile(),
            )
        ],
        cache_runtime=_runtime(
            store,
            replay_chunk_size=replay_chunk_size,
            max_entry_bytes=max_entry_bytes,
            clock=cache_clock,
            sleep=cache_sleep,
            singleflight_wait_timeout_ms=singleflight_wait_timeout_ms,
            singleflight_poll_interval_ms=singleflight_poll_interval_ms,
        ),
        event_sink=event_sink,
        global_budget_tracker=budget,
        cooldown_tracker=cooldown,
    )


def _text_events(
    content: str,
    *,
    usage: TokenUsage | None = None,
) -> list[LLMStreamEvent]:
    events = [
        LLMStreamEvent(event_type="message_start"),
        LLMStreamEvent(event_type="text_delta", text_delta=content),
    ]
    if usage is not None:
        events.append(LLMStreamEvent(event_type="usage_delta", usage_delta=usage))
    events.append(LLMStreamEvent(event_type="message_complete"))
    return events


def _consume_through_terminal(
    stream: Iterator[LLMStreamEvent],
) -> list[LLMStreamEvent]:
    events: list[LLMStreamEvent] = []
    while True:
        event = next(stream)
        events.append(event)
        if event.event_type == "message_complete":
            return events


def _stream_outcome(events: list[LLMRouterEvent]) -> LLMRouterEvent:
    return next(
        event
        for event in reversed(events)
        if event.event_type
        in {
            "llm_cache_stream_not_written",
            "llm_cache_stream_replay_completed",
            "llm_cache_stream_replay_interrupted",
            "llm_cache_write_failed",
            "llm_cache_write_succeeded",
        }
    )


def test_stream_writes_only_after_terminal_is_fully_exhausted() -> None:
    store = _RecordingStore()
    client = _ScriptedStreamClient(
        _text_events("incremental", usage=TokenUsage(input_tokens=7, output_tokens=2))
    )
    router = _router(client, store)
    stream = router.stream("route", _request())

    events = _consume_through_terminal(stream)

    assert [event.event_type for event in events] == [
        "message_start",
        "text_delta",
        "usage_delta",
        "message_complete",
    ]
    assert store.put_count == 0
    assert store.entry_count == 0
    assert client.produced == [
        "message_start",
        "text_delta",
        "usage_delta",
        "message_complete",
    ]

    with pytest.raises(StopIteration):
        next(stream)

    assert store.put_count == 1
    assert store.entry_count == 1
    assert store.release_count == 1


def test_close_after_terminal_releases_lease_without_writing() -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    client = _ScriptedStreamClient(_text_events("complete but abandoned"))
    router = _router(client, store, event_sink=recorded.append)
    stream = router.stream("route", _request())

    _consume_through_terminal(stream)
    stream.close()

    assert store.acquire_count == 1
    assert store.release_count == 1
    assert store.put_count == 0
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.event_type == "llm_cache_stream_not_written"
    assert outcome.metadata["reason"] == "consumer_closed"


def test_cache_hit_replay_is_bounded_isolated_and_avoids_provider_state() -> None:
    store = _RecordingStore()
    client = _ScriptedStreamClient(
        _text_events(
            "abcdefgh",
            usage=TokenUsage(
                input_tokens=11,
                output_tokens=8,
                estimated_cost_usd=0.25,
            ),
        )
    )
    budget = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=1))
    cooldown = InMemoryLLMCooldownTracker(
        LLMCooldownPolicy(
            cooldown_on_rate_limit_seconds=60,
            failure_count_threshold=1,
        )
    )
    router = _router(
        client,
        store,
        budget=budget,
        cooldown=cooldown,
        replay_chunk_size=2,
    )
    request = _request()

    list(router.stream("route", request))
    cooldown.record_failure(
        "primary",
        LLMProviderError(
            "rate limited",
            provider="test",
            model="model",
            deployment_id="primary",
            error_type="rate_limit",
            retryable=True,
            status_code=429,
        ),
    )
    cooldown_before = cooldown.state("primary")

    replay = list(router.stream("route", request))

    assert client.stream_calls == 1
    assert budget.usage.llm_calls == 1
    assert budget.usage.token_usage == TokenUsage(input_tokens=11, output_tokens=8)
    assert cooldown.state("primary") == cooldown_before
    assert [event.event_type for event in replay].count("message_start") == 1
    assert [event.event_type for event in replay].count("message_complete") == 1
    chunks = [
        event.text_delta or "" for event in replay if event.event_type == "text_delta"
    ]
    assert "".join(chunks) == "abcdefgh"
    assert all(0 < len(chunk) <= 2 for chunk in chunks)

    replay_usage = next(event for event in replay if event.event_type == "usage_delta")
    assert replay_usage.usage_delta == TokenUsage()
    assert replay_usage.metadata["source_usage"]["total_tokens"] == 19
    terminal = replay[-1]
    assert terminal.metadata["llm_provider_call"] is False
    assert terminal.metadata["llm_provider_usage"]["total_tokens"] == 0

    accumulator = LLMStreamAccumulator()
    for event in replay:
        accumulator.add_event(event)
    replayed_response = accumulator.to_response()
    assert replayed_response.content == "abcdefgh"
    assert replayed_response.usage == TokenUsage()

    replay[0].metadata["provider"] = "mutated"
    next_replay = list(router.stream("route", request))
    assert next_replay[0].metadata["provider"] == "test"


def test_empty_cached_response_replays_only_legal_terminal_sequence() -> None:
    store = _RecordingStore()
    client = _ScriptedStreamClient(
        [
            LLMStreamEvent(event_type="message_start"),
            LLMStreamEvent(event_type="message_complete"),
        ]
    )
    router = _router(client, store)
    request = _request()

    list(router.stream("route", request))
    replay = list(router.stream("route", request))

    assert [event.event_type for event in replay] == [
        "message_start",
        "message_complete",
    ]


def test_expired_caller_deadline_refuses_replay_without_provider_call() -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    now = [10.0]
    client = _ScriptedStreamClient(_text_events("deadline-bound"))
    router = _router(
        client,
        store,
        event_sink=recorded.append,
        cache_clock=lambda: now[0],
    )
    request = _request(deadline_monotonic=20.0)

    list(router.stream("route", request))
    now[0] = 21.0

    with pytest.raises(LLMRouteError) as raised:
        list(router.stream("route", request))

    assert raised.value.error_type == "caller_deadline_exceeded"
    assert client.stream_calls == 1
    outcome = _stream_outcome(recorded)
    assert outcome.event_type == "llm_cache_stream_replay_interrupted"
    assert outcome.metadata["reason"] == "caller_deadline_exceeded"


def test_deadline_expiring_during_singleflight_wait_blocks_provider_call() -> None:
    store = _BusyStore()
    recorded: list[LLMRouterEvent] = []
    now = [10.0]

    def advance(seconds: float) -> None:
        now[0] += seconds

    client = _ScriptedStreamClient(_text_events("must not run"))
    router = _router(
        client,
        store,
        event_sink=recorded.append,
        cache_clock=lambda: now[0],
        cache_sleep=advance,
        singleflight_wait_timeout_ms=100,
        singleflight_poll_interval_ms=50,
    )

    with pytest.raises(LLMRouteError) as raised:
        list(
            router.stream(
                "route",
                _request(deadline_monotonic=10.05),
            )
        )

    assert raised.value.error_type == "caller_deadline_exceeded"
    assert client.stream_calls == 0
    assert store.put_count == 0
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.event_type == "llm_cache_stream_not_written"
    assert outcome.metadata["reason"] == "caller_deadline_exceeded"
    assert outcome.metadata["phase"] == "cache_admission"


def test_deadline_expiring_after_terminal_prevents_cache_write() -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    now = [10.0]
    router = _router(
        _ScriptedStreamClient(_text_events("deadline crossed")),
        store,
        event_sink=recorded.append,
        cache_clock=lambda: now[0],
    )
    stream = router.stream(
        "route",
        _request(deadline_monotonic=20.0),
    )

    _consume_through_terminal(stream)
    now[0] = 21.0

    with pytest.raises(StopIteration):
        next(stream)

    assert store.put_count == 0
    assert store.entry_count == 0
    assert store.release_count == 1
    outcome = _stream_outcome(recorded)
    assert outcome.event_type == "llm_cache_stream_not_written"
    assert outcome.metadata["reason"] == "caller_deadline_exceeded"
    assert outcome.metadata["phase"] == "post_stream_exhaustion"


@pytest.mark.parametrize(
    "first_event",
    [
        {"event_type": "text_delta", "text_delta": ""},
        {"event_type": "usage_delta"},
    ],
)
def test_ignored_empty_delta_before_start_is_delivered_but_not_cached(
    first_event: dict[str, Any],
) -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    router = _router(
        _ScriptedStreamClient(
            [
                first_event,
                {"event_type": "message_start"},
                {"event_type": "message_complete"},
            ]
        ),
        store,
        event_sink=recorded.append,
    )

    delivered = list(router.stream("route", _request()))

    assert delivered[-1].event_type == "message_complete"
    assert store.put_count == 0
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.metadata["reason"] == "invalid_stream_protocol"
    assert outcome.metadata["protocol_reason"] == "event_before_message_start"


@pytest.mark.parametrize(
    ("events", "expected_reason"),
    [
        (
            [
                {"event_type": "message_start"},
                {"event_type": "message_start"},
            ],
            "invalid_stream_protocol",
        ),
        (
            [
                {"event_type": "message_start"},
                {"event_type": "text_delta", "text_delta": "partial"},
            ],
            "incomplete_stream",
        ),
        (
            [
                {"event_type": "message_start"},
                {"event_type": "message_complete"},
                {"event_type": "message_complete"},
            ],
            "invalid_stream_protocol",
        ),
        (
            [
                {"event_type": "message_start"},
                {"event_type": "message_complete"},
                {"event_type": "text_delta", "text_delta": "late"},
            ],
            "invalid_stream_protocol",
        ),
    ],
)
def test_invalid_stream_protocol_never_writes(
    events: list[dict[str, Any]],
    expected_reason: str,
) -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    router = _router(
        _ScriptedStreamClient(events),
        store,
        event_sink=recorded.append,
    )

    with pytest.raises(LLMRouteError):
        list(router.stream("route", _request()))

    assert store.put_count == 0
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.event_type == "llm_cache_stream_not_written"
    assert outcome.metadata["reason"] == expected_reason


def test_tool_stream_is_delivered_but_never_cached_or_exposed_in_events() -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    secret_arguments = '{"credential":"tool-secret-value"}'
    client = _ScriptedStreamClient(
        [
            LLMStreamEvent(event_type="message_start"),
            LLMStreamEvent(
                event_type="tool_call_start",
                tool_call_delta={
                    "tool_call_id": "call-1",
                    "tool_name": "lookup",
                    "arguments": secret_arguments,
                },
            ),
            LLMStreamEvent(event_type="message_complete"),
        ]
    )
    router = _router(client, store, event_sink=recorded.append)

    delivered = list(router.stream("route", _request(content="raw-prompt-secret")))

    assert [event.event_type for event in delivered] == [
        "message_start",
        "tool_call_start",
        "message_complete",
    ]
    assert store.put_count == 0
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.metadata["reason"] == "tool_event_present"
    event_payload = " ".join(str(event.to_dict()) for event in recorded)
    assert "raw-prompt-secret" not in event_payload
    assert "tool-secret-value" not in event_payload
    assert "tenant-a" not in event_payload


@pytest.mark.parametrize("payload_event_type", ["text_delta", "message_complete"])
def test_tool_payload_on_non_tool_event_never_populates_cache(
    payload_event_type: str,
) -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    tool_secret = "embedded-tool-secret"
    if payload_event_type == "text_delta":
        payload_event = LLMStreamEvent(
            event_type="text_delta",
            text_delta="safe text",
            tool_call_delta={"arguments": tool_secret},
        )
        events = [
            LLMStreamEvent(event_type="message_start"),
            payload_event,
            LLMStreamEvent(event_type="message_complete"),
        ]
    else:
        payload_event = LLMStreamEvent(
            event_type="message_complete",
            tool_call=LLMToolCall(
                tool_call_id="call-1",
                tool_name="lookup",
                arguments={"credential": tool_secret},
            ),
        )
        events = [
            LLMStreamEvent(event_type="message_start"),
            LLMStreamEvent(event_type="text_delta", text_delta="safe text"),
            payload_event,
        ]
    router = _router(
        _ScriptedStreamClient(events),
        store,
        event_sink=recorded.append,
    )

    delivered = list(router.stream("route", _request()))

    assert delivered[-1].event_type == "message_complete"
    assert store.put_count == 0
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.metadata["reason"] == "tool_event_present"
    event_payload = " ".join(str(event.to_dict()) for event in recorded)
    assert tool_secret not in event_payload


def test_provider_error_after_delta_never_writes_partial_response() -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    client = _ScriptedStreamClient(
        [
            LLMStreamEvent(event_type="message_start"),
            LLMStreamEvent(event_type="text_delta", text_delta="partial"),
        ],
        trailing_error=LLMProviderError(
            "provider interrupted",
            provider="test",
            model="model",
            error_type="provider_connection_error",
            retryable=True,
        ),
    )
    router = _router(client, store, event_sink=recorded.append)

    with pytest.raises(LLMRouteError):
        list(router.stream("route", _request()))

    assert store.put_count == 0
    assert store.entry_count == 0
    assert _stream_outcome(recorded).metadata["reason"] == "source_interrupted"


def test_provider_error_after_terminal_records_terminal_invalidation() -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    client = _ScriptedStreamClient(
        _text_events("terminal was visible"),
        trailing_error=LLMProviderError(
            "provider failed after terminal",
            provider="test",
            model="model",
            error_type="provider_connection_error",
            retryable=True,
        ),
    )
    router = _router(client, store, event_sink=recorded.append)
    stream = router.stream("route", _request())

    delivered = _consume_through_terminal(stream)
    with pytest.raises(LLMRouteError):
        next(stream)

    assert delivered[-1].event_type == "message_complete"
    assert store.put_count == 0
    assert store.entry_count == 0
    invalidation = next(
        event
        for event in recorded
        if event.event_type == "llm_stream_terminal_invalidated"
    )
    assert invalidation.metadata["reason"] == "source_interrupted_after_message_complete"


def test_cache_backend_write_failure_cannot_fail_completed_stream() -> None:
    store = _RecordingStore(fail_put=True)
    recorded: list[LLMRouterEvent] = []
    router = _router(
        _ScriptedStreamClient(_text_events("provider success")),
        store,
        event_sink=recorded.append,
    )

    delivered = list(router.stream("route", _request()))

    assert delivered[-1].event_type == "message_complete"
    assert store.put_count == 1
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.event_type == "llm_cache_write_failed"
    assert outcome.metadata["reason"] == "backend_error"


def test_invalid_accumulated_output_contract_is_delivered_but_not_cached() -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    router = _router(
        _ScriptedStreamClient(_text_events("not-json")),
        store,
        event_sink=recorded.append,
    )
    request = replace(_request(), response_format="json")

    delivered = list(router.stream("route", request))

    assert delivered[-1].event_type == "message_complete"
    assert store.put_count == 0
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.event_type == "llm_cache_stream_not_written"
    assert outcome.metadata["reason"] == "output_contract_validation_failed"


def test_oversized_accumulated_response_is_delivered_without_cache_write() -> None:
    store = _RecordingStore()
    recorded: list[LLMRouterEvent] = []
    router = _router(
        _ScriptedStreamClient(_text_events("x" * 2_000)),
        store,
        event_sink=recorded.append,
        max_entry_bytes=128,
    )

    delivered = list(router.stream("route", _request()))

    assert delivered[-1].event_type == "message_complete"
    assert store.put_count == 0
    assert store.entry_count == 0
    outcome = _stream_outcome(recorded)
    assert outcome.event_type == "llm_cache_write_failed"
    assert outcome.metadata["reason"] == "entry_too_large"
