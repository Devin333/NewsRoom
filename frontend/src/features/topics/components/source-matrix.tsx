import { CredibilityBadge, SourceBadge } from "@/components/common/badges";
import { formatDate } from "@/lib/format";
import type { TopicSourceCoverage } from "@/types/topic";

export function SourceMatrix({ sources }: { sources: TopicSourceCoverage[] }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-base font-semibold text-foreground">来源矩阵</h2>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] table-fixed border-collapse text-left text-sm">
          <thead className="text-xs uppercase text-muted-foreground">
            <tr>
              <th className="w-52 py-2 font-medium">来源</th>
              <th className="w-28 py-2 font-medium">条目</th>
              <th className="w-40 py-2 font-medium">首次出现</th>
              <th className="w-40 py-2 font-medium">更新于</th>
              <th className="w-44 py-2 font-medium">可信度</th>
              <th className="py-2 font-medium">覆盖说明</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.sourceName} className="border-t border-border">
                <td className="py-3 pr-3"><SourceBadge sourceName={source.sourceName} sourceType={source.sourceType} /></td>
                <td className="py-3 pr-3 text-muted-foreground">{source.itemCount}</td>
                <td className="py-3 pr-3 text-muted-foreground">{formatDate(source.firstSeenAt)}</td>
                <td className="py-3 pr-3 text-muted-foreground">{formatDate(source.lastSeenAt)}</td>
                <td className="py-3 pr-3"><CredibilityBadge credibility={source.credibility} /></td>
                <td className="py-3 text-muted-foreground">{source.coverageSummary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
