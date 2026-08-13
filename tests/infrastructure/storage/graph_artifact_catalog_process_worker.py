from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from framework.harness.artifacts.catalog import ArtifactCatalogRegistrationRequest
from framework.harness.runtime import ArtifactRecord
from framework.shared.json import stable_json_dumps
from infrastructure.storage.artifacts import LocalJsonArtifactCatalog


def main() -> int:
    if len(sys.argv) != 6:
        return 2
    root, record_path, start_path, result_path = map(Path, sys.argv[1:5])
    verified_at = datetime.fromisoformat(sys.argv[5].replace("Z", "+00:00"))
    deadline = time.monotonic() + 10
    while not start_path.exists():
        if time.monotonic() >= deadline:
            return 3
        time.sleep(0.01)
    record = ArtifactRecord.from_dict(json.loads(record_path.read_text(encoding="utf-8")))
    result = LocalJsonArtifactCatalog(root).register(
        ArtifactCatalogRegistrationRequest.from_verified_record(
            record,
            verified_at=verified_at,
        )
    )
    result_path.write_text(stable_json_dumps(result.to_dict()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
