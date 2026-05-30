import { notFound } from "next/navigation"
import { StatusBadge } from "@/components/common/StatusBadge"
import { ReportViewer } from "@/components/reports/ReportViewer"
import { safeApiGet } from "@/lib/api-client"
import { formatDateTime, formatScore, stringifyJson } from "@/lib/format"
import type { ReportDetail, ReportMarkdown, ReportQuality } from "@/lib/types"

export default async function ReportDetailPage({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params
  const [report, markdown, quality] = await Promise.all([
    safeApiGet<ReportDetail>(`/api/v1/reports/${reportId}`),
    safeApiGet<ReportMarkdown>(`/api/v1/reports/${reportId}/markdown`),
    safeApiGet<ReportQuality>(`/api/v1/reports/${reportId}/quality`)
  ])

  if (!report.ok || !report.data) return notFound()
  const r = report.data
  const md = markdown.data?.markdown ?? markdown.data?.report_markdown ?? markdown.data?.content

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-ink">{r.title ?? reportId}</h1>
          {r.summary && <p className="mt-1 text-sm text-muted">{r.summary}</p>}
        </div>
        <StatusBadge status={r.status} />
      </div>

      {/* Meta */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Quality", value: r.quality_score != null ? formatScore(r.quality_score) : "—" },
          { label: "Citation", value: r.citation_coverage_score != null ? formatScore(r.citation_coverage_score) : "—" },
          { label: "Sources", value: String(r.source_count ?? "—") },
          { label: "Created", value: r.created_at ? formatDateTime(r.created_at) : "—" }
        ].map(({ label, value }) => (
          <div key={label} className="rounded-lg border border-line bg-white p-3 shadow-card">
            <p className="text-xs font-medium text-muted">{label}</p>
            <p className="mt-1 text-sm font-semibold text-ink">{value}</p>
          </div>
        ))}
      </div>

      {/* Markdown */}
      {md && (
        <div className="rounded-xl border border-line bg-white p-5 shadow-card">
          <h2 className="mb-4 text-sm font-semibold text-ink">Report</h2>
          <ReportViewer markdown={md} />
        </div>
      )}

      {/* Quality detail */}
      {quality.data?.quality_result && (
        <div className="rounded-xl border border-line bg-white p-5 shadow-card">
          <h2 className="mb-4 text-sm font-semibold text-ink">Quality Detail</h2>
          <pre className="overflow-x-auto rounded-md bg-surface p-3 font-mono text-xs text-ink">
            {stringifyJson(quality.data.quality_result)}
          </pre>
        </div>
      )}
    </div>
  )
}
