import { ErrorState } from "@/components/common/ErrorState"
import { StatusBadge } from "@/components/common/StatusBadge"
import { ReportViewer } from "@/components/reports/ReportViewer"
import { safeApiGet } from "@/lib/api-client"
import { formatScore, stringifyJson } from "@/lib/format"
import type { ReportDetail, ReportMarkdown, ReportQuality } from "@/lib/types"

export default async function ReportDetailPage({ params }: { params: { reportId: string } }) {
  const reportId = decodeURIComponent(params.reportId)
  const encodedReportId = encodeURIComponent(reportId)
  const [report, markdown, quality] = await Promise.all([
    safeApiGet<ReportDetail>(`/api/v1/reports/${encodedReportId}`),
    safeApiGet<ReportMarkdown>(`/api/v1/reports/${encodedReportId}/markdown`),
    safeApiGet<ReportQuality>(`/api/v1/reports/${encodedReportId}/quality`)
  ])
  const markdownBody =
    markdown.data?.markdown ??
    markdown.data?.report_markdown ??
    markdown.data?.content ??
    report.data?.report_markdown

  return (
    <main className="space-y-6">
      <header className="border-b border-line pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="break-all text-2xl font-semibold text-ink">
              {report.data?.title ?? reportId}
            </h1>
            <p className="text-sm text-muted">Report detail, markdown body, and quality context.</p>
          </div>
          {report.data?.status ? <StatusBadge status={report.data.status} /> : null}
        </div>
      </header>

      {report.ok && report.data ? (
        <section className="grid gap-4 lg:grid-cols-4">
          <Summary label="Report" value={report.data.report_id} />
          <Summary label="Run" value={report.data.run_id} />
          <Summary label="Quality" value={formatScore(report.data.quality_score)} />
          <Summary label="Sources" value={String(report.data.source_count ?? "n/a")} />
        </section>
      ) : (
        <ErrorState message={report.errorMessage} requestId={report.requestId} />
      )}

      <section className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-ink">Markdown Preview</h2>
          {markdown.ok || report.data?.report_markdown ? (
            <ReportViewer markdown={markdownBody} />
          ) : (
            <ErrorState message={markdown.errorMessage} requestId={markdown.requestId} />
          )}
        </div>

        <div className="space-y-6">
          <Panel title="Quality Summary">
            {quality.ok ? (
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-ink">
                {stringifyJson(quality.data)}
              </pre>
            ) : (
              <ErrorState message={quality.errorMessage} requestId={quality.requestId} />
            )}
          </Panel>
          <Panel title="JSON View">
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-ink">
              {stringifyJson(report.data?.report_json ?? report.data)}
            </pre>
          </Panel>
        </div>
      </section>
    </main>
  )
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <p className="text-xs uppercase text-muted">{label}</p>
      <p className="mt-2 truncate font-medium text-ink">{value}</p>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-white p-4">
      <h2 className="mb-3 text-base font-semibold text-ink">{title}</h2>
      {children}
    </section>
  )
}
