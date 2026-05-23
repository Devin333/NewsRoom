import { Card, CardContent } from "@/components/ui/card";
import { calculateSourceMetrics } from "@/features/sources/hooks/use-sources";
import { cn, formatDurationMs, formatNumber } from "@/lib/format";
import type { Source } from "@/types/source";

export function SourceMetrics({ sources }: { sources: Source[] }) {
  const metrics = calculateSourceMetrics(sources);
  return (
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      <Metric label="数据源" value={formatNumber(metrics.total)} detail={`${formatNumber(metrics.enabled)} 个启用`} />
      <Metric label="健康" value={formatNumber(metrics.healthy)} detail="可用数据源" tone="success" />
      <Metric label="失败" value={formatNumber(metrics.failed)} detail="需要复核" tone={metrics.failed ? "danger" : "success"} />
      <Metric label="24h 采集" value={formatNumber(metrics.collected)} detail="条目" />
      <Metric label="24h 错误" value={formatNumber(metrics.errors)} detail="来源错误" tone={metrics.errors ? "warning" : "success"} />
      <Metric label="平均延迟" value={formatDurationMs(metrics.avgLatency)} detail="每次来源运行" />
    </section>
  );
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "success" | "warning" | "danger" }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("mt-2 truncate text-2xl font-semibold", tone === "success" && "text-success", tone === "warning" && "text-warning", tone === "danger" && "text-danger")}>{value}</p>
        <p className="mt-1 truncate text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}
