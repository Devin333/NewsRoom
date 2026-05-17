import { ErrorState } from "@/components/common/ErrorState"
import { WorkerStatusTable } from "@/components/workers/WorkerStatusTable"
import { safeApiGet } from "@/lib/api-client"
import type { QueueStatus, WorkerStatusResponse } from "@/lib/types"

export default async function WorkersPage() {
  const [workers, queues] = await Promise.all([
    safeApiGet<WorkerStatusResponse>("/api/v1/workers"),
    safeApiGet<{ queues?: QueueStatus[] }>("/api/v1/queues")
  ])

  const workerRows = workers.data?.workers ?? []
  const queueRows = workers.data?.queues ?? queues.data?.queues ?? []

  return (
    <main className="space-y-6">
      <header className="border-b border-line pb-4">
        <h1 className="text-2xl font-semibold text-ink">Workers</h1>
        <p className="text-sm text-muted">Worker state, queue depth, stale workers, and dead letter signals.</p>
      </header>

      {workers.ok || queues.ok ? (
        <WorkerStatusTable workers={workerRows} queues={queueRows} />
      ) : (
        <ErrorState message={workers.errorMessage ?? queues.errorMessage} requestId={workers.requestId ?? queues.requestId} />
      )}
    </main>
  )
}
