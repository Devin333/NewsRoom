import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime } from "@/lib/format"
import type { WorkerStatus, QueueStatus } from "@/lib/types"

export function WorkerStatusTable({
  workers,
  queues
}: {
  workers: WorkerStatus[]
  queues: QueueStatus[]
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div>
        <h3 className="mb-3 text-sm font-semibold text-ink">Workers</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line">
              <th className="pb-2 pr-4 text-left text-xs font-medium text-muted">ID</th>
              <th className="pb-2 pr-4 text-left text-xs font-medium text-muted">Status</th>
              <th className="pb-2 text-left text-xs font-medium text-muted">Heartbeat</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {workers.length ? workers.map((w, i) => (
              <tr key={w.worker_id ?? i}>
                <td className="py-2.5 pr-4 font-mono text-xs text-ink">{w.worker_id ?? "—"}</td>
                <td className="py-2.5 pr-4">
                  <StatusBadge status={w.stale ? "unavailable" : (w.status ?? "unknown")} />
                </td>
                <td className="py-2.5 text-xs text-muted">
                  {w.last_heartbeat_at ? formatDateTime(w.last_heartbeat_at) : "—"}
                </td>
              </tr>
            )) : (
              <tr><td colSpan={3} className="py-4 text-center text-xs text-muted">No workers</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold text-ink">Queues</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line">
              <th className="pb-2 pr-4 text-left text-xs font-medium text-muted">Queue</th>
              <th className="pb-2 pr-4 text-right text-xs font-medium text-muted">Pending</th>
              <th className="pb-2 pr-4 text-right text-xs font-medium text-muted">Leased</th>
              <th className="pb-2 text-right text-xs font-medium text-muted">Dead</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {queues.length ? queues.map((q, i) => (
              <tr key={q.queue_name ?? i}>
                <td className="py-2.5 pr-4 font-mono text-xs text-ink">{q.queue_name ?? "—"}</td>
                <td className="py-2.5 pr-4 text-right text-xs text-muted">{q.pending_count ?? 0}</td>
                <td className="py-2.5 pr-4 text-right text-xs text-muted">{q.leased_count ?? 0}</td>
                <td className="py-2.5 text-right text-xs text-muted">{q.dead_letter_count ?? 0}</td>
              </tr>
            )) : (
              <tr><td colSpan={4} className="py-4 text-center text-xs text-muted">No queues</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
