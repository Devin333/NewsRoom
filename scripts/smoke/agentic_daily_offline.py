from __future__ import annotations

import argparse

from core.framework.specs import WorkflowStatus
from interfaces.services.run_service import RunApplicationService
from workflows.daily_intelligence.profiles import PROFILE_AGENTIC_OFFLINE


DEFAULT_TOPIC = "AI agents"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.smoke.agentic_daily_offline",
        description="Run the deterministic agentic offline Daily Intelligence smoke.",
    )
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--source-limit", type=int, default=2)
    parser.add_argument("--artifact-root", default=".newsroom/runs")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    result = RunApplicationService(artifact_root=args.artifact_root).run_daily_agentic(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic=args.topic,
        source_limit=args.source_limit,
        run_id=args.run_id,
    )

    print(f"status={result.status.value}")
    print(f"run_id={result.run_id}")
    print(f"profile={PROFILE_AGENTIC_OFFLINE}")
    print(f"artifact_dir={result.artifact_dir}")
    print(f"manifest={result.manifest_path}")
    print(f"events={result.events_path}")
    if result.error:
        print(f"error={result.error.get('message')}")
    return 0 if result.status == WorkflowStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
