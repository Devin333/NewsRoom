import Link from "next/link"
import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime } from "@/lib/format"
import type { RunListItem } from "@/lib/types"

export function RunTable({ runs }: { runs: RunListItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Run ID</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Workflow</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Profile</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Status</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Started</th>
            <th className="pb-3 text-left text-xs font-medium text-muted">Finished</th>
            <th className="pb-3 text-right text-xs font-medium text-muted"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {runs.map((run) => (
            <tr key={run.run_id} className="group">
              <td className="py-3 pr-4 font-mono text-xs text-ink">{run.run_id.slice(0, 12)}…</td>
              <td className="py-3 pr-4 text-muted">{run.workflow_id ?? "—"}</td>
              <td className="py-3 pr-4 text-muted">{run.profile ?? "—"}</td>
              <td className="py-3 pr-4"><StatusBadge status={run.status} /></td>
              <td className="py-3 pr-4 text-muted">{run.started_at ? formatDateTime(run.started_at) : "—"}</td>
              <td className="py-3 text-muted">{run.finished_at ? formatDateTime(run.finished_at) : "—"}</td>
              <td className="py-3 pl-4 text-right">
                <Link href={`/runs/${run.run_id}`} className="text-xs text-accent opacity-0 transition-opacity group-hover:opacity-100 hover:underline">
                  View →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
