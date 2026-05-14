from __future__ import annotations

from typing import Any

from core.framework.agent_loop.diagnostics import (
    AgentLoopDiagnosticsBuilder,
    AgentLoopStallDetector,
    StallDetection,
    max_iterations_detection,
)
from core.framework.agent_loop.events import AgentLoopEventRecorder
from core.framework.agent_loop.judge import OutputJudge
from core.framework.agent_loop.models import (
    AgentAction,
    AgentLoopMetrics,
    AgentLoopResult,
    AgentLoopStatus,
    AgentLoopStopReason,
    AgentSpec,
    JudgeDecision,
    JudgeVerdict,
    LLMCallArtifact,
)
from core.framework.agent_loop.parser import AgentActionParser
from core.framework.agent_loop.prompt import PromptBuilder
from core.framework.agent_loop.trace import AgentLoopTrace, IterationTrace
from core.framework.llm import (
    GlobalBudgetExceededError,
    GlobalBudgetTracker,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMStreamAccumulator,
)
from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolObservation,
    ToolPolicy,
    ToolResult,
    ToolStatus,
)


class AgentLoop:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        tool_executor: ToolExecutor,
        prompt_builder: PromptBuilder | None = None,
        action_parser: AgentActionParser | None = None,
        output_judge: OutputJudge | None = None,
        global_budget_tracker: GlobalBudgetTracker | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tool_executor = tool_executor
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._action_parser = action_parser or AgentActionParser()
        self._output_judge = output_judge or OutputJudge()
        self._global_budget_tracker = global_budget_tracker

    def run(
        self,
        agent: AgentSpec,
        inputs: dict[str, Any],
        tools: list[dict[str, Any]],
    ) -> AgentLoopResult:
        metrics = AgentLoopMetrics()
        events = AgentLoopEventRecorder(agent_id=agent.agent_id)
        trace = AgentLoopTrace(agent_id=agent.agent_id)
        diagnostics = AgentLoopDiagnosticsBuilder(agent_id=agent.agent_id, trace=trace)
        stall_detector = AgentLoopStallDetector(agent.loop_policy)

        events.started()
        feedback: str | None = None
        tool_observations: list[ToolObservation] = []
        called_tools: list[str] = []
        last_verdict: JudgeVerdict | None = None
        llm_call_artifacts: list[LLMCallArtifact] = []
        judge_retries = 0
        parser_errors = 0

        for iteration in range(1, agent.loop_policy.max_iterations + 1):
            metrics.iterations = iteration
            iteration_trace = trace.start_iteration(
                iteration,
                feedback=feedback,
                tool_observation_count_before=len(tool_observations),
                tools_available=_tool_names(tools),
            )
            events.iteration_started(
                iteration=iteration,
                feedback=feedback,
                tool_observation_count=len(tool_observations),
                tools_available=_tool_names(tools),
            )

            request = self._prompt_builder.build(
                agent,
                inputs,
                feedback=feedback,
                tool_observations=[
                    observation.to_dict()
                    for observation in tool_observations
                ],
                tools=tools,
            )
            try:
                self._check_global_budget_before_llm_call(metrics)
            except GlobalBudgetExceededError as exc:
                trace.mark_stop_candidate(
                    iteration_trace,
                    AgentLoopStopReason.GLOBAL_BUDGET_EXCEEDED.value,
                )
                return self._global_budget_exceeded_result(
                    agent=agent,
                    metrics=metrics,
                    events=events,
                    trace=trace,
                    diagnostics=diagnostics,
                    iterations=iteration,
                    exc=exc,
                    llm_call_artifacts=llm_call_artifacts,
                )
            try:
                response = self._complete_llm_request(
                    request,
                    agent=agent,
                    iteration=iteration,
                    metrics=metrics,
                    events=events,
                )
            except GlobalBudgetExceededError as exc:
                metrics.llm_error_count += 1
                trace.record_llm_error(iteration_trace, exc)
                events.llm_failed(iteration=iteration, exc=exc)
                return self._global_budget_exceeded_result(
                    agent=agent,
                    metrics=metrics,
                    events=events,
                    trace=trace,
                    diagnostics=diagnostics,
                    iterations=iteration,
                    exc=exc,
                    llm_call_artifacts=llm_call_artifacts,
                )
            except Exception as exc:
                if _is_global_budget_exception(exc):
                    metrics.llm_error_count += 1
                    trace.record_llm_error(iteration_trace, exc)
                    events.llm_failed(iteration=iteration, exc=exc)
                    return self._global_budget_exceeded_result(
                        agent=agent,
                        metrics=metrics,
                        events=events,
                        trace=trace,
                        diagnostics=diagnostics,
                        iterations=iteration,
                        exc=exc,
                        llm_call_artifacts=llm_call_artifacts,
                    )
                metrics.llm_error_count += 1
                trace.record_llm_error(iteration_trace, exc)
                events.llm_failed(iteration=iteration, exc=exc)
                return self._failed_result(
                    agent=agent,
                    metrics=metrics,
                    events=events,
                    trace=trace,
                    diagnostics=diagnostics,
                    iterations=iteration,
                    stop_reason=AgentLoopStopReason.LLM_FAILED,
                    error=str(exc),
                    llm_call_artifacts=llm_call_artifacts,
                )

            llm_trace = trace.record_llm_call(iteration_trace, response)
            llm_call_artifacts.append(
                _llm_call_artifact(
                    agent=agent,
                    iteration=iteration,
                    request=request,
                    response=response,
                )
            )
            metrics.llm_calls += 1
            metrics.add_usage(response.usage)
            try:
                self._record_global_budget_call(metrics, response)
            except GlobalBudgetExceededError as exc:
                trace.mark_stop_candidate(
                    iteration_trace,
                    AgentLoopStopReason.GLOBAL_BUDGET_EXCEEDED.value,
                )
                events.llm_call(
                    iteration=iteration,
                    token_usage=response.usage.to_dict(),
                    response_chars=llm_trace.response_chars,
                    provider=llm_trace.provider,
                    model=llm_trace.model,
                    route_id=llm_trace.route_id,
                    deployment_id=llm_trace.deployment_id,
                    fallback_used=llm_trace.fallback_used,
                    fallback_count=llm_trace.fallback_count,
                    router_event_count=llm_trace.router_event_count,
                )
                return self._global_budget_exceeded_result(
                    agent=agent,
                    metrics=metrics,
                    events=events,
                    trace=trace,
                    diagnostics=diagnostics,
                    iterations=iteration,
                    exc=exc,
                    llm_call_artifacts=llm_call_artifacts,
                )
            events.llm_call(
                iteration=iteration,
                token_usage=response.usage.to_dict(),
                response_chars=llm_trace.response_chars,
                provider=llm_trace.provider,
                model=llm_trace.model,
                route_id=llm_trace.route_id,
                deployment_id=llm_trace.deployment_id,
                fallback_used=llm_trace.fallback_used,
                fallback_count=llm_trace.fallback_count,
                router_event_count=llm_trace.router_event_count,
            )

            try:
                action = self._action_parser.parse(response.content)
            except Exception as exc:
                parser_errors += 1
                metrics.parser_errors += 1
                feedback = f"parser error: {exc}"
                parser_error = trace.record_parser_error(
                    iteration_trace,
                    exc=exc,
                    content=response.content,
                    max_preview_chars=agent.loop_policy.max_trace_preview_chars,
                )
                last_verdict = JudgeVerdict(
                    decision=JudgeDecision.RETRY,
                    confidence=0.0,
                    feedback=feedback,
                    schema_errors=[str(exc)],
                )
                events.parser_error(
                    iteration=iteration,
                    error_type=parser_error.error_type,
                    error_message=parser_error.error_message,
                    parser_errors=parser_errors,
                    max_parser_errors=agent.loop_policy.max_parser_errors,
                )
                detection = stall_detector.after_parser_error(
                    trace=trace,
                    iteration=iteration,
                    parser_errors=parser_errors,
                )
                if detection.stalled:
                    trace.mark_stop_candidate(
                        iteration_trace,
                        detection.stop_reason.value if detection.stop_reason else "parser_error",
                    )
                    return self._retry_exhausted_result(
                        agent=agent,
                        metrics=metrics,
                        events=events,
                        trace=trace,
                        diagnostics=diagnostics,
                        iterations=iteration,
                        verdict=last_verdict,
                        stop_reason=AgentLoopStopReason.PARSER_RETRY_EXHAUSTED,
                        detection=detection,
                        llm_call_artifacts=llm_call_artifacts,
                    )
                continue

            parser_errors = 0
            action_trace = trace.record_action(
                iteration_trace,
                action_type=action.action_type,
                tool_name=action.tool_name,
                output=action.output,
            )
            events.action_parsed(
                iteration=iteration,
                action_type=action_trace.action_type,
                tool_name=action_trace.tool_name,
                output_keys=action_trace.output_keys,
            )

            if action.action_type == "tool_call":
                tool_result = self._handle_tool_action(
                    agent=agent,
                    inputs=inputs,
                    action=action,
                    metrics=metrics,
                    events=events,
                    trace=trace,
                    diagnostics=diagnostics,
                    stall_detector=stall_detector,
                    iteration_trace=iteration_trace,
                    tool_observations=tool_observations,
                    called_tools=called_tools,
                    llm_call_artifacts=llm_call_artifacts,
                )
                if isinstance(tool_result, AgentLoopResult):
                    return tool_result
                feedback = tool_result
                continue

            verdict = self._output_judge.judge(
                agent=agent,
                action=action,
                called_tools=called_tools,
                inputs=inputs,
            )
            last_verdict = verdict
            trace.record_judge(iteration_trace, verdict)
            verdict_result = self._handle_verdict(
                agent=agent,
                action=action,
                metrics=metrics,
                events=events,
                trace=trace,
                diagnostics=diagnostics,
                stall_detector=stall_detector,
                iteration_trace=iteration_trace,
                verdict=verdict,
                judge_retries=judge_retries,
                via_tool=None,
                llm_call_artifacts=llm_call_artifacts,
            )
            if isinstance(verdict_result, AgentLoopResult):
                return verdict_result
            judge_retries, feedback = verdict_result

        detection = max_iterations_detection(metrics.iterations, agent.loop_policy)
        return self._stalled_result(
            agent=agent,
            metrics=metrics,
            events=events,
            trace=trace,
            diagnostics=diagnostics,
            iterations=metrics.iterations,
            verdict=last_verdict,
            detection=detection,
            llm_call_artifacts=llm_call_artifacts,
        )

    def _handle_tool_action(
        self,
        *,
        agent: AgentSpec,
        inputs: dict[str, Any],
        action: AgentAction,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        stall_detector: AgentLoopStallDetector,
        iteration_trace: IterationTrace,
        tool_observations: list[ToolObservation],
        called_tools: list[str],
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> str | AgentLoopResult | None:
        iteration = iteration_trace.iteration
        tool_policy = agent.resolved_tool_policy()
        tool_call = ToolCall(
            tool_name=action.tool_name or "",
            arguments=action.tool_args,
            requested_by_agent_id=agent.agent_id,
        )
        budget_blocked = metrics.tool_calls >= _max_tool_calls_per_agent(tool_policy)
        if budget_blocked:
            observation = _blocked_tool_budget_observation(tool_call, tool_policy)
            events.tool_budget_blocked(
                iteration=iteration,
                tool_name=tool_call.tool_name,
                max_tool_calls=_max_tool_calls_per_agent(tool_policy),
            )
        else:
            observation = self._execute_tool(tool_call, tool_policy)

        tool_observations.append(observation)
        called_tools.append(observation.call.tool_name)
        metrics.tool_calls += 1
        metrics.record_tool_status(observation.status, elapsed_ms=observation.elapsed_ms)
        events.tool_call(
            iteration=iteration,
            tool_name=observation.call.tool_name,
            call_id=observation.call.call_id,
        )
        events.tool_observation(iteration=iteration, observation=observation.to_dict())
        tool_trace = trace.record_tool_call(
            iteration_trace,
            observation,
            max_preview_chars=agent.loop_policy.max_trace_preview_chars,
        )

        repeated_count = trace.count_tool_signature(tool_trace.signature.key)
        if repeated_count > 1:
            metrics.repeated_tool_calls += 1
            events.repeated_tool_call_detected(
                iteration=iteration,
                tool_name=tool_trace.tool_name,
                signature=tool_trace.signature.key,
                count=repeated_count,
                limit=agent.loop_policy.max_repeated_tool_calls,
            )
        detection = stall_detector.after_tool_call(trace, tool_trace)
        if detection.stalled:
            metrics.stalled_iterations += 1
            trace.mark_stop_candidate(
                iteration_trace,
                detection.stop_reason.value if detection.stop_reason else "stalled",
            )
            return self._stalled_result(
                agent=agent,
                metrics=metrics,
                events=events,
                trace=trace,
                diagnostics=diagnostics,
                iterations=iteration,
                verdict=None,
                detection=detection,
                llm_call_artifacts=llm_call_artifacts,
            )

        if observation.status == ToolStatus.APPROVAL_REQUIRED:
            events.tool_approval_required(
                iteration=iteration,
                tool_name=observation.call.tool_name,
                approval_id=observation.result.approval_id,
            )
            return self._waiting_for_approval_result(
                agent=agent,
                metrics=metrics,
                events=events,
                trace=trace,
                diagnostics=diagnostics,
                iterations=iteration,
                tool_name=observation.call.tool_name,
                approval_id=observation.result.approval_id,
                llm_call_artifacts=llm_call_artifacts,
            )

        if observation.status == ToolStatus.SUCCEEDED and _is_control_set_output(observation):
            control_output = _control_output(observation)
            verdict = self._output_judge.judge(
                agent=agent,
                action=AgentAction(
                    action_type="final_output",
                    output=control_output,
                ),
                called_tools=called_tools,
                inputs=inputs,
            )
            trace.record_judge(iteration_trace, verdict)
            result = self._handle_verdict(
                agent=agent,
                action=AgentAction(action_type="final_output", output=control_output),
                metrics=metrics,
                events=events,
                trace=trace,
                diagnostics=diagnostics,
                stall_detector=stall_detector,
                iteration_trace=iteration_trace,
                verdict=verdict,
                judge_retries=metrics.judge_retries,
                via_tool=observation.call.tool_name,
                llm_call_artifacts=llm_call_artifacts,
            )
            if isinstance(result, AgentLoopResult):
                return result
            return result[1]

        if observation.status == ToolStatus.BLOCKED:
            return observation.result.error_message or "tool call blocked"
        if observation.status == ToolStatus.FAILED:
            return observation.result.error_message or "tool call failed"
        if observation.status == ToolStatus.TIMEOUT:
            return observation.result.error_message or "tool call timed out"
        return None

    def _handle_verdict(
        self,
        *,
        agent: AgentSpec,
        action: AgentAction,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        stall_detector: AgentLoopStallDetector,
        iteration_trace: IterationTrace,
        verdict: JudgeVerdict,
        judge_retries: int,
        via_tool: str | None,
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> tuple[int, str] | AgentLoopResult:
        iteration = iteration_trace.iteration
        verdict_payload = verdict.to_dict()
        if verdict.decision == JudgeDecision.ACCEPT:
            metrics.judge_accepts += 1
            events.judge_accept(iteration=iteration, verdict=verdict_payload)
            return self._accepted_result(
                agent=agent,
                metrics=metrics,
                events=events,
                trace=trace,
                diagnostics=diagnostics,
                iterations=iteration,
                output=action.output or {},
                verdict=verdict,
                stop_reason=(
                    AgentLoopStopReason.CONTROL_OUTPUT_ACCEPTED
                    if via_tool
                    else AgentLoopStopReason.FINAL_OUTPUT_ACCEPTED
                ),
                via_tool=via_tool,
                llm_call_artifacts=llm_call_artifacts,
            )

        if verdict.decision == JudgeDecision.BLOCK:
            metrics.judge_blocks += 1
            events.judge_block(iteration=iteration, verdict=verdict_payload, via_tool=via_tool)
            return self._blocked_result(
                agent=agent,
                metrics=metrics,
                events=events,
                trace=trace,
                diagnostics=diagnostics,
                iterations=iteration,
                verdict=verdict,
                stop_reason=_blocked_stop_reason(verdict),
                via_tool=via_tool,
                llm_call_artifacts=llm_call_artifacts,
            )

        next_judge_retries = judge_retries + 1
        metrics.judge_retries += 1
        feedback = verdict.feedback or "output rejected by judge"
        events.judge_retry(
            iteration=iteration,
            feedback=feedback,
            verdict=verdict_payload,
            via_tool=via_tool,
        )
        detection = stall_detector.after_judge_retry(
            trace=trace,
            iteration=iteration,
            judge_retries=next_judge_retries,
        )
        if detection.stalled:
            trace.mark_stop_candidate(iteration_trace, AgentLoopStopReason.JUDGE_RETRY_EXHAUSTED.value)
            return self._retry_exhausted_result(
                agent=agent,
                metrics=metrics,
                events=events,
                trace=trace,
                diagnostics=diagnostics,
                iterations=iteration,
                verdict=verdict,
                stop_reason=AgentLoopStopReason.JUDGE_RETRY_EXHAUSTED,
                detection=detection,
                llm_call_artifacts=llm_call_artifacts,
            )
        return next_judge_retries, feedback

    def _execute_tool(self, tool_call: ToolCall, tool_policy: ToolPolicy) -> ToolObservation:
        return self._tool_executor.execute(tool_call, tool_policy)

    def _complete_llm_request(
        self,
        request: LLMRequest,
        *,
        agent: AgentSpec,
        iteration: int,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
    ) -> LLMResponse:
        if not agent.loop_policy.llm_streaming_enabled:
            return self._llm_client.complete(request)
        stream = getattr(self._llm_client, "stream", None)
        if not callable(stream):
            return self._llm_client.complete(request)

        accumulator = LLMStreamAccumulator()
        stream_event_count = 0
        for stream_event_count, stream_event in enumerate(stream(request), start=1):
            accumulator.add_event(stream_event)
            metrics.llm_stream_event_count += 1
            events.llm_stream_event(
                iteration=iteration,
                stream_event=stream_event.to_dict(),
                sequence=stream_event_count,
            )
        response = accumulator.to_response()
        metadata = dict(response.metadata)
        metadata["llm_streamed"] = True
        metadata["llm_stream_event_count"] = stream_event_count
        return LLMResponse(
            content=response.content,
            usage=response.usage,
            metadata=metadata,
            structured_output=response.structured_output,
            tool_calls=list(response.tool_calls),
        )

    def _check_global_budget_before_llm_call(self, metrics: AgentLoopMetrics) -> None:
        if self._global_budget_tracker is None:
            return
        check = self._global_budget_tracker.check_before_llm_call()
        metrics.global_budget_check = check.to_dict()
        metrics.global_budget_usage = check.usage.to_dict()

    def _record_global_budget_call(
        self,
        metrics: AgentLoopMetrics,
        response,
    ) -> None:
        metadata = dict(response.metadata)
        router_budget_check = metadata.get("llm_global_budget_check")
        router_budget_usage = metadata.get("llm_global_budget_usage")
        if isinstance(router_budget_check, dict):
            metrics.global_budget_check = dict(router_budget_check)
            metrics.global_budget_usage = (
                dict(router_budget_usage) if isinstance(router_budget_usage, dict) else None
            )
            return
        if self._global_budget_tracker is None:
            return
        check = self._global_budget_tracker.record_llm_call(
            response.usage,
            estimated_cost_usd=_optional_float(metadata.get("llm_estimated_cost_usd")),
        )
        metrics.global_budget_check = check.to_dict()
        metrics.global_budget_usage = check.usage.to_dict()

    def _accepted_result(
        self,
        *,
        agent: AgentSpec,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        iterations: int,
        output: dict[str, Any],
        verdict: JudgeVerdict,
        stop_reason: AgentLoopStopReason,
        via_tool: str | None,
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> AgentLoopResult:
        events.final_output(iteration=iterations, output_keys=sorted(output.keys()), via_tool=via_tool)
        result_diagnostics = diagnostics.accepted(
            metrics=metrics,
            iterations=iterations,
            stop_reason=stop_reason,
            verdict=verdict,
        )
        events.completed(
            iteration=iterations,
            status=AgentLoopStatus.ACCEPTED.value,
            stop_reason=stop_reason.value,
        )
        return AgentLoopResult(
            success=True,
            status=AgentLoopStatus.ACCEPTED,
            output=output,
            verdict=verdict,
            iterations=iterations,
            metrics=metrics,
            events=events.to_dicts(),
            trace=_trace_payload(trace, agent),
            diagnostics=result_diagnostics,
            llm_call_artifacts=list(llm_call_artifacts),
        )

    def _blocked_result(
        self,
        *,
        agent: AgentSpec,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        iterations: int,
        verdict: JudgeVerdict,
        stop_reason: AgentLoopStopReason,
        via_tool: str | None,
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> AgentLoopResult:
        result_diagnostics = diagnostics.blocked(
            metrics=metrics,
            iterations=iterations,
            stop_reason=stop_reason,
            verdict=verdict,
        )
        events.blocked(
            iteration=iterations,
            stop_reason=stop_reason.value,
            verdict=verdict.to_dict(),
        )
        return AgentLoopResult(
            success=False,
            status=AgentLoopStatus.BLOCKED,
            verdict=verdict,
            iterations=iterations,
            metrics=metrics,
            events=events.to_dicts(),
            trace=_trace_payload(trace, agent),
            diagnostics=result_diagnostics,
            llm_call_artifacts=list(llm_call_artifacts),
            error=verdict.feedback,
        )

    def _global_budget_exceeded_result(
        self,
        *,
        agent: AgentSpec,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        iterations: int,
        exc: Exception,
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> AgentLoopResult:
        budget_check = _budget_check_from_exception(exc)
        if budget_check is not None:
            metrics.global_budget_check = budget_check
            usage = budget_check.get("usage")
            metrics.global_budget_usage = dict(usage) if isinstance(usage, dict) else None
        verdict = JudgeVerdict(
            decision=JudgeDecision.BLOCK,
            confidence=1.0,
            feedback=str(exc),
            policy_violations=["global budget exceeded"],
        )
        result_diagnostics = diagnostics.blocked(
            metrics=metrics,
            iterations=iterations,
            stop_reason=AgentLoopStopReason.GLOBAL_BUDGET_EXCEEDED,
            verdict=verdict,
        )
        events.blocked(
            iteration=iterations,
            stop_reason=AgentLoopStopReason.GLOBAL_BUDGET_EXCEEDED.value,
            verdict=verdict.to_dict(),
        )
        return AgentLoopResult(
            success=False,
            status=AgentLoopStatus.BLOCKED,
            verdict=verdict,
            iterations=iterations,
            metrics=metrics,
            events=events.to_dicts(),
            trace=_trace_payload(trace, agent),
            diagnostics=result_diagnostics,
            llm_call_artifacts=list(llm_call_artifacts),
            error=str(exc),
        )

    def _waiting_for_approval_result(
        self,
        *,
        agent: AgentSpec,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        iterations: int,
        tool_name: str,
        approval_id: str | None,
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> AgentLoopResult:
        result_diagnostics = diagnostics.waiting_for_approval(
            metrics=metrics,
            iterations=iterations,
            tool_name=tool_name,
            approval_id=approval_id,
        )
        events.waiting_for_approval(
            iteration=iterations,
            stop_reason=AgentLoopStopReason.TOOL_APPROVAL_REQUIRED.value,
            approval_id=approval_id,
        )
        return AgentLoopResult(
            success=False,
            status=AgentLoopStatus.WAITING_FOR_APPROVAL,
            iterations=iterations,
            metrics=metrics,
            events=events.to_dicts(),
            trace=_trace_payload(trace, agent),
            diagnostics=result_diagnostics,
            llm_call_artifacts=list(llm_call_artifacts),
            error=result_diagnostics.summary,
        )

    def _retry_exhausted_result(
        self,
        *,
        agent: AgentSpec,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        iterations: int,
        verdict: JudgeVerdict | None,
        stop_reason: AgentLoopStopReason,
        detection: StallDetection | None = None,
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> AgentLoopResult:
        result_diagnostics = diagnostics.retry_exhausted(
            metrics=metrics,
            iterations=iterations,
            stop_reason=stop_reason,
            verdict=verdict,
            issue=detection.issue if detection else None,
        )
        events.retry_exhausted(
            iteration=iterations,
            stop_reason=stop_reason.value,
            verdict=verdict.to_dict() if verdict else None,
        )
        return AgentLoopResult(
            success=False,
            status=AgentLoopStatus.RETRY_EXHAUSTED,
            verdict=verdict,
            iterations=iterations,
            metrics=metrics,
            events=events.to_dicts(),
            trace=_trace_payload(trace, agent),
            diagnostics=result_diagnostics,
            llm_call_artifacts=list(llm_call_artifacts),
            error=result_diagnostics.summary,
        )

    def _stalled_result(
        self,
        *,
        agent: AgentSpec,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        iterations: int,
        verdict: JudgeVerdict | None,
        detection: StallDetection,
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> AgentLoopResult:
        result_diagnostics = diagnostics.stalled(
            metrics=metrics,
            iterations=iterations,
            detection=detection,
            verdict=verdict,
        )
        events.stalled(
            iteration=iterations,
            stop_reason=result_diagnostics.stop_reason.value,
            summary=result_diagnostics.summary,
        )
        return AgentLoopResult(
            success=False,
            status=AgentLoopStatus.STALLED,
            verdict=verdict,
            iterations=iterations,
            metrics=metrics,
            events=events.to_dicts(),
            trace=_trace_payload(trace, agent),
            diagnostics=result_diagnostics,
            llm_call_artifacts=list(llm_call_artifacts),
            error=result_diagnostics.summary,
        )

    def _failed_result(
        self,
        *,
        agent: AgentSpec,
        metrics: AgentLoopMetrics,
        events: AgentLoopEventRecorder,
        trace: AgentLoopTrace,
        diagnostics: AgentLoopDiagnosticsBuilder,
        iterations: int,
        stop_reason: AgentLoopStopReason,
        error: str,
        llm_call_artifacts: list[LLMCallArtifact],
    ) -> AgentLoopResult:
        result_diagnostics = diagnostics.failed(
            metrics=metrics,
            iterations=iterations,
            stop_reason=stop_reason,
            error=error,
        )
        events.failed(iteration=iterations, stop_reason=stop_reason.value, error=error)
        return AgentLoopResult(
            success=False,
            status=AgentLoopStatus.FAILED,
            iterations=iterations,
            metrics=metrics,
            events=events.to_dicts(),
            trace=_trace_payload(trace, agent),
            diagnostics=result_diagnostics,
            llm_call_artifacts=list(llm_call_artifacts),
            error=error,
        )


def _trace_payload(trace: AgentLoopTrace, agent: AgentSpec) -> dict[str, Any]:
    if not agent.loop_policy.trace_enabled:
        return {"agent_id": agent.agent_id, "summary": trace.summary()}
    return trace.to_dict()


def _llm_call_artifact(
    *,
    agent: AgentSpec,
    iteration: int,
    request: LLMRequest,
    response: LLMResponse,
) -> LLMCallArtifact:
    metadata = dict(response.metadata)
    return LLMCallArtifact(
        artifact_id=f"{agent.agent_id}:llm_call:{iteration}",
        iteration=iteration,
        request=request.to_dict(redact=True),
        response=response.to_dict(redact=True),
        metadata={
            "agent_id": agent.agent_id,
            "provider": metadata.get("provider") or metadata.get("llm_provider"),
            "model": metadata.get("model") or metadata.get("llm_model"),
            "route_id": metadata.get("llm_route_id"),
            "deployment_id": metadata.get("llm_deployment_id"),
            "fallback_used": metadata.get("llm_fallback_used"),
            "streamed": metadata.get("llm_streamed"),
        },
    )


def _tool_names(tools: list[dict[str, Any]]) -> list[str]:
    names = []
    for tool in tools:
        name = tool.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return sorted(names)


def _max_tool_calls_per_agent(policy: ToolPolicy) -> int:
    return max(0, int(policy.max_tool_calls_per_agent))


def _blocked_tool_budget_observation(
    tool_call: ToolCall,
    policy: ToolPolicy,
) -> ToolObservation:
    return ToolObservation(
        call=tool_call,
        result=ToolResult(
            status=ToolStatus.BLOCKED,
            error_type="ToolPermissionError",
            error_message=(
                "agent exceeded max_tool_calls_per_agent "
                f"of {_max_tool_calls_per_agent(policy)}"
            ),
        ),
        elapsed_ms=0.0,
    )


def _is_control_set_output(observation: ToolObservation) -> bool:
    output = observation.result.output
    return (
        observation.call.tool_name == "control.set_output"
        and isinstance(output, dict)
        and output.get("control_action") == "set_output"
        and isinstance(output.get("output"), dict)
    )


def _control_output(observation: ToolObservation) -> dict[str, Any]:
    output = observation.result.output
    if isinstance(output, dict) and isinstance(output.get("output"), dict):
        return dict(output["output"])
    return {}


def _blocked_stop_reason(verdict: JudgeVerdict) -> AgentLoopStopReason:
    if any("secret" in violation for violation in verdict.policy_violations):
        return AgentLoopStopReason.SECRET_BLOCKED
    return AgentLoopStopReason.JUDGE_BLOCKED


def _is_global_budget_exception(exc: Exception) -> bool:
    return getattr(exc, "error_type", None) == "global_budget_exceeded"


def _budget_check_from_exception(exc: Exception) -> dict[str, Any] | None:
    check = getattr(exc, "check", None)
    if check is not None and hasattr(check, "to_dict"):
        payload = check.to_dict()
        return dict(payload) if isinstance(payload, dict) else None
    manifest = getattr(exc, "manifest", None)
    if isinstance(manifest, dict):
        check_payload = manifest.get("global_budget_check")
        if isinstance(check_payload, dict):
            return dict(check_payload)
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
