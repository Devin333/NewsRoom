"""Safe graph inspection projections.

Only structural identities, typed statuses, counters, and checksum references
are exposed. Worker payloads, prompts, signal bodies, secrets, and arbitrary
state metadata are deliberately excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from framework.harness.control_plane.graph_checkpoint import HarnessGraphReplayReport
from framework.harness.control_plane.graph_state import HarnessGraphState
from framework.harness.workflow.canonical import freeze_json, thaw_json
from framework.harness.workflow.versioning import HARNESS_GRAPH_INSPECTION_SCHEMA


@dataclass(frozen=True, slots=True)
class HarnessGraphInspection:
    projection: Mapping[str, Any]

    def __post_init__(self) -> None:
        projection = freeze_json(self.projection, "graph_inspection")
        if not isinstance(projection, Mapping):
            raise TypeError("projection must be a mapping")
        object.__setattr__(self, "projection", projection)

    @classmethod
    def from_state(
        cls,
        state: HarnessGraphState,
        *,
        replay_report: HarnessGraphReplayReport | None = None,
    ) -> "HarnessGraphInspection":
        if not isinstance(state, HarnessGraphState):
            raise TypeError("state must be HarnessGraphState")
        if replay_report is not None and not isinstance(
            replay_report,
            HarnessGraphReplayReport,
        ):
            raise TypeError("replay_report must be HarnessGraphReplayReport")
        nodes = tuple(
            {
                "node_instance_id": node.instance_id,
                "node_id": node.identity.node_id,
                "node_kind": node.node_kind.value,
                "status": node.status.value,
                "step_id": node.step_id,
                "step_phase": (
                    None if node.step_status is None else node.step_status.value
                ),
                "attempt": node.attempt,
                "activation_ordinal": node.identity.activation_ordinal,
                "branch_path": list(node.identity.branch_path),
                "iteration_vector": [
                    item.to_dict() for item in node.identity.iteration_vector
                ],
                "last_event_sequence": node.last_event_sequence,
                "terminal_reason": node.terminal_reason,
                "evidence_refs": [item.evidence_ref for item in node.evidence_refs],
                "output_refs": {
                    key: node.output_refs[key] for key in sorted(node.output_refs)
                },
            }
            for node in state.node_instances
        )
        projection = {
            "schema_version": HARNESS_GRAPH_INSPECTION_SCHEMA,
            "run_id": state.run_id,
            "graph": state.graph_ref.to_dict(),
            "lifecycle": state.lifecycle.value,
            "outcome": state.outcome.value,
            "counts": {
                "ready": len(state.ready_node_ids),
                "running": len(state.running_node_ids),
                "waiting": len(state.waiting_node_ids),
                "terminal": len(state.terminal_node_ids),
                "active_activities": len(state.active_activities),
            },
            "node_instances": list(nodes),
            "joins": [
                {
                    "join_node_instance_id": item.join_instance_id,
                    "fork_node_instance_id": item.fork_instance_id,
                    "kind": item.join_kind.value,
                    "status": item.status.value,
                    "required_branch_ids": list(item.required_branch_ids),
                    "completed_branch_instances": dict(
                        item.completed_branch_instances
                    ),
                    "winner_branch_id": item.winner_branch_id,
                    "terminal_event_refs": dict(item.terminal_event_refs),
                    "last_event_sequence": item.last_event_sequence,
                }
                for item in state.join_states
            ],
            "loops": [item.to_dict() for item in state.loop_counters],
            "waits": [
                {
                    "wait_id": item.wait_id,
                    "node_instance_id": item.node_instance_id,
                    "kind": item.kind.value,
                    "status": item.status.value,
                    "registered_sequence": item.registered_sequence,
                    "last_event_sequence": item.last_event_sequence,
                    "deadline_ref": item.deadline_ref,
                    "resolution_event_ref": item.resolution_event_ref,
                }
                for item in state.wait_registrations
            ],
            "compensation": [
                {
                    "entry_id": item.entry_id,
                    "origin_node_instance_id": item.origin_node_instance_id,
                    "compensation_node_instance_id": (
                        item.compensation_node_instance_id
                    ),
                    "effect_outcome_ref": item.effect_outcome_ref,
                    "effect_commit_sequence": item.effect_commit_sequence,
                    "handler_ref": item.handler_ref.exact_ref,
                    "activity_ref": item.activity_ref.exact_ref,
                    "status": item.status.value,
                    "attempt": item.attempt,
                    "outcome_ref": item.outcome_ref,
                    "last_event_sequence": item.last_event_sequence,
                }
                for item in state.compensation_stack
            ],
            "budgets": [item.to_dict() for item in state.budgets.counters],
            "last_event_sequence": state.last_event_sequence,
            "projection_checksum": state.projection_checksum,
            "terminal_reason": state.terminal_reason_code,
            "terminal_evidence_ref": state.terminal_evidence_ref,
            "replay": (
                None
                if replay_report is None
                else {
                    "mode": replay_report.mode,
                    "through_sequence": replay_report.through_sequence,
                    "projection_checksum": replay_report.projection_checksum,
                    "verified_decision_count": len(
                        replay_report.verified_decision_checksums
                    ),
                    "pending_cause_count": len(
                        replay_report.pending_cause_checksums
                    ),
                    "quarantine_reason": replay_report.quarantine_reason,
                }
            ),
        }
        return cls(projection)

    def to_dict(self) -> dict[str, Any]:
        return thaw_json(self.projection)


__all__ = ["HarnessGraphInspection"]
