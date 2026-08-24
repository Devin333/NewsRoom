import { EmptyState } from "@/components/common/EmptyState"
import { WaitTable } from "@/components/waits/WaitTable"
import { safeApiGet } from "@/lib/api-client"
import type { GraphWaitListResponse, RunList } from "@/lib/types"

export default async function WaitsPage() {
  const runs = await safeApiGet<RunList>("/api/v2/graph-runs?limit=100")
  const candidateRuns = runs.data?.runs ?? []
  const waitResults = await Promise.all(
    candidateRuns
      .filter((run) => ["blocked", "waiting_for_human"].includes(run.status))
      .map((run) => safeApiGet<GraphWaitListResponse>(`/api/v2/graph-runs/${encodeURIComponent(run.run_id)}/waits`)),
  )
  const waits = waitResults.flatMap((result) => result.data?.waits ?? []).filter((wait) => wait.kind === "approval" && wait.status === "registered")
  const error = !runs.ok ? runs.errorMessage : waitResults.find((result) => !result.ok)?.errorMessage

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Graph Waits</h1>
        <p className="mt-0.5 text-sm text-muted">Durable human decisions bound to Graph identity</p>
      </div>
      {waits.length ? <WaitTable waits={waits} /> : <div className="rounded-xl border border-line bg-white p-5 shadow-card"><EmptyState title="No pending Graph Waits" message={error} /></div>}
    </div>
  )
}
