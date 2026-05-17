import { EmptyState } from "@/components/common/EmptyState"
import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime, formatNumber } from "@/lib/format"
import type { QueueStatus, WorkerStatus } from "@/lib/types"

export function WorkerStatusTable({
  workers,
  queues
}: {
  workers: WorkerStatus[]
  queues: QueueStatus[]
}) {
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-ink">Workers</h2>
        {workers.length ? (
          <Table
            headers={["Worker", "Status", "Queue", "Heartbeat"]}
            rows={workers.map((worker) => [
              worker.worker_id ?? "unknown",
              <StatusBadge key="status" status={worker.status ?? "unknown"} />,
              worker.queue_name ?? "n/a",
              formatDateTime(worker.heartbeat_at)
            ])}
          />
        ) : (
          <EmptyState title="No workers" message="No worker status records were returned." />
        )}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-ink">Queues</h2>
        {queues.length ? (
          <Table
            headers={["Queue", "Pending", "Leased", "Dead letters"]}
            rows={queues.map((queue) => [
              queue.queue_name ?? "unknown",
              formatNumber(queue.pending_count),
              formatNumber(queue.leased_count),
              formatNumber(queue.dead_letter_count)
            ])}
          />
        ) : (
          <EmptyState title="No queues" message="No queue status records were returned." />
        )}
      </section>
    </div>
  )
}

function Table({ headers, rows }: { headers: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-white">
      <table className="w-full table-fixed border-collapse text-left text-sm">
        <thead className="bg-surface text-xs uppercase text-muted">
          <tr>
            {headers.map((header) => (
              <th key={header} className="w-40 px-4 py-3 font-medium">{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-t border-line">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="truncate px-4 py-3 text-muted">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
