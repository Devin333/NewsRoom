"use client";

import { EmptyState } from "@/components/common/empty-state";
import { StatusBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
import { formatDateTime, formatScore, titleCase } from "@/lib/format";
import type { QualityResult } from "@/types/quality";

export function QualityResultTable({ results, selectedResultId, onSelectResult }: { results: QualityResult[]; selectedResultId?: string; onSelectResult: (resultId: string) => void }) {
  if (!results.length) {
    return <EmptyState title="暂无质量结果" description="调整质量搜索、对象类型、状态、分数或复核筛选。" />;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[840px] table-fixed border-collapse text-left text-sm">
        <thead className="bg-secondary/70 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="w-72 px-4 py-3 font-medium">对象</th>
            <th className="w-24 px-4 py-3 font-medium">类型</th>
            <th className="w-24 px-4 py-3 font-medium">分数</th>
            <th className="w-36 px-4 py-3 font-medium">状态</th>
            <th className="w-24 px-4 py-3 font-medium">问题</th>
            <th className="w-36 px-4 py-3 font-medium">复核人</th>
            <th className="w-40 px-4 py-3 font-medium">创建时间</th>
          </tr>
        </thead>
        <tbody>
          {results.map((result) => (
            <tr key={result.id} className={`cursor-pointer border-t border-border hover:bg-secondary/50 ${selectedResultId === result.id ? "bg-secondary/60" : ""}`} onClick={() => onSelectResult(result.id)}>
              <td className="px-4 py-3">
                <p className="truncate font-medium text-foreground">{result.objectTitle}</p>
                <p className="truncate text-xs text-muted-foreground">{result.objectId}</p>
              </td>
              <td className="px-4 py-3"><Badge variant="muted">{titleCase(result.objectType)}</Badge></td>
              <td className="truncate px-4 py-3 text-muted-foreground">{formatScore(result.score)}</td>
              <td className="px-4 py-3"><StatusBadge status={result.status} /></td>
              <td className="truncate px-4 py-3 text-muted-foreground">{result.issueCount}</td>
              <td className="truncate px-4 py-3 text-muted-foreground">{result.reviewerDecision ? titleCase(result.reviewerDecision) : "无"}</td>
              <td className="truncate px-4 py-3 text-muted-foreground">{formatDateTime(result.createdAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
