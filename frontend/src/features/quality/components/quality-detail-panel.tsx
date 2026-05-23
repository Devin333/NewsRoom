import { EmptyState } from "@/components/common/empty-state";
import { StatusBadge } from "@/components/common/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { QualityCheckList } from "@/features/quality/components/quality-check-list";
import { formatDateTime, formatScore, titleCase } from "@/lib/format";
import type { QualityResult } from "@/types/quality";

export function QualityDetailPanel({ result }: { result?: QualityResult }) {
  if (!result) {
    return <EmptyState title="未选择质量结果" description="选择一个质量结果以检查具体检查项和复核状态。" />;
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{result.objectTitle}</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">{titleCase(result.objectType)} / {result.objectId}</p>
        </div>
        <StatusBadge status={result.status} />
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 text-sm sm:grid-cols-4">
          <Summary label="分数" value={formatScore(result.score)} />
          <Summary label="问题" value={String(result.issueCount)} />
          <Summary label="复核人" value={result.reviewerDecision ? titleCase(result.reviewerDecision) : "无"} />
          <Summary label="创建时间" value={formatDateTime(result.createdAt)} />
        </div>
        <div>
          <h3 className="mb-3 text-base font-semibold text-foreground">检查项</h3>
          <QualityCheckList checks={result.checks} />
        </div>
      </CardContent>
    </Card>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase text-muted-foreground">{label}</p>
      <p className="mt-1 truncate font-medium text-foreground">{value}</p>
    </div>
  );
}
