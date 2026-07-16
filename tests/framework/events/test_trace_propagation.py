from __future__ import annotations

from collections.abc import Callable

import pytest

from framework.events import (
    AuxiliaryFailureAction,
    NoOpTraceAdapter,
    TraceContext,
    TraceParentFailureAction,
    TracePropagationError,
    TracePropagationPolicy,
    W3CTracePropagator,
)
import framework.events.propagation as propagation_module


TRACE_ID = "1" * 32
REMOTE_SPAN_ID = "2" * 16


def test_w3c_extract_child_and_inject_preserve_only_allowed_state() -> None:
    policy = TracePropagationPolicy(
        tracestate_allowlist=frozenset({"vendor"}),
        baggage_allowlist=frozenset({"request.kind"}),
    )
    propagator = W3CTracePropagator(policy)
    carrier = {
        "TraceParent": f"00-{TRACE_ID}-{REMOTE_SPAN_ID}-01",
        "TraceState": "vendor=opaque,untrusted=drop-me",
        "Baggage": "request.kind=research,tenant_id=must-not-propagate",
    }

    extracted = propagator.extract(
        carrier,
        run_id="run-propagation",
        workflow_id="wf-propagation",
    )
    child = extracted.child(step_id="step-propagation")
    outbound_seed = {"content-type": "application/json"}
    outbound = propagator.inject(
        child.context,
        outbound_seed,
        baggage=extracted.baggage,
    )

    assert extracted.accepted_remote is True
    assert extracted.context.is_remote is True
    assert extracted.context.trace_id == TRACE_ID
    assert extracted.context.span_id == REMOTE_SPAN_ID
    assert extracted.context.trace_flags == "01"
    assert extracted.context.tracestate == "vendor=opaque"
    assert dict(extracted.baggage) == {"request.kind": "research"}
    assert child.context.is_remote is False
    assert child.context.parent_span_id == REMOTE_SPAN_ID
    assert len(child.context.span_id) == 16
    assert outbound["traceparent"] == (
        f"00-{TRACE_ID}-{child.context.span_id}-01"
    )
    assert outbound["tracestate"] == "vendor=opaque"
    assert outbound["baggage"] == "request.kind=research"
    assert outbound_seed == {"content-type": "application/json"}
    assert "tenant_id" not in outbound["baggage"]


def test_invalid_or_untrusted_remote_context_restarts_without_business_identity() -> None:
    propagator = W3CTracePropagator()

    extracted = propagator.extract(
        {
            "traceparent": "00-not-a-trace-id-not-a-span-id-01",
            "baggage": "run_id=attacker-selected",
        },
        run_id="trusted-run-id",
    )

    assert extracted.restarted is True
    assert extracted.accepted_remote is False
    assert extracted.context.run_id == "trusted-run-id"
    assert extracted.context.is_injectable is True
    assert dict(extracted.baggage) == {}
    assert extracted.diagnostics == ("invalid_traceparent",)

    untrusted = W3CTracePropagator(
        TracePropagationPolicy(accept_remote_context=False)
    ).extract(
        {"traceparent": f"00-{TRACE_ID}-{REMOTE_SPAN_ID}-00"},
        run_id="trusted-run-id",
    )
    assert untrusted.restarted is True
    assert untrusted.context.trace_id != TRACE_ID
    assert untrusted.diagnostics == ("untrusted_remote_context",)


def test_traceparent_policy_can_reject_instead_of_restart() -> None:
    propagator = W3CTracePropagator(
        TracePropagationPolicy(
            invalid_traceparent_action=TraceParentFailureAction.REJECT,
        )
    )

    with pytest.raises(TracePropagationError, match="invalid_traceparent"):
        propagator.extract(
            {"traceparent": "malformed"},
            run_id="run-reject",
        )


