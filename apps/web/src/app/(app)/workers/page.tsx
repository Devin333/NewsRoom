import Link from "next/link"
import { ErrorState } from "@/components/common/ErrorState"
import { WorkerStatusTable } from "@/components/workers/WorkerStatusTable"
import { safeApiGet } from "@/lib/api-client"
import type { QueueStatus, WorkerStatusResponse } from "@/lib/types"

const STALE_OPTIONS = [30, 60, 300]

export default async function WorkersPage({
  searchParams
}: {
  searchParams: { stale_after_seconds?: string }
}) {
  const staleAfterSeconds = normalizeStaleAfterSeconds(searchParams.stale_after_seconds)
  const [workers, queues] = await Promise.all([
    safeApiGet<WorkerStatusResponse>(`/api/v1/workers?stale_after_seconds=${staleAfterSeconds}`),
    safeApiGet<{ queues?: QueueStatus[] }>("/api/v1/queues")
  ])

  const workerRows = workers.data?.workers ?? []
  const queueRows = workers.data?.queues ?? queues.data?.queues ?? []

  return (
    <main className="space-y-6">
      <header className="flex flex-col gap-4 border-b border-line pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Workers</h1>
          <p className="text-sm text-muted">Worker state, queue depth, stale workers, and dead letter signals.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {STALE_OPTIONS.map((option) => (
            <FilterLink
              key={option}
              active={staleAfterSeconds === option}
              href={`/workers?stale_after_seconds=${option}`}
              label={`Stale ${option}s`}
            />
          ))}
        </div>
      </header>

      {workers.ok || queues.ok ? (
        <WorkerStatusTable workers={workerRows} queues={queueRows} />
      ) : (
        <ErrorState message={workers.errorMessage ?? queues.errorMessage} requestId={workers.requestId ?? queues.requestId} />
      )}
    </main>
  )
}

function FilterLink({ active, href, label }: { active: boolean; href: string; label: string }) {
  return (
    <Link
      href={href}
      className={`rounded-md border px-3 py-2 text-sm font-medium ${
        active ? "border-accent bg-accent text-white" : "border-line bg-white text-muted hover:text-ink"
      }`}
    >
      {label}
    </Link>
  )
}

function normalizeStaleAfterSeconds(value?: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 60
  }
  return Math.min(Math.floor(parsed), 3600)
}
