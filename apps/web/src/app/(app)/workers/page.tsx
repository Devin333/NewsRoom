import { WorkerStatusTable } from "@/components/workers/WorkerStatusTable"
import { EmptyState } from "@/components/common/EmptyState"
import { safeApiGet } from "@/lib/api-client"
import Link from "next/link"
import type { WorkerStatusResponse } from "@/lib/types"

export default async function WorkersPage({
  searchParams
}: {
  searchParams: Promise<{ stale?: string }>
}) {
  const sp = await searchParams
  const stale = [30, 60, 300].includes(Number(sp.stale)) ? Number(sp.stale) : 60
  const res = await safeApiGet<WorkerStatusResponse>(`/api/v1/workers?stale_after_seconds=${stale}`)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Workers</h1>
          <p className="mt-0.5 text-sm text-muted">Worker and queue status</p>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted">
          Stale after
          {[30, 60, 300].map((n) => (
            <Link
              key={n}
              href={`/workers?stale=${n}`}
              className={`rounded px-2 py-0.5 ${stale === n ? "bg-ink text-white" : "hover:text-ink"}`}
            >
              {n}s
            </Link>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-line bg-white p-5 shadow-card">
        {res.ok && res.data ? (
          <WorkerStatusTable
            workers={res.data.workers ?? []}
            queues={res.data.queues ?? []}
          />
        ) : (
          <EmptyState title="No worker data" message={res.errorMessage} />
        )}
      </div>
    </div>
  )
}