def test_legacy_context_is_preserved_but_never_injected() -> None:
    legacy = TraceContext.root(
        run_id="run-legacy",
        trace_id="trace-events",
        span_id="workflow:run-legacy",
    )
    restored = TraceContext.from_dict(legacy.to_dict(redact=False))
    propagator = W3CTracePropagator()

    outbound = propagator.inject(
        restored,
        {
            "TraceParent": f"00-{TRACE_ID}-{REMOTE_SPAN_ID}-01",
            "tracestate": "vendor=stale",
            "baggage": "safe=stale",
            "content-type": "application/json",
        },
    )

    assert restored.trace_id == "trace-events"
    assert restored.span_id == "workflow:run-legacy"
    assert restored.has_legacy_identifiers is True
    assert restored.is_injectable is False
    assert outbound == {"content-type": "application/json"}


def test_auxiliary_headers_are_bounded_and_can_fail_closed() -> None:
    dropping = W3CTracePropagator(
        TracePropagationPolicy(
            tracestate_allowlist=frozenset({"vendor"}),
            baggage_allowlist=frozenset({"safe"}),
            max_tracestate_bytes=12,
            max_baggage_bytes=12,
        )
    )
    extracted = dropping.extract(
        {
            "traceparent": f"00-{TRACE_ID}-{REMOTE_SPAN_ID}-00",
            "tracestate": "vendor=value-that-is-too-large",
            "baggage": "safe=value-that-is-too-large",
        },
        run_id="run-bounded",
    )

    assert extracted.accepted_remote is True
    assert extracted.context.tracestate is None
    assert dict(extracted.baggage) == {}
    assert "tracestate_size_limit" in extracted.diagnostics
    assert "baggage_size_limit" in extracted.diagnostics

    rejecting = W3CTracePropagator(
        TracePropagationPolicy(
            invalid_auxiliary_action=AuxiliaryFailureAction.REJECT,
            max_baggage_bytes=8,
        )
    )
    with pytest.raises(TracePropagationError, match="baggage_size_limit"):
        rejecting.extract(
            {
                "traceparent": f"00-{TRACE_ID}-{REMOTE_SPAN_ID}-00",
                "baggage": "safe=oversized",
            },
            run_id="run-bounded",
        )


def test_extract_rejects_duplicate_case_insensitive_trace_headers() -> None:
    with pytest.raises(TracePropagationError, match="duplicate_traceparent"):
        W3CTracePropagator().extract(
            {
                "traceparent": f"00-{TRACE_ID}-{REMOTE_SPAN_ID}-00",
                "TraceParent": f"00-{TRACE_ID}-{'3' * 16}-00",
            },
            run_id="run-duplicate",
        )


def test_extracted_baggage_is_immutable() -> None:
    extracted = W3CTracePropagator(
        TracePropagationPolicy(baggage_allowlist=frozenset({"safe"}))
    ).extract(
        {
            "traceparent": f"00-{TRACE_ID}-{REMOTE_SPAN_ID}-00",
            "baggage": "safe=value",
        },
        run_id="run-baggage",
    )

    with pytest.raises(TypeError):
        extracted.baggage["safe"] = "changed"  # type: ignore[index]


def test_noop_adapter_preserves_trace_facade_when_otel_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing_otel() -> tuple[object, object, object]:
        raise ImportError("optional dependency unavailable")

    monkeypatch.setattr(propagation_module, "_load_otel_bindings", _missing_otel)

    adapter = propagation_module.default_trace_adapter()
    root = adapter.root(run_id="run-noop")
    child = adapter.child(root, step_id="step-noop")

    assert isinstance(adapter, NoOpTraceAdapter)
    assert adapter.available is False
    assert root.is_injectable is True
    assert child.trace_id == root.trace_id
    assert child.parent_span_id == root.span_id
    assert adapter.to_native_context(child) is None


@pytest.mark.parametrize(
    "factory",
    [
        lambda: NoOpTraceAdapter(),
        lambda: propagation_module.default_trace_adapter(),
    ],
)
def test_trace_adapter_never_changes_facade_identity(
    factory: Callable[[], object],
) -> None:
    adapter = factory()
    root = adapter.root(run_id="run-adapter")  # type: ignore[attr-defined]
    child = adapter.child(root, agent_id="agent-adapter")  # type: ignore[attr-defined]

    assert child.trace_id == root.trace_id
    assert child.parent_span_id == root.span_id
    assert child.agent_id == "agent-adapter"
