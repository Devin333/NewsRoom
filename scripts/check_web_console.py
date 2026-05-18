from __future__ import annotations

import json
from pathlib import Path


REQUIRED_FILES = [
    "apps/web/package.json",
    "apps/web/next.config.mjs",
    "apps/web/tsconfig.json",
    "apps/web/src/app/layout.tsx",
    "apps/web/src/app/page.tsx",
    "apps/web/src/app/settings/page.tsx",
    "apps/web/src/app/runs/page.tsx",
    "apps/web/src/app/runs/[runId]/page.tsx",
    "apps/web/src/app/reports/page.tsx",
    "apps/web/src/app/reports/[reportId]/page.tsx",
    "apps/web/src/app/workers/page.tsx",
    "apps/web/src/app/sources/page.tsx",
    "apps/web/src/app/memory/page.tsx",
    "apps/web/src/app/approvals/page.tsx",
    "apps/web/src/lib/api-client.ts",
    "apps/web/src/lib/types.ts",
    "apps/web/src/lib/format.ts",
    "apps/web/src/components/layout/AppShell.tsx",
    "apps/web/src/components/common/StatusBadge.tsx",
    "apps/web/src/components/common/EmptyState.tsx",
    "apps/web/src/components/common/ErrorState.tsx",
    "apps/web/src/components/runs/RunTable.tsx",
    "apps/web/src/components/runs/RunTimeline.tsx",
    "apps/web/src/components/runs/RunArtifacts.tsx",
    "apps/web/src/components/runs/RunOperationPanel.tsx",
    "apps/web/src/components/reports/ReportList.tsx",
    "apps/web/src/components/reports/ReportViewer.tsx",
    "apps/web/src/components/workers/WorkerStatusTable.tsx",
    "apps/web/src/components/sources/SourceHealthTable.tsx",
    "apps/web/src/components/memory/MemorySearchBox.tsx",
    "apps/web/src/components/approvals/ApprovalTable.tsx",
    "apps/web/README.md",
]

REQUIRED_PACKAGE_SCRIPTS = ["dev", "build", "start", "lint", "typecheck"]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    missing = [path for path in REQUIRED_FILES if not (root / path).exists()]
    if missing:
        for path in missing:
            print(f"missing={path}")
        return 1

    package_path = root / "apps/web/package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"invalid_package_json={exc}")
        return 1

    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        print("missing=apps/web/package.json scripts")
        return 1

    missing_scripts = [script for script in REQUIRED_PACKAGE_SCRIPTS if script not in scripts]
    if missing_scripts:
        for script in missing_scripts:
            print(f"missing_script={script}")
        return 1

    print("web_console=ok")
    print(f"required_files={len(REQUIRED_FILES)}")
    print(f"package_scripts={len(REQUIRED_PACKAGE_SCRIPTS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
