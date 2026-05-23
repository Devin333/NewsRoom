"use client";

import type { SourceFilters, SourceHealthStatus } from "@/types/source";
import type { SourceType } from "@/types/common";

const sourceTypes: SourceType[] = ["official_blog", "rss", "github", "hackernews", "reddit", "arxiv", "media", "custom"];
const healthStatuses: SourceHealthStatus[] = ["healthy", "degraded", "failed", "disabled"];
const sourceLabels: Record<SourceType, string> = {
  official_blog: "官方博客",
  rss: "RSS",
  github: "GitHub",
  hackernews: "Hacker News",
  reddit: "Reddit",
  arxiv: "arXiv",
  media: "媒体",
  custom: "自定义",
};
const healthLabels: Record<SourceHealthStatus, string> = {
  healthy: "健康",
  degraded: "降级",
  failed: "失败",
  disabled: "已停用",
};

export function SourceToolbar({ filters, onChange }: { filters: SourceFilters; onChange: (filters: SourceFilters) => void }) {
  return (
    <section className="grid gap-3 rounded-lg border border-border bg-card p-4 lg:grid-cols-[1fr_12rem_12rem_12rem]">
      <input
        className="h-10 rounded-md border border-input bg-background px-3 text-sm text-foreground"
        placeholder="搜索数据源"
        value={filters.keyword}
        onChange={(event) => onChange({ ...filters, keyword: event.target.value })}
      />
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={filters.type} onChange={(event) => onChange({ ...filters, type: event.target.value as SourceFilters["type"] })}>
        <option value="all">全部类型</option>
        {sourceTypes.map((type) => (
          <option key={type} value={type}>{sourceLabels[type]}</option>
        ))}
      </select>
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={filters.healthStatus} onChange={(event) => onChange({ ...filters, healthStatus: event.target.value as SourceFilters["healthStatus"] })}>
        <option value="all">全部健康状态</option>
        {healthStatuses.map((status) => (
          <option key={status} value={status}>{healthLabels[status]}</option>
        ))}
      </select>
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={filters.enabled} onChange={(event) => onChange({ ...filters, enabled: event.target.value as SourceFilters["enabled"] })}>
        <option value="all">全部状态</option>
        <option value="enabled">已启用</option>
        <option value="disabled">已停用</option>
      </select>
    </section>
  );
}
