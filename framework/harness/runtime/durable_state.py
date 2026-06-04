from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.event_log import HarnessEventLogEntry, InMemoryHarnessEventLog
from framework.harness.control_plane.transcript import HarnessTranscriptEntry, InMemoryHarnessTranscriptStore
from framework.harness.runtime.checkpoint import HarnessCheckpoint
from framework.harness.runtime.checkpoint_store import InMemoryHarnessCheckpointStore
from framework.shared.json import to_jsonable


@dataclass
class HarnessDurableState:
    event_log: InMemoryHarnessEventLog = field(default_factory=InMemoryHarnessEventLog)
    transcripts: InMemoryHarnessTranscriptStore = field(default_factory=InMemoryHarnessTranscriptStore)
    checkpoints: InMemoryHarnessCheckpointStore = field(default_factory=InMemoryHarnessCheckpointStore)

    def append_event(self, entry: HarnessEventLogEntry) -> HarnessEventLogEntry:
        return self.event_log.append(entry)

    def append_transcript(self, entry: HarnessTranscriptEntry) -> HarnessTranscriptEntry:
        return self.transcripts.append(entry)

    def save_checkpoint(self, checkpoint: HarnessCheckpoint) -> HarnessCheckpoint:
        return self.checkpoints.save_checkpoint(checkpoint)

    def export_run(self, run_id: str) -> dict[str, Any]:
        latest_checkpoint = self.checkpoints.latest_for_run(run_id)
        return {
            "run_id": run_id,
            "events": [entry.to_dict() for entry in self.event_log.entries_for_run(run_id)],
            "transcript": self.transcripts.export_run(run_id).to_dict(),
            "latest_checkpoint": latest_checkpoint.to_dict() if latest_checkpoint is not None else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable({"events": self.event_log.to_dict()})


__all__ = ["HarnessDurableState"]
