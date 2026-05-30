import { EmptyState } from "@/components/common/EmptyState"
import { StatusBadge } from "@/components/common/StatusBadge"
import { apiGet } from "@/lib/api-client"
import { formatDateTime } from "@/lib/format"
import type { HealthStatus, LatestReport, RunList, WorkerSummary } from "@/lib/types"

export default async function DashboardPage() {
  const [health, latestReport, recentRuns, workers] = await Promise.all([
    safeGet<HealthStatus>("/health"),
    safeGet<LatestReport>("/api/v1/reports/latest"),
    safeGet<RunList>("/api/v1/runs?limit=5"),
    safeGet<WorkerSummary>("/api/v1/workers")
  ])

  return (
    <main className="space-y-6">
      <header className="flex flex-col gap-2 border-b border-line pb-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-ink">Dashboard</h1>
            <p className="text-sm text-muted">Runtime health, latest report, and recent operational signals.</p>
          </div>
          <StatusBadge status={health.data?.status ?? health.errorCode ?? "unknown"} />
        </div>
      </header>

      <section className="grid gap-4 lg:grid-cols-4">
        <SummaryTile label="API Health" value={health.data?.status ?? "unavailable"} tone={health.ok ? "good" : "bad"} />
        <SummaryTile
          label="Latest Report"
          value={latestReport.data?.title ?? "None"}
          detail={latestReport.data?.report_id}
        />
        <SummaryTile
          label="Recent Runs"
          value={String(recentRuns.data?.run_count ?? 0)}
          detail="Last 5 runs"
        />
        <SummaryTile
          label="Workers"
          value={String(workers.data?.worker_count ?? 0)}
          detail="Queue summary"
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg border border-line bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-ink">Recent Runs</h2>
            <span className="text-xs text-muted">Updated on load</span>
          </div>
          {recentRuns.data?.runs?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full table-fixed border-collapse text-left text-sm">
                <thead className="text-xs uppercase text-muted">
                  <tr>
                    <th className="w-40 py-2 font-medium">Run</th>
                    <th className="w-36 py-2 font-medium">Workflow</th>
                    <th className="w-32 py-2 font-medium">Status</th>
                    <th className="w-48 py-2 font-medium">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.data.runs.map((run) => (
                    <tr key={run.run_id} className="border-t border-line">
                      <td className="truncate py-3 pr-3 font-medium text-ink">{run.run_id}</td>
                      <td className="truncate py-3 pr-3 text-muted">{run.workflow_id ?? "unknown"}</td>
                      <td className="py-3 pr-3">
                        <StatusBadge status={run.status} />
                      </td>
                      <td className="truncate py-3 text-muted">{formatDateTime(run.started_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No runs found" message={recentRuns.errorMessage ?? "Recent run history is empty."} />
          )}
        </div>

        <div className="rounded-lg border border-line bg-white p-4">
          <h2 className="mb-3 text-base font-semibold text-ink">Latest Report</h2>
          {latestReport.data ? (
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-xs uppercase text-muted">Title</p>
                <p className="font-medium text-ink">{latestReport.data.title ?? latestReport.data.report_id}</p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={latestReport.data.status} />
                <span className="text-muted">Quality {latestReport.data.quality_score ?? "n/a"}</span>
              </div>
              <p className="line-clamp-6 whitespace-pre-wrap text-muted">
                {latestReport.data.report_markdown ?? "No markdown preview available."}
              </p>
            </div>
          ) : (
            <EmptyState title="No report available" message={latestReport.errorMessage ?? "No latest report was returned."} />
          )}
        </div>
      </section>
    </main>
  )
}

function SummaryTile({
  label,
  value,
  detail,
  tone
}: {
  label: string
  value: string
  detail?: string
  tone?: "good" | "bad"
}) {
  const color = tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : "text-ink"
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <p className="text-xs uppercase text-muted">{label}</p>
      <p className={`mt-2 truncate text-xl font-semibold ${color}`}>{value}</p>
      {detail ? <p className="mt-1 truncate text-xs text-muted">{detail}</p> : null}
    </div>
  )
}

async function safeGet<T>(path: string): Promise<{ ok: boolean; data?: T; errorCode?: string; errorMessage?: string }> {
  try {
    return { ok: true, data: await apiGet<T>(path) }
  } catch (error) {
    const apiError = error as { code?: string; message?: string }
    return {
      ok: false,
      errorCode: apiError.code ?? "unavailable",
      errorMessage: apiError.message ?? "Request failed"
    }
  }
}
