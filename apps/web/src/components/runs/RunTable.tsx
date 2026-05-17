import Link from "next/link"
import { EmptyState } from "@/components/common/EmptyState"
import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime } from "@/lib/format"
import type { RunListItem } from "@/lib/types"

export function RunTable({ runs }: { runs: RunListItem[] }) {
  if (!runs.length) {
    return <EmptyState title="No runs found" message="No workflow runs match the current filters." />
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-white">
      <table className="w-full table-fixed border-collapse text-left text-sm">
        <thead className="bg-surface text-xs uppercase text-muted">
          <tr>
            <th className="w-48 px-4 py-3 font-medium">Run</th>
            <th className="w-36 px-4 py-3 font-medium">Workflow</th>
            <th className="w-32 px-4 py-3 font-medium">Profile</th>
            <th className="w-32 px-4 py-3 font-medium">Status</th>
            <th className="w-44 px-4 py-3 font-medium">Started</th>
            <th className="w-44 px-4 py-3 font-medium">Finished</th>
            <th className="w-24 px-4 py-3 font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id} className="border-t border-line">
              <td className="truncate px-4 py-3 font-medium text-ink">{run.run_id}</td>
              <td className="truncate px-4 py-3 text-muted">{run.workflow_id ?? "unknown"}</td>
              <td className="truncate px-4 py-3 text-muted">{run.profile ?? "n/a"}</td>
              <td className="px-4 py-3">
                <StatusBadge status={run.status} />
              </td>
              <td className="truncate px-4 py-3 text-muted">{formatDateTime(run.started_at)}</td>
              <td className="truncate px-4 py-3 text-muted">{formatDateTime(run.finished_at)}</td>
              <td className="px-4 py-3">
                <Link className="font-medium text-accent hover:underline" href={`/runs/${encodeURIComponent(run.run_id)}`}>
                  Open
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
