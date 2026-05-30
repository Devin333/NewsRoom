import { StatusBadge } from "@/components/common/StatusBadge"
import { formatDateTime } from "@/lib/format"
import type { SourceHealthItem } from "@/lib/types"

export function SourceHealthTable({ sources }: { sources: SourceHealthItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Source</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Status</th>
            <th className="pb-3 pr-4 text-left text-xs font-medium text-muted">Last success</th>
            <th className="pb-3 pr-4 text-right text-xs font-medium text-muted">Failures</th>
            <th className="pb-3 text-left text-xs font-medium text-muted">Cooldown until</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {sources.map((s) => (
            <tr key={s.source_id} className="group">
              <td className="py-3 pr-4">
                <p className="font-medium text-ink">{s.source_name ?? s.source_id}</p>
                <p className="font-mono text-xs text-subtle">{s.source_id}</p>
              </td>
              <td className="py-3 pr-4"><StatusBadge status={s.status} /></td>
              <td className="py-3 pr-4 text-muted">{s.last_success_at ? formatDateTime(s.last_success_at) : "—"}</td>
              <td className="py-3 pr-4 text-right">
                {s.consecutive_failures ? (
                  <span className="font-medium text-bad">{s.consecutive_failures}</span>
                ) : (
                  <span className="text-muted">0</span>
                )}
              </td>
              <td className="py-3 text-muted">{s.cooldown_until ? formatDateTime(s.cooldown_until) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
