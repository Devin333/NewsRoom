import { EmptyState } from "@/components/common/empty-state";
import { SourceHealthBadge } from "@/components/common/source-health-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime, formatDurationMs, formatNumber, titleCase } from "@/lib/format";
import type { Source } from "@/types/source";

export function SourceDetailPanel({ source }: { source?: Source }) {
  if (!source) {
    return <EmptyState title="未选择数据源" description="选择一行数据源以查看最近运行和错误。" />;
  }

  return (
    <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div>
            <CardTitle>{source.name}</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">{source.id}</p>
          </div>
          <SourceHealthBadge status={source.healthStatus} />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <Summary label="类型" value={titleCase(source.type)} />
            <Summary label="启用" value={source.enabled ? "是" : "否"} />
            <Summary label="最近运行" value={formatDateTime(source.lastRunAt)} />
            <Summary label="最近成功" value={formatDateTime(source.lastSuccessAt)} />
            <Summary label="24h 采集" value={formatNumber(source.collectedCount24h)} />
            <Summary label="平均延迟" value={formatDurationMs(source.avgLatencyMs)} />
          </div>
          <div className="rounded-md border border-border bg-secondary/50 p-3 text-sm leading-6 text-muted-foreground">
            {source.configSummary ?? "暂无配置摘要。"}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle>最近运行历史</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {(source.recentRuns ?? []).map((run) => (
              <div key={run.id} className="rounded-md border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-foreground">{run.id}</span>
                  <SourceHealthBadge status={run.status} />
                </div>
                <p className="mt-1 text-muted-foreground">{formatDateTime(run.startedAt)} - {formatNumber(run.collectedCount)} 条目 - {formatDurationMs(run.latencyMs)}</p>
                {run.errorMessage ? <p className="mt-1 text-danger">{run.errorMessage}</p> : null}
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>错误与最新条目</CardTitle></CardHeader>
          <CardContent>
            {source.errorSummary?.length ? (
              <ul className="mb-4 space-y-1 text-sm text-danger">
                {source.errorSummary.map((error) => <li key={error}>{error}</li>)}
              </ul>
            ) : (
              <p className="mb-4 text-sm text-muted-foreground">暂无最近错误摘要。</p>
            )}
            <div className="space-y-2">
              {(source.latestItems ?? []).map((item) => (
                <div key={item.id} className="rounded-md border border-border p-3 text-sm">
                  <p className="font-medium text-foreground">{item.title}</p>
                  <p className="mt-1 text-muted-foreground">{formatDateTime(item.capturedAt)}</p>
                </div>
              ))}
              {!source.latestItems?.length ? <p className="text-sm text-muted-foreground">暂无最新条目预览。</p> : null}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
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
