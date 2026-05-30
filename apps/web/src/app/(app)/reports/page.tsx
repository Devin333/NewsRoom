import Link from "next/link"
import { ReportList } from "@/components/reports/ReportList"
import { EmptyState } from "@/components/common/EmptyState"
import { safeApiGet } from "@/lib/api-client"
import type { ReportList as ReportListType } from "@/lib/types"

export default async function ReportsPage({
  searchParams
}: {
  searchParams: Promise<{ limit?: string }>
}) {
  const sp = await searchParams
  const limit = [20, 50, 100].includes(Number(sp.limit)) ? Number(sp.limit) : 20
  const res = await safeApiGet<ReportListType>(`/api/v1/reports?limit=${limit}`)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Reports</h1>
          <p className="mt-0.5 text-sm text-muted">Generated intelligence reports</p>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted">
          Show
          {[20, 50, 100].map((n) => (
            <Link
              key={n}
              href={`/reports?limit=${n}`}
              className={`rounded px-2 py-0.5 ${limit === n ? "bg-ink text-white" : "hover:text-ink"}`}
            >
              {n}
            </Link>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-line bg-white p-5 shadow-card">
        {res.ok && res.data?.reports?.length ? (
          <ReportList reports={res.data.reports} />
        ) : (
          <EmptyState title="No reports found" message={res.errorMessage} />
        )}
      </div>
    </div>
  )
}
