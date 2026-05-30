import Link from "next/link"
import { StatusBadge } from "@/components/common/StatusBadge"
import { apiGet } from "@/lib/api-client"
import { formatDateTime, formatScore } from "@/lib/format"
import type { HealthStatus, LatestReport, RunList, WorkerSummary } from "@/lib/types"

async function safeGet<T>(path: string) {
  try { return { ok: true, data: await apiGet<T>(path) } }
  catch (e: unknown) {
    const err = e as { code?: string; message?: string }
    return { ok: false, errorCode: err.code ?? "unavailable", errorMessage: err.message ?? "Request failed" }
  }
}

export default async function DashboardPage() {
  const [health, latestReport, recentRuns, workers] = await Promise.all([
    safeGet<HealthStatus>("/health"),
    safeGet<LatestReport>("/api/v1/reports/latest"),
    safeGet<RunList>("/api/v1/runs?limit=5"),
    safeGet<WorkerSummary>("/api/v1/workers")
  ])

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Dashboard</h1>
          <p className="mt-0.5 text-sm text-muted">Runtime health and recent activity</p>
        </div>
        <StatusBadge status={health.data?.status ?? health.errorCode ?? "unknown"} />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="API" value={health.data?.status ?? "—"} ok={health.ok} />
        <StatCard label="Latest report" value={latestReport.data?.title ?? "None"} sub={latestReport.data?.report_id?.slice(0, 8)} />
        <StatCard label="Recent runs" value={String(recentRuns.data?.run_count ?? 0)} sub="last 5" />
        <StatCard label="Workers" value={String((workers.data as { worker_count?: number })?.worker_count ?? 0)} />
      </div>

      <div className="grid gap-6 xl:grid-cols-5">
        {/* Recent runs */}
        <div className="xl:col-span-3 rounded-xl border border-line bg-white p-5 shadow-card">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">Recent Runs</h2>
            <Link href="/runs" className="text-xs text-accent hover:underline">View all →</Link>
          </div>
          {recentRuns.data?.runs?.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line">
                  <th className="pb-2 pr-4 text-left text-xs font-medium text-muted">Run</th>
                  <th className="pb-2 pr-4 text-left text-xs font-medium text-muted">Status</th>
                  <th className="pb-2 text-left text-xs font-medium text-muted">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {recentRuns.data.runs.map((run) => (
                  <tr key={run.run_id} className="group">
                    <td className="py-2.5 pr-4">
                      <Link href={`/runs/${run.run_id}`} className="font-mono text-xs text-ink hover:text-accent">
                        {run.run_id.slice(0, 12)}…
                      </Link>
                      <p className="text-xs text-subtle">{run.workflow_id ?? ""}</p>
                    </td>
                    <td className="py-2.5 pr-4"><StatusBadge status={run.status} /></td>
                    <td className="py-2.5 text-xs text-muted">{run.started_at ? formatDateTime(run.started_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-muted">No recent runs.</p>
          )}
        </div>

        {/* Latest report */}
        <div className="xl:col-span-2 rounded-xl border border-line bg-white p-5 shadow-card">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">Latest Report</h2>
            <Link href="/reports" className="text-xs text-accent hover:underline">View all →</Link>
          </div>
          {latestReport.data ? (
            <div className="space-y-3">
              <div>
                <p className="font-medium text-ink">{latestReport.data.title ?? latestReport.data.report_id}</p>
                <div className="mt-1 flex items-center gap-2">
                  <StatusBadge status={latestReport.data.status} />
                  {latestReport.data.quality_score != null && (
                    <span className="text-xs text-muted">Quality {formatScore(latestReport.data.quality_score)}</span>
                  )}
                </div>
              </div>
              {latestReport.data.report_markdown && (
                <p className="line-clamp-5 text-xs leading-relaxed text-muted">
                  {latestReport.data.report_markdown}
                </p>
              )}
              {latestReport.data.report_id && (
                <Link href={`/reports/${latestReport.data.report_id}`} className="text-xs text-accent hover:underline">
                  Read full report →
                </Link>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted">No report available.</p>
          )}
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, sub, ok }: { label: string; value: string; sub?: string; ok?: boolean }) {
  return (
    <div className="rounded-xl border border-line bg-white p-4 shadow-card">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className={`mt-1.5 truncate text-lg font-semibold ${ok === false ? "text-bad" : ok === true ? "text-good" : "text-ink"}`}>
        {value}
      </p>
      {sub && <p className="mt-0.5 truncate text-xs text-subtle">{sub}</p>}
    </div>
  )
}
