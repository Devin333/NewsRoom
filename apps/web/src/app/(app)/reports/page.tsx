import Link from "next/link"
import { ErrorState } from "@/components/common/ErrorState"
import { ReportList } from "@/components/reports/ReportList"
import { safeApiGet } from "@/lib/api-client"
import type { ReportList as ReportListData } from "@/lib/types"

const LIMIT_OPTIONS = [20, 50, 100]

export default async function ReportsPage({
  searchParams
}: {
  searchParams: { limit?: string }
}) {
  const limit = normalizeLimit(searchParams.limit)
  const reports = await safeApiGet<ReportListData>(`/api/v1/reports?limit=${limit}`)

  return (
    <main className="space-y-6">
      <header className="flex flex-col gap-4 border-b border-line pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Reports</h1>
          <p className="text-sm text-muted">Generated reports, quality scores, and report detail links.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {LIMIT_OPTIONS.map((option) => (
            <FilterLink
              key={option}
              active={limit === option}
              href={`/reports?limit=${option}`}
              label={`Limit ${option}`}
            />
          ))}
        </div>
      </header>

      {reports.ok && reports.data ? (
        <ReportList reports={reports.data.reports ?? []} />
      ) : (
        <ErrorState message={reports.errorMessage} requestId={reports.requestId} />
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

function normalizeLimit(value?: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 1) {
    return 20
  }
  return Math.min(Math.floor(parsed), 100)
}
