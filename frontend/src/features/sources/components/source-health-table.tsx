"use client";

import { EmptyState } from "@/components/common/empty-state";
import { SourceHealthBadge } from "@/components/common/source-health-badge";
import { formatDateTime, formatDurationMs, formatNumber, titleCase } from "@/lib/format";
import type { Source } from "@/types/source";

export function SourceHealthTable({ sources, selectedSourceId, onSelectSource }: { sources: Source[]; selectedSourceId?: string; onSelectSource: (sourceId: string) => void }) {
  if (!sources.length) {
    return <EmptyState title="没有匹配的数据源" description="调整数据源搜索、类型、健康或启用状态筛选。" />;
  }

  if (sources.every((source) => !source.enabled)) {
    return <EmptyState title="所有数据源均已停用" description="当前数据源集合已暂停；启用数据源前，运行时采集不会产生新证据。" />;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[1120px] table-fixed border-collapse text-left text-sm">
        <thead className="bg-secondary/70 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="w-56 px-4 py-3 font-medium">数据源</th>
            <th className="w-36 px-4 py-3 font-medium">类型</th>
            <th className="w-28 px-4 py-3 font-medium">启用</th>
            <th className="w-32 px-4 py-3 font-medium">健康</th>
            <th className="w-44 px-4 py-3 font-medium">最近运行</th>
            <th className="w-44 px-4 py-3 font-medium">最近成功</th>
            <th className="w-28 px-4 py-3 font-medium">24h 错误</th>
            <th className="w-32 px-4 py-3 font-medium">24h 采集</th>
            <th className="w-32 px-4 py-3 font-medium">平均延迟</th>
            <th className="w-44 px-4 py-3 font-medium">配置</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => (
            <tr
              key={source.id}
              className={`cursor-pointer border-t border-border hover:bg-secondary/50 ${selectedSourceId === source.id ? "bg-secondary/60" : ""}`}
              onClick={() => onSelectSource(source.id)}
            >
              <td className="px-4 py-3">
                <p className="truncate font-medium text-foreground">{source.name}</p>
                <p className="truncate text-xs text-muted-foreground">{source.id}</p>
              </td>
              <td className="truncate px-4 py-3 text-muted-foreground">{titleCase(source.type)}</td>
              <td className="truncate px-4 py-3 text-muted-foreground">{source.enabled ? "已启用" : "已停用"}</td>
              <td className="px-4 py-3"><SourceHealthBadge status={source.healthStatus} /></td>
              <td className="truncate px-4 py-3 text-muted-foreground">{formatDateTime(source.lastRunAt)}</td>
              <td className="truncate px-4 py-3 text-muted-foreground">{formatDateTime(source.lastSuccessAt)}</td>
              <td className="truncate px-4 py-3 text-muted-foreground">{formatNumber(source.errorCount24h)}</td>
              <td className="truncate px-4 py-3 text-muted-foreground">{formatNumber(source.collectedCount24h)}</td>
              <td className="truncate px-4 py-3 text-muted-foreground">{formatDurationMs(source.avgLatencyMs)}</td>
              <td className="truncate px-4 py-3 text-muted-foreground">{source.configProfile ?? "无"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
