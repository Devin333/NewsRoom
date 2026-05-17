import { EmptyState } from "@/components/common/EmptyState"
import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime, formatNumber } from "@/lib/format"
import type { SourceHealthItem } from "@/lib/types"

export function SourceHealthTable({ sources }: { sources: SourceHealthItem[] }) {
  if (!sources.length) {
    return <EmptyState title="No source health" message="No source health records were returned." />
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-white">
      <table className="w-full table-fixed border-collapse text-left text-sm">
        <thead className="bg-surface text-xs uppercase text-muted">
          <tr>
            <th className="w-48 px-4 py-3 font-medium">Source</th>
            <th className="w-44 px-4 py-3 font-medium">Name</th>
            <th className="w-32 px-4 py-3 font-medium">Status</th>
            <th className="w-44 px-4 py-3 font-medium">Last success</th>
            <th className="w-44 px-4 py-3 font-medium">Last failure</th>
            <th className="w-32 px-4 py-3 font-medium">Failures</th>
            <th className="w-44 px-4 py-3 font-medium">Cooldown</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => (
            <tr key={source.source_id} className="border-t border-line">
              <td className="truncate px-4 py-3 font-medium text-ink">{source.source_id}</td>
              <td className="truncate px-4 py-3 text-muted">{source.source_name ?? "n/a"}</td>
              <td className="px-4 py-3">
                <StatusBadge status={source.status} />
              </td>
              <td className="truncate px-4 py-3 text-muted">{formatDateTime(source.last_success_at)}</td>
              <td className="truncate px-4 py-3 text-muted">{formatDateTime(source.last_failure_at)}</td>
              <td className="truncate px-4 py-3 text-muted">{formatNumber(source.consecutive_failures)}</td>
              <td className="truncate px-4 py-3 text-muted">{formatDateTime(source.cooldown_until)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
