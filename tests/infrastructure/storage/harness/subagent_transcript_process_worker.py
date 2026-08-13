from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from framework.harness import (
    SubAgentContextEvidence,
    SubAgentOutputDocument,
    SubAgentTranscript,
)
from framework.shared.json import stable_json_dumps
from infrastructure.storage.harness import FilesystemSubAgentTranscriptStore


def main() -> int:
    if len(sys.argv) != 5:
        return 2
    root, payload_path, start_path, receipt_path = map(Path, sys.argv[1:])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 10
    while not start_path.exists():
        if time.monotonic() >= deadline:
            return 3
        time.sleep(0.01)
    store = FilesystemSubAgentTranscriptStore(
        root,
        clock=lambda: datetime(2026, 8, 13, 1, 2, 3, tzinfo=UTC),
    )
    receipt = store.write(
        SubAgentContextEvidence.from_dict(payload["context"]),
        SubAgentOutputDocument.from_dict(payload["output"]),
        SubAgentTranscript.from_dict(payload["transcript"]),
    )
    receipt_path.write_text(stable_json_dumps(receipt.to_dict()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
