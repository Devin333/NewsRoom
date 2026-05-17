import Link from "next/link"
import { EmptyState } from "@/components/common/EmptyState"
import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime, formatScore } from "@/lib/format"
import type { ReportListItem } from "@/lib/types"

export function ReportList({ reports }: { reports: ReportListItem[] }) {
  if (!reports.length) {
    return <EmptyState title="No reports found" message="No reports are available for the current query." />
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-white">
      <table className="w-full table-fixed border-collapse text-left text-sm">
        <thead className="bg-surface text-xs uppercase text-muted">
          <tr>
            <th className="w-52 px-4 py-3 font-medium">Report</th>
            <th className="w-48 px-4 py-3 font-medium">Run</th>
            <th className="w-64 px-4 py-3 font-medium">Title</th>
            <th className="w-32 px-4 py-3 font-medium">Status</th>
            <th className="w-28 px-4 py-3 font-medium">Quality</th>
            <th className="w-44 px-4 py-3 font-medium">Created</th>
            <th className="w-24 px-4 py-3 font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {reports.map((report) => {
            const reportId = report.report_id ?? report.run_id
            return (
              <tr key={reportId} className="border-t border-line">
                <td className="truncate px-4 py-3 font-medium text-ink">{reportId}</td>
                <td className="truncate px-4 py-3 text-muted">{report.run_id}</td>
                <td className="truncate px-4 py-3 text-muted">{report.title ?? "Untitled"}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={report.status ?? "unknown"} />
                </td>
                <td className="truncate px-4 py-3 text-muted">{formatScore(report.quality_score)}</td>
                <td className="truncate px-4 py-3 text-muted">{formatDateTime(report.created_at)}</td>
                <td className="px-4 py-3">
                  <Link className="font-medium text-accent hover:underline" href={`/reports/${encodeURIComponent(reportId)}`}>
                    Open
                  </Link>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
