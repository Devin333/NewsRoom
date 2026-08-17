from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


HARNESS_GRAPH_RUNTIME_VERSION = "newsroom.harness-graph-runtime/v2"
HARNESS_GRAPH_DEFINITION_SCHEMA = "newsroom.harness-graph-definition/v6"
HARNESS_GRAPH_DSL_SCHEMA = "newsroom.harness-workflow-graph/v1"
NORMALIZED_HARNESS_GRAPH_SCHEMA = "newsroom.harness-normalized-graph/v1"
GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA = (
    "newsroom.harness-normalized-graph/v2"
)
HARNESS_GRAPH_STATE_SCHEMA = "newsroom.harness-graph-state/v1"
GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA = "newsroom.harness-graph-state/v2"
HARNESS_GRAPH_DECISION_SCHEMA = "newsroom.harness-graph-decision/v1"
GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA = "newsroom.harness-graph-decision/v2"
HARNESS_GRAPH_CHECKPOINT_SCHEMA = "newsroom.harness-graph-checkpoint/v1"
GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA = (
    "newsroom.harness-graph-checkpoint/v2"
)
HARNESS_GRAPH_INSPECTION_SCHEMA = "newsroom.harness-graph-inspection/v1"
HARNESS_CONDITION_POLICY_VERSION = "newsroom.harness-graph-condition-policy/v1"
HARNESS_GRAPH_COMPILER_VERSION = "newsroom.harness-graph-compiler/v1"
HARNESS_GRAPH_ONLY_COMPILER_VERSION = "newsroom.harness-graph-compiler/v2"
HARNESS_GRAPH_EVALUATOR_VERSION = "newsroom.harness-graph-evaluator/v1"
HARNESS_STEP_LIFECYCLE_VERSION = "newsroom.harness-step-lifecycle/v1"
HARNESS_GRAPH_REDUCER_VERSION = "newsroom.harness-graph-state-reducer/v1"
HARNESS_GRAPH_CONTROL_POLICY_VERSION = "newsroom.harness-graph-control-policy/v1"
HARNESS_GRAPH_MERGE_VERSION = "newsroom.harness-graph-merge/v1"
HARNESS_WORKER_ACTIVITY_SCHEMA = "newsroom.harness-worker-activity/v1"
GRAPH_EXECUTION_VERSION_MANIFEST_SCHEMA = (
    "newsroom.graph-execution-version-manifest/v1"
)

HARNESS_GRAPH_EVENT_SCHEMAS: Mapping[str, str] = MappingProxyType(
    {
        "harness_graph_created": "newsroom.harness-graph-created/v1",
        "harness_graph_decision_committed": HARNESS_GRAPH_DECISION_SCHEMA,
        "harness_graph_node_activated": "newsroom.harness-graph-node-activated/v1",
        "harness_graph_node_terminal": "newsroom.harness-graph-node-terminal/v1",
        "harness_graph_choice_selected": "newsroom.harness-graph-choice-selected/v1",
        "harness_graph_fork_opened": "newsroom.harness-graph-fork-opened/v1",
        "harness_graph_join_satisfied": "newsroom.harness-graph-join-satisfied/v1",
        "harness_graph_loop_transitioned": "newsroom.harness-graph-loop-transition/v1",
        "harness_graph_wait_transitioned": "newsroom.harness-graph-wait-transition/v1",
        "harness_graph_winner_selected": "newsroom.harness-graph-winner-selected/v1",
        "harness_graph_cancellation_transitioned": "newsroom.harness-graph-cancellation-transition/v1",
        "harness_graph_compensation_transitioned": "newsroom.harness-graph-compensation-transition/v1",
        "harness_graph_budget_transitioned": "newsroom.harness-graph-budget-transition/v1",
        "harness_graph_run_lifecycle_transitioned": "newsroom.harness-graph-run-lifecycle-transition/v1",
    }
)
HARNESS_GRAPH_EVENT_SCHEMA = HARNESS_GRAPH_EVENT_SCHEMAS[
    "harness_graph_created"
]

__all__ = [
    "GRAPH_EXECUTION_VERSION_MANIFEST_SCHEMA",
    "HARNESS_CONDITION_POLICY_VERSION",
    "HARNESS_GRAPH_CHECKPOINT_SCHEMA",
    "HARNESS_GRAPH_COMPILER_VERSION",
    "HARNESS_GRAPH_ONLY_COMPILER_VERSION",
    "HARNESS_GRAPH_CONTROL_POLICY_VERSION",
    "HARNESS_GRAPH_DECISION_SCHEMA",
    "HARNESS_GRAPH_DEFINITION_SCHEMA",
    "HARNESS_GRAPH_DSL_SCHEMA",
    "HARNESS_GRAPH_EVALUATOR_VERSION",
    "HARNESS_GRAPH_EVENT_SCHEMA",
    "HARNESS_GRAPH_EVENT_SCHEMAS",
    "HARNESS_GRAPH_INSPECTION_SCHEMA",
    "HARNESS_GRAPH_MERGE_VERSION",
    "HARNESS_GRAPH_REDUCER_VERSION",
    "HARNESS_GRAPH_RUNTIME_VERSION",
    "HARNESS_GRAPH_STATE_SCHEMA",
    "HARNESS_STEP_LIFECYCLE_VERSION",
    "HARNESS_WORKER_ACTIVITY_SCHEMA",
    "GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA",
    "GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA",
    "GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA",
    "GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA",
    "NORMALIZED_HARNESS_GRAPH_SCHEMA",
]
