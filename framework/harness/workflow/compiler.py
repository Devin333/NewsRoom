from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.conditions import (
    ConditionAll,
    ConditionPredicate,
    HarnessCondition,
    condition_from_legacy_dict,
)
from framework.harness.workflow.dsl import (
    BoundedLoop,
    Choice,
    HarnessGraphExpression,
    ParallelAll,
    ParallelAny,
    PureMerge,
    Sequence,
    StepRef,
    VerifiedAggregation,
    Wait,
    WaitTimeoutAction,
)
from framework.harness.workflow.graph import (
    HarnessBranch,
    HarnessCompensationReference,
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphEdge,
    HarnessGraphEdgeKind,
    HarnessGraphNode,
    HarnessGraphNodeKind,
    HarnessJoinContract,
    HarnessLoopContract,
    HarnessMergeContract,
    HarnessMergeKind,
    HarnessWaitContract,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.spec import (
    HarnessRouteKind,
    HarnessRoutingRule,
    HarnessWorkflowSpec,
)
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workflow.versioning import (
    HARNESS_GRAPH_COMPILER_VERSION,
    HARNESS_WORKER_ACTIVITY_SCHEMA,
)


@dataclass(frozen=True, slots=True)
class HarnessGraphCompileResult:
    graph: NormalizedHarnessGraph
    declaration_mode: str
    compiler_version: str = HARNESS_GRAPH_COMPILER_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if self.declaration_mode not in {"graph", "legacy"}:
            raise HarnessValidationError(
                "unsupported workflow declaration mode",
                code="unsupported_workflow_declaration_mode",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_version": self.compiler_version,
            "declaration_mode": self.declaration_mode,
            "graph": self.graph.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _Fragment:
    entry_node_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]


class HarnessWorkflowGraphCompiler:
    compiler_version = HARNESS_GRAPH_COMPILER_VERSION

    def compile(self, workflow: HarnessWorkflowSpec) -> HarnessGraphCompileResult:
        if not isinstance(workflow, HarnessWorkflowSpec):
            raise TypeError("workflow must be HarnessWorkflowSpec")
        context = _CompilerContext(workflow)
        if workflow.graph is None:
            graph = context.compile_legacy()
            mode = "legacy"
        else:
            graph = context.compile_graph()
            mode = "graph"
        return HarnessGraphCompileResult(graph=graph, declaration_mode=mode)


class _CompilerContext:
    def __init__(self, workflow: HarnessWorkflowSpec) -> None:
        self.workflow = workflow
        self.steps_by_id = {step.step_id: step for step in workflow.steps}
        self.nodes: list[HarnessGraphNode] = []
        self.edges: list[HarnessGraphEdge] = []
        self.compensation_refs: list[HarnessCompensationReference] = []
        self._node_order = 0
        self._edge_order = 0
        self._node_ids_by_step: dict[str, list[str]] = defaultdict(list)

    def compile_graph(self) -> NormalizedHarnessGraph:
        graph_spec = self.workflow.graph
        if graph_spec is None:
            raise AssertionError("explicit graph compiler requires graph spec")
        fragment = self._compile_expression(graph_spec.root)
        self._compile_compensations()
        self._compile_repair_edges()
        return self._build_graph(
            graph_id=graph_spec.graph_id,
            entry_node_ids=fragment.entry_node_ids,
            terminal_node_ids=fragment.terminal_node_ids,
            input_keys=graph_spec.input_keys,
            terminal_output_keys=graph_spec.terminal_output_keys,
        )

    def compile_legacy(self) -> NormalizedHarnessGraph:
        for step in self.workflow.steps:
            self._add_executable(step.step_id, step.step_id)

        ordered_ids = self.workflow.step_ids
        rules_by_source: dict[str, list[HarnessRoutingRule]] = defaultdict(list)
        for rule in self.workflow.routing_rules:
            rules_by_source[rule.from_step].append(rule)

        for index, source_id in enumerate(ordered_ids):
            default_target = (
                ordered_ids[index + 1] if index + 1 < len(ordered_ids) else None
            )
            rules = _effective_legacy_rules(tuple(rules_by_source.get(source_id, ())))
            if not rules:
                if default_target is not None:
                    self._add_edge(
                        source_id, default_target, HarnessGraphEdgeKind.DEPENDENCY
                    )
                continue
            if len(rules) == 1 and _is_unconditional_legacy_rule(rules[0]):
                self._add_edge(
                    source_id,
                    rules[0].to_step,
                    HarnessGraphEdgeKind.DEPENDENCY,
                    priority=0,
                )
                continue
            self._compile_legacy_choice(source_id, rules, default_target)

        self._compile_repair_edges()
        self._prune_unreachable_legacy_nodes()
        terminal_ids = self._forward_terminal_node_ids()
        return self._build_graph(
            graph_id=f"{self.workflow.workflow_id}:legacy",
            entry_node_ids=(self.workflow.entry_step_id,),
            terminal_node_ids=terminal_ids,
            input_keys=self._legacy_input_keys(),
            terminal_output_keys=self._legacy_terminal_output_keys(terminal_ids),
        )

    def _prune_unreachable_legacy_nodes(self) -> None:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            adjacency[edge.source_id].append(edge.target_id)
        reachable: set[str] = set()
        pending = [self.workflow.entry_step_id]
        while pending:
            node_id = pending.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            pending.extend(
                target_id
                for target_id in sorted(adjacency.get(node_id, ()), reverse=True)
                if target_id not in reachable
            )
        self.nodes = [node for node in self.nodes if node.node_id in reachable]
        self.edges = [
            edge
            for edge in self.edges
            if edge.source_id in reachable and edge.target_id in reachable
        ]

    def _compile_expression(self, expression: HarnessGraphExpression) -> _Fragment:
        if isinstance(expression, StepRef):
            step = self._step(expression.step_id)
            self._add_executable(step.step_id, expression.node_id or expression.step_id)
            return _Fragment(
                (expression.node_id or expression.step_id,),
                (expression.node_id or expression.step_id,),
            )
        if isinstance(expression, Sequence):
            fragments = tuple(
                self._compile_expression(child) for child in expression.children
            )
            for left, right in zip(fragments, fragments[1:]):
                for source_id in left.terminal_node_ids:
                    for target_id in right.entry_node_ids:
                        self._add_edge(
                            source_id,
                            target_id,
                            self._sequence_edge_kind(source_id),
                        )
            return _Fragment(
                fragments[0].entry_node_ids, fragments[-1].terminal_node_ids
            )
        if isinstance(expression, Choice):
            return self._compile_choice(expression)
        if isinstance(expression, ParallelAll):
            return self._compile_parallel_all(expression)
        if isinstance(expression, ParallelAny):
            return self._compile_parallel_any(expression)
        if isinstance(expression, BoundedLoop):
            return self._compile_loop(expression)
        if isinstance(expression, Wait):
            self._add_control(
                node_id=expression.wait_id,
                node_kind=HarnessGraphNodeKind.WAIT,
                wait=HarnessWaitContract(
                    wait_id=expression.wait_id,
                    kind=expression.kind,
                    correlation=expression.correlation,
                    signal_type=expression.signal_type,
                    signal_version=expression.signal_version,
                    tenant_scope_path=expression.tenant_scope_path,
                    identity_scope_path=expression.identity_scope_path,
                    timeout_policy=expression.timeout_policy,
                    deadline_input_path=expression.deadline_input_path,
                ),
            )
            if (
                expression.timeout_policy is not None
                and expression.timeout_policy.action is WaitTimeoutAction.ROUTE
            ):
                assert expression.timeout_policy.target_node_id is not None
                self._add_edge(
                    expression.wait_id,
                    expression.timeout_policy.target_node_id,
                    HarnessGraphEdgeKind.WAIT_TIMEOUT,
                )
            return _Fragment((expression.wait_id,), (expression.wait_id,))
        raise HarnessValidationError(
            "compiler received unsupported graph expression",
            code="unsupported_graph_node_kind",
            details={"type": type(expression).__name__},
        )

    def _sequence_edge_kind(self, source_id: str) -> HarnessGraphEdgeKind:
        source = next(
            (node for node in self.nodes if node.node_id == source_id),
            None,
        )
        if (
            isinstance(source, HarnessControlNode)
            and source.node_kind is HarnessGraphNodeKind.WAIT
        ):
            return HarnessGraphEdgeKind.WAIT_RESUME
        return HarnessGraphEdgeKind.DEPENDENCY

    def _compile_choice(self, expression: Choice) -> _Fragment:
        compiled: list[tuple[Any, _Fragment]] = []
        branches: list[HarnessBranch] = []
        for branch in expression.branches:
            fragment = self._compile_expression(branch.child)
            compiled.append((branch, fragment))
            branches.append(
                HarnessBranch(
                    branch_id=branch.branch_id,
                    entry_node_ids=fragment.entry_node_ids,
                    terminal_node_ids=fragment.terminal_node_ids,
                    priority=branch.priority,
                    output_namespace=branch.output_namespace
                    or f"choice.{expression.choice_id}.{branch.branch_id}",
                    condition=branch.condition,
                    is_default=branch.is_default,
                )
            )
        self._add_control(
            node_id=expression.choice_id,
            node_kind=HarnessGraphNodeKind.CHOICE,
            branches=tuple(branches),
        )
        choice_join_id = f"{expression.choice_id}:join"
        self._add_control(
            node_id=choice_join_id,
            node_kind=HarnessGraphNodeKind.CHOICE_JOIN,
            branches=tuple(branches),
            metadata={"choice_node_id": expression.choice_id},
        )
        for branch, fragment in compiled:
            edge_kind = (
                HarnessGraphEdgeKind.DEFAULT
                if branch.is_default
                else HarnessGraphEdgeKind.CHOICE
            )
            for target_id in fragment.entry_node_ids:
                self._add_edge(
                    expression.choice_id,
                    target_id,
                    edge_kind,
                    priority=branch.priority,
                    condition=branch.condition,
                    branch_id=branch.branch_id,
                )
            for terminal_id in fragment.terminal_node_ids:
                self._add_edge(
                    terminal_id,
                    choice_join_id,
                    HarnessGraphEdgeKind.DEPENDENCY,
                    branch_id=branch.branch_id,
                )
        return _Fragment((expression.choice_id,), (choice_join_id,))

    def _compile_parallel_all(self, expression: ParallelAll) -> _Fragment:
        compiled = tuple(
            (branch, self._compile_expression(branch.child))
            for branch in expression.branches
        )
        branches = tuple(
            HarnessBranch(
                branch_id=branch.branch_id,
                entry_node_ids=fragment.entry_node_ids,
                terminal_node_ids=fragment.terminal_node_ids,
                priority=index,
                output_namespace=branch.output_namespace,
                is_default=False,
            )
            for index, (branch, fragment) in enumerate(compiled)
        )
        merge_node_id = f"{expression.join_id}:merge"
        merge_ref = None
        if isinstance(expression.merge, PureMerge):
            merge_ref = _reference_from_text(
                HarnessContractKind.MERGE,
                expression.merge.merge_ref,
                field_name="parallel_all.merge.merge_ref",
            )[0]
        self._add_control(
            node_id=expression.fork_id,
            node_kind=HarnessGraphNodeKind.FORK_ALL,
            branches=branches,
        )
        self._add_control(
            node_id=expression.join_id,
            node_kind=HarnessGraphNodeKind.JOIN_ALL,
            join=HarnessJoinContract(
                fork_node_id=expression.fork_id,
                required_branch_ids=tuple(
                    branch.branch_id for branch in expression.branches
                ),
                failure_policy=expression.failure_policy.value,
                merge_ref=merge_ref,
            ),
        )
        for branch, fragment in compiled:
            for entry_id in fragment.entry_node_ids:
                self._add_edge(
                    expression.fork_id,
                    entry_id,
                    HarnessGraphEdgeKind.FORK_BRANCH,
                    branch_id=branch.branch_id,
                )
            for terminal_id in fragment.terminal_node_ids:
                self._add_edge(
                    terminal_id,
                    expression.join_id,
                    HarnessGraphEdgeKind.JOIN,
                    branch_id=branch.branch_id,
                )
        if expression.merge is None:
            return _Fragment((expression.fork_id,), (expression.join_id,))
        if isinstance(expression.merge, PureMerge):
            self._add_control(
                node_id=merge_node_id,
                node_kind=HarnessGraphNodeKind.MERGE,
                merge=HarnessMergeContract(
                    merge_kind=HarnessMergeKind.PURE,
                    input_branch_ids=tuple(
                        branch.branch_id for branch in expression.branches
                    ),
                    output_keys=expression.merge.output_keys,
                    merge_ref=merge_ref,
                ),
                metadata={"join_node_id": expression.join_id},
            )
            self._add_edge(
                expression.join_id,
                merge_node_id,
                HarnessGraphEdgeKind.DEPENDENCY,
            )
            return _Fragment((expression.fork_id,), (merge_node_id,))
        if not isinstance(expression.merge, VerifiedAggregation):
            raise AssertionError("unsupported Parallel-All merge contract")
        aggregation_step = self._step(expression.merge.step.step_id)
        if expression.merge.branch_inputs_key not in aggregation_step.input_keys:
            raise HarnessValidationError(
                "verified aggregation Step must declare its branch input key",
                code="aggregation_input_key_missing",
                details={
                    "step_id": aggregation_step.step_id,
                    "branch_inputs_key": expression.merge.branch_inputs_key,
                },
            )
        if aggregation_step.output_key is None:
            raise HarnessValidationError(
                "verified aggregation Step must declare one output key",
                code="aggregation_output_key_missing",
                details={"step_id": aggregation_step.step_id},
            )
        if aggregation_step.quality_gate is None:
            raise HarnessValidationError(
                "verified aggregation Step requires an exact deterministic Gate",
                code="aggregation_gate_missing",
                details={"step_id": aggregation_step.step_id},
            )
        aggregation = self._compile_expression(expression.merge.step)
        if len(aggregation.entry_node_ids) != 1 or len(aggregation.terminal_node_ids) != 1:
            raise HarnessValidationError(
                "verified aggregation must compile to one executable node",
                code="invalid_merge_contract",
            )
        aggregation_node_id = aggregation.entry_node_ids[0]
        self._add_control(
            node_id=merge_node_id,
            node_kind=HarnessGraphNodeKind.MERGE,
            merge=HarnessMergeContract(
                merge_kind=HarnessMergeKind.AGGREGATION_STEP,
                input_branch_ids=tuple(
                    branch.branch_id for branch in expression.branches
                ),
                output_keys=(aggregation_step.output_key,),
                aggregation_node_id=aggregation_node_id,
            ),
            metadata={
                "branch_inputs_key": expression.merge.branch_inputs_key,
                "join_node_id": expression.join_id,
            },
        )
        self._add_edge(
            expression.join_id,
            aggregation_node_id,
            HarnessGraphEdgeKind.DEPENDENCY,
        )
        for terminal_id in aggregation.terminal_node_ids:
            self._add_edge(
                terminal_id,
                merge_node_id,
                HarnessGraphEdgeKind.DEPENDENCY,
            )
        return _Fragment((expression.fork_id,), (merge_node_id,))

    def _compile_parallel_any(self, expression: ParallelAny) -> _Fragment:
        compiled = tuple(
            (branch, self._compile_expression(branch.child))
            for branch in expression.branches
        )
        branches = tuple(
            HarnessBranch(
                branch_id=branch.branch_id,
                entry_node_ids=fragment.entry_node_ids,
                terminal_node_ids=fragment.terminal_node_ids,
                priority=index,
                output_namespace=branch.output_namespace,
                is_default=False,
            )
            for index, (branch, fragment) in enumerate(compiled)
        )
        self._add_control(
            node_id=expression.fork_id,
            node_kind=HarnessGraphNodeKind.FORK_ANY,
            branches=branches,
            metadata={"cancellation_policy": expression.cancellation_policy.value},
        )
        self._add_control(
            node_id=expression.join_id,
            node_kind=HarnessGraphNodeKind.JOIN_ANY,
            join=HarnessJoinContract(
                fork_node_id=expression.fork_id,
                required_branch_ids=tuple(
                    branch.branch_id for branch in expression.branches
                ),
                failure_policy=expression.failure_policy.value,
                winner_policy="first_verified_success_by_stream_sequence",
            ),
        )
        for branch, fragment in compiled:
            for entry_id in fragment.entry_node_ids:
                self._add_edge(
                    expression.fork_id,
                    entry_id,
                    HarnessGraphEdgeKind.FORK_BRANCH,
                    branch_id=branch.branch_id,
                )
            for terminal_id in fragment.terminal_node_ids:
                self._add_edge(
                    terminal_id,
                    expression.join_id,
                    HarnessGraphEdgeKind.JOIN,
                    branch_id=branch.branch_id,
                )
        return _Fragment((expression.fork_id,), (expression.join_id,))

    def _compile_loop(self, expression: BoundedLoop) -> _Fragment:
        if expression.exit is None:
            raise HarnessValidationError(
                "bounded loop requires an explicit exit expression",
                code="loop_exit_missing",
                details={"loop_id": expression.loop_id},
            )
        body = self._compile_expression(expression.body)
        exit_fragment = self._compile_expression(expression.exit)
        exhaustion = (
            None
            if expression.exhaustion is None
            else self._compile_expression(expression.exhaustion)
        )
        self._add_control(
            node_id=expression.loop_id,
            node_kind=HarnessGraphNodeKind.LOOP_GUARD,
            loop=HarnessLoopContract(
                body_entry_node_ids=body.entry_node_ids,
                body_terminal_node_ids=body.terminal_node_ids,
                condition=expression.condition,
                max_iterations=expression.max_iterations,
                exit_node_ids=exit_fragment.entry_node_ids,
                exhaustion_node_ids=(
                    () if exhaustion is None else exhaustion.entry_node_ids
                ),
            ),
        )
        loop_join_id = f"{expression.loop_id}:join"
        loop_routes = [
            HarnessBranch(
                branch_id="exit",
                entry_node_ids=exit_fragment.entry_node_ids,
                terminal_node_ids=exit_fragment.terminal_node_ids,
                priority=0,
                output_namespace=f"loop.{expression.loop_id}.exit",
            )
        ]
        if exhaustion is not None:
            loop_routes.append(
                HarnessBranch(
                    branch_id="exhaustion",
                    entry_node_ids=exhaustion.entry_node_ids,
                    terminal_node_ids=exhaustion.terminal_node_ids,
                    priority=1,
                    output_namespace=f"loop.{expression.loop_id}.exhaustion",
                )
            )
        self._add_control(
            node_id=loop_join_id,
            node_kind=HarnessGraphNodeKind.LOOP_JOIN,
            branches=tuple(loop_routes),
            metadata={"loop_node_id": expression.loop_id},
        )
        for entry_id in body.entry_node_ids:
            self._add_edge(
                expression.loop_id,
                entry_id,
                HarnessGraphEdgeKind.LOOP_BODY,
                condition=expression.condition,
                loop_id=expression.loop_id,
            )
        for terminal_id in body.terminal_node_ids:
            self._add_edge(
                terminal_id,
                expression.loop_id,
                HarnessGraphEdgeKind.LOOP_BACK,
                loop_id=expression.loop_id,
            )
        for entry_id in exit_fragment.entry_node_ids:
            self._add_edge(
                expression.loop_id,
                entry_id,
                HarnessGraphEdgeKind.LOOP_EXIT,
                loop_id=expression.loop_id,
            )
        if exhaustion is not None:
            for entry_id in exhaustion.entry_node_ids:
                self._add_edge(
                    expression.loop_id,
                    entry_id,
                    HarnessGraphEdgeKind.LOOP_EXHAUSTED,
                    loop_id=expression.loop_id,
                )
        for route in loop_routes:
            for terminal_id in route.terminal_node_ids:
                self._add_edge(
                    terminal_id,
                    loop_join_id,
                    HarnessGraphEdgeKind.DEPENDENCY,
                    branch_id=route.branch_id,
                    loop_id=expression.loop_id,
                )
        return _Fragment((expression.loop_id,), (loop_join_id,))

    def _compile_legacy_choice(
        self,
        source_id: str,
        rules: tuple[HarnessRoutingRule, ...],
        default_target: str | None,
    ) -> None:
        choice_id = f"choice:{source_id}"
        branches: list[HarnessBranch] = []
        compiled: list[tuple[HarnessBranch, str]] = []
        has_default = False
        for priority, rule in enumerate(rules):
            condition = _legacy_rule_condition(rule)
            is_default = condition is None
            has_default = has_default or is_default
            branch = HarnessBranch(
                branch_id=f"legacy:{source_id}:{priority}",
                entry_node_ids=(rule.to_step,),
                terminal_node_ids=(rule.to_step,),
                priority=priority,
                output_namespace=f"legacy.{source_id}.{priority}",
                condition=condition,
                is_default=is_default,
            )
            branches.append(branch)
            compiled.append((branch, rule.to_step))
        if not has_default and default_target is not None:
            priority = len(rules)
            branch = HarnessBranch(
                branch_id=f"legacy:{source_id}:default",
                entry_node_ids=(default_target,),
                terminal_node_ids=(default_target,),
                priority=priority,
                output_namespace=f"legacy.{source_id}.default",
                is_default=True,
            )
            branches.append(branch)
            compiled.append((branch, default_target))
        self._add_control(
            node_id=choice_id,
            node_kind=HarnessGraphNodeKind.CHOICE,
            branches=tuple(branches),
            metadata={"legacy_source_step_id": source_id},
        )
        self._add_edge(source_id, choice_id, HarnessGraphEdgeKind.DEPENDENCY)
        for branch, target_id in compiled:
            self._add_edge(
                choice_id,
                target_id,
                HarnessGraphEdgeKind.DEFAULT
                if branch.is_default
                else HarnessGraphEdgeKind.CHOICE,
                priority=branch.priority,
                condition=branch.condition,
                branch_id=branch.branch_id,
            )

    def _compile_compensations(self) -> None:
        graph_spec = self.workflow.graph
        if graph_spec is None:
            return
        for binding in graph_spec.compensations:
            compensation_node_id = f"compensation:{binding.binding_id}"
            step = self._step(binding.compensation_step_id)
            self._add_executable(step.step_id, compensation_node_id)
            handler_ref, _ = _reference_from_text(
                HarnessContractKind.COMPENSATION,
                binding.handler_ref,
                field_name="compensation.handler_ref",
            )
            activity_ref, _ = _reference_from_text(
                HarnessContractKind.ACTIVITY,
                binding.activity_contract_ref,
                field_name="compensation.activity_contract_ref",
            )
            self.compensation_refs.append(
                HarnessCompensationReference(
                    binding_id=binding.binding_id,
                    for_node_id=binding.for_node_id,
                    compensation_node_id=compensation_node_id,
                    handler_ref=handler_ref,
                    activity_ref=activity_ref,
                    scope=binding.scope,
                )
            )
            self._add_edge(
                binding.for_node_id,
                compensation_node_id,
                HarnessGraphEdgeKind.COMPENSATION,
            )

    def _compile_repair_edges(self) -> None:
        for node in tuple(self.nodes):
            if not isinstance(node, HarnessExecutableNode):
                continue
            step = self.steps_by_id[node.step_id]
            repair_step_id = step.retry_policy.repair_step_id
            if repair_step_id is None:
                continue
            targets = tuple(self._node_ids_by_step.get(repair_step_id, ()))
            if not targets and repair_step_id in self.steps_by_id:
                targets = (repair_step_id,)
            for target_id in targets:
                self._add_edge(
                    node.node_id,
                    target_id,
                    HarnessGraphEdgeKind.REPAIR,
                )

    def _add_executable(self, step_id: str, node_id: str) -> None:
        step = self._step(step_id)
        step_version = str(step.metadata.get("step_version", "1"))
        worker_version = str(step.metadata.get("worker_version", "1"))
        worker_id = str(step.metadata.get("worker_id", step.step_id))
        activity_value = str(
            step.metadata.get(
                "activity_contract_version",
                HARNESS_WORKER_ACTIVITY_SCHEMA,
            )
        )
        activity_ref, activity_inferred = _reference_from_text(
            HarnessContractKind.ACTIVITY,
            activity_value,
            field_name=f"step[{step.step_id}].activity_contract_version",
            allow_schema_version=True,
        )
        gate_refs: tuple[HarnessContractReference, ...] = ()
        inferred_gate = False
        if step.quality_gate is not None:
            gate_ref, inferred_gate = _reference_from_text(
                HarnessContractKind.GATE,
                step.quality_gate,
                field_name=f"step[{step.step_id}].quality_gate",
                inferred_version="1",
            )
            gate_refs = (gate_ref,)
        side_effect_ref = None
        if step.side_effect_ref is not None:
            side_effect_ref = HarnessContractReference(
                HarnessContractKind.SIDE_EFFECT,
                step.side_effect_ref.handler_id,
                step.side_effect_ref.version,
            )
        metadata = {
            "worker_type": step.worker_type.value,
            "step_metadata": step.metadata,
            "retry_policy": step.retry_policy.to_dict(),
            "contract_provenance": {
                "step_version_inferred": "step_version" not in step.metadata,
                "worker_version_inferred": "worker_version" not in step.metadata,
                "activity_version_inferred": activity_inferred,
                "gate_version_inferred": inferred_gate,
            },
        }
        self.nodes.append(
            HarnessExecutableNode(
                node_id=node_id,
                step_id=step.step_id,
                declaration_order=self._next_node_order(),
                step_ref=HarnessContractReference(
                    HarnessContractKind.STEP,
                    f"{self.workflow.workflow_id}:{step.step_id}",
                    step_version,
                ),
                worker_ref=HarnessContractReference(
                    HarnessContractKind.WORKER,
                    worker_id,
                    worker_version,
                ),
                activity_ref=activity_ref,
                gate_refs=gate_refs,
                side_effect_ref=side_effect_ref,
                input_keys=step.input_keys,
                output_keys=() if step.output_key is None else (step.output_key,),
                metadata=metadata,
            )
        )
        self._node_ids_by_step[step.step_id].append(node_id)

    def _add_control(
        self,
        *,
        node_id: str,
        node_kind: HarnessGraphNodeKind,
        branches: tuple[HarnessBranch, ...] = (),
        join: HarnessJoinContract | None = None,
        loop: HarnessLoopContract | None = None,
        wait: HarnessWaitContract | None = None,
        merge: HarnessMergeContract | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.nodes.append(
            HarnessControlNode(
                node_id=node_id,
                node_kind=node_kind,
                declaration_order=self._next_node_order(),
                branches=branches,
                join=join,
                loop=loop,
                wait=wait,
                merge=merge,
                metadata=metadata or {},
            )
        )

    def _add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_kind: HarnessGraphEdgeKind,
        *,
        priority: int = 0,
        condition: HarnessCondition | None = None,
        branch_id: str | None = None,
        loop_id: str | None = None,
    ) -> None:
        ordinal = self._edge_order
        self._edge_order += 1
        self.edges.append(
            HarnessGraphEdge(
                edge_id=f"edge:{ordinal:06d}:{edge_kind.value}:{source_id}:{target_id}",
                source_id=source_id,
                target_id=target_id,
                edge_kind=edge_kind,
                priority=priority,
                condition=condition,
                branch_id=branch_id,
                loop_id=loop_id,
            )
        )

    def _next_node_order(self) -> int:
        value = self._node_order
        self._node_order += 1
        return value

    def _step(self, step_id: str) -> HarnessStepSpec:
        try:
            return self.steps_by_id[step_id]
        except KeyError as exc:
            raise HarnessValidationError(
                "graph step reference does not resolve to a declared HarnessStepSpec",
                code="unknown_graph_step_reference",
                details={"step_id": str(step_id)},
            ) from exc

    def _forward_terminal_node_ids(self) -> tuple[str, ...]:
        ignored = {HarnessGraphEdgeKind.REPAIR, HarnessGraphEdgeKind.COMPENSATION}
        outgoing = {
            edge.source_id for edge in self.edges if edge.edge_kind not in ignored
        }
        terminals = tuple(
            node.node_id for node in self.nodes if node.node_id not in outgoing
        )
        if not terminals:
            raise HarnessValidationError(
                "compiled legacy graph has no terminal node",
                code="graph_terminal_missing",
            )
        return terminals

    def _build_graph(
        self,
        *,
        graph_id: str,
        entry_node_ids: tuple[str, ...],
        terminal_node_ids: tuple[str, ...],
        input_keys: tuple[str, ...],
        terminal_output_keys: tuple[str, ...],
    ) -> NormalizedHarnessGraph:
        terminal_policy = self.workflow.terminal_side_effect_policy
        terminal_policy_ref = None
        if terminal_policy is not None:
            policy = terminal_policy
            terminal_policy_ref = HarnessContractReference(
                HarnessContractKind.TERMINAL_POLICY,
                policy.policy_id,
                policy.version,
            )
            for gate_ref in policy.inherited_gate_refs:
                _reference_from_text(
                    HarnessContractKind.GATE,
                    gate_ref,
                    field_name="terminal_policy.inherited_gate_refs",
                )
        return NormalizedHarnessGraph(
            graph_id=graph_id,
            workflow_id=self.workflow.workflow_id,
            workflow_version=self.workflow.workflow_version or "1",
            workflow_ref=HarnessContractReference(
                HarnessContractKind.WORKFLOW,
                self.workflow.workflow_id,
                self.workflow.workflow_version or "1",
            ),
            nodes=tuple(self.nodes),
            edges=tuple(self.edges),
            entry_node_ids=entry_node_ids,
            terminal_node_ids=terminal_node_ids,
            input_keys=input_keys,
            terminal_output_keys=terminal_output_keys,
            compensation_refs=tuple(self.compensation_refs),
            terminal_policy_ref=terminal_policy_ref,
            terminal_policy=terminal_policy,
        )

    def _legacy_input_keys(self) -> tuple[str, ...]:
        active_step_ids = {
            node.step_id
            for node in self.nodes
            if isinstance(node, HarnessExecutableNode)
        }
        produced = {
            step.output_key
            for step in self.workflow.steps
            if step.step_id in active_step_ids and step.output_key is not None
        }
        return tuple(
            sorted(
                {
                    input_key
                    for step in self.workflow.steps
                    if step.step_id in active_step_ids
                    for input_key in step.input_keys
                    if input_key not in produced
                }
            )
        )

    def _legacy_terminal_output_keys(
        self,
        terminal_node_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        terminal_steps = {
            node.step_id
            for node in self.nodes
            if isinstance(node, HarnessExecutableNode)
            and node.node_id in terminal_node_ids
        }
        return tuple(
            sorted(
                {
                    step.output_key
                    for step in self.workflow.steps
                    if step.step_id in terminal_steps and step.output_key is not None
                }
            )
        )


def _is_unconditional_legacy_rule(rule: HarnessRoutingRule) -> bool:
    return rule.kind == HarnessRouteKind.ALWAYS and not rule.condition


def _effective_legacy_rules(
    rules: tuple[HarnessRoutingRule, ...],
) -> tuple[HarnessRoutingRule, ...]:
    for index, rule in enumerate(rules):
        if _is_unconditional_legacy_rule(rule):
            return rules[: index + 1]
    return rules


def _legacy_rule_condition(rule: HarnessRoutingRule) -> HarnessCondition | None:
    if rule.kind == HarnessRouteKind.ALWAYS and not rule.condition:
        return None
    if rule.kind == HarnessRouteKind.ON_STATUS:
        expected = rule.condition.get("status", rule.condition.get("equals"))
        if expected is None:
            raise HarnessValidationError(
                "ON_STATUS route requires status or equals",
                code="legacy_route_condition_missing",
                details={"from_step": rule.from_step, "to_step": rule.to_step},
            )
        return ConditionPredicate(
            path="worker_result.status",
            operator="equals",
            expected=expected,
        )
    if rule.kind == HarnessRouteKind.ON_VERDICT:
        predicates: list[HarnessCondition] = []
        if "passed" in rule.condition:
            predicates.append(
                ConditionPredicate(
                    path="quality_verdict.passed",
                    operator="equals",
                    expected=rule.condition["passed"],
                )
            )
        if "min_score" in rule.condition:
            predicates.append(
                ConditionPredicate(
                    path="quality_verdict.score",
                    operator="gte",
                    expected=rule.condition["min_score"],
                )
            )
        if "max_score" in rule.condition:
            predicates.append(
                ConditionPredicate(
                    path="quality_verdict.score",
                    operator="lte",
                    expected=rule.condition["max_score"],
                )
            )
        if not predicates:
            raise HarnessValidationError(
                "ON_VERDICT route requires passed or score bounds",
                code="legacy_route_condition_missing",
                details={"from_step": rule.from_step, "to_step": rule.to_step},
            )
        return (
            predicates[0] if len(predicates) == 1 else ConditionAll(tuple(predicates))
        )
    return condition_from_legacy_dict(rule.condition)


def _reference_from_text(
    kind: HarnessContractKind,
    value: str,
    *,
    field_name: str,
    inferred_version: str | None = None,
    allow_schema_version: bool = False,
) -> tuple[HarnessContractReference, bool]:
    text = str(value).strip()
    if text.count("@") == 1:
        contract_id, version = text.rsplit("@", maxsplit=1)
        return HarnessContractReference(kind, contract_id, version), False
    if allow_schema_version and "/v" in text:
        contract_id, version_number = text.rsplit("/v", maxsplit=1)
        if contract_id and version_number.isdigit() and int(version_number) > 0:
            return HarnessContractReference(
                kind, contract_id, f"v{version_number}"
            ), False
    if inferred_version is not None and text:
        return HarnessContractReference(kind, text, inferred_version), True
    raise HarnessValidationError(
        f"{field_name} must be an exact version reference",
        code="graph_inexact_version_reference",
        details={"field": field_name, "reference": text},
    )


__all__ = [
    "HarnessGraphCompileResult",
    "HarnessWorkflowGraphCompiler",
]
