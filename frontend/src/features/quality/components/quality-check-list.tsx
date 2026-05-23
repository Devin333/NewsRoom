import { StatusBadge } from "@/components/common/status-badge";
import { formatScore, titleCase } from "@/lib/format";
import type { QualityCheck } from "@/types/quality";

export function QualityCheckList({ checks }: { checks: QualityCheck[] }) {
  return (
    <div className="space-y-2">
      {checks.map((check) => (
        <div key={check.id} className="rounded-md border border-border bg-secondary/40 p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium text-foreground">{titleCase(check.name)}</p>
            <StatusBadge status={check.status} />
          </div>
          <p className="mt-1 text-muted-foreground">分数 {formatScore(check.score)}</p>
          {check.message ? <p className="mt-1 leading-6 text-muted-foreground">{check.message}</p> : null}
        </div>
      ))}
    </div>
  );
}
