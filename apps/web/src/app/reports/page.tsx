import { ErrorState } from "@/components/common/ErrorState"
import { ReportList } from "@/components/reports/ReportList"
import { safeApiGet } from "@/lib/api-client"
import type { ReportList as ReportListData } from "@/lib/types"

export default async function ReportsPage({
  searchParams
}: {
  searchParams: { limit?: string }
}) {
  const limit = normalizeLimit(searchParams.limit)
  const reports = await safeApiGet<ReportListData>(`/api/v1/reports?limit=${limit}`)

  return (
    <main className="space-y-6">
      <header className="border-b border-line pb-4">
        <h1 className="text-2xl font-semibold text-ink">Reports</h1>
        <p className="text-sm text-muted">Generated reports, quality scores, and report detail links.</p>
      </header>

      {reports.ok && reports.data ? (
        <ReportList reports={reports.data.reports ?? []} />
      ) : (
        <ErrorState message={reports.errorMessage} requestId={reports.requestId} />
      )}
    </main>
  )
}

function normalizeLimit(value?: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 1) {
    return 20
  }
  return Math.min(Math.floor(parsed), 100)
}
