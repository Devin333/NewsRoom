import Link from "next/link"
import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime, formatScore } from "@/lib/format"
import type { ReportListItem } from "@/lib/types"

export function ReportList({ reports }: { reports: ReportListItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Title</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Status</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Quality</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Sources</th>
            <th className="pb-3 text-left text-xs font-medium text-muted">Created</th>
            <th className="pb-3 text-right text-xs font-medium text-muted"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {reports.map((r) => (
            <tr key={r.report_id ?? r.run_id} className="group">
              <td className="py-3 pr-4">
                <p className="font-medium text-ink">{r.title ?? r.report_id ?? "Untitled"}</p>
                {r.summary && <p className="mt-0.5 line-clamp-1 text-xs text-muted">{r.summary}</p>}
              </td>
              <td className="py-3 pr-4"><StatusBadge status={r.status ?? "unknown"} /></td>
              <td className="py-3 pr-4 text-muted">{r.quality_score != null ? formatScore(r.quality_score) : "—"}</td>
              <td className="py-3 pr-4 text-muted">{r.source_count ?? "—"}</td>
              <td className="py-3 text-muted">{r.created_at ? formatDateTime(r.created_at) : "—"}</td>
              <td className="py-3 pl-4 text-right">
                {r.report_id && (
                  <Link href={`/reports/${r.report_id}`} className="text-xs text-accent opacity-0 transition-opacity group-hover:opacity-100 hover:underline">
                    View →
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
