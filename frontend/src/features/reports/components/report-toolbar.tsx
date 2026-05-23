"use client";

import type { ReportFilters } from "@/features/reports/hooks/use-report-list";
import type { ReportStatus, ReportType } from "@/types/report";

const types: ReportType[] = ["daily", "weekly", "topic", "tech", "quality", "source_health"];
const statuses: ReportStatus[] = ["draft", "generated", "reviewed", "published", "failed"];
const typeLabels: Record<ReportType, string> = {
  daily: "日报",
  weekly: "周报",
  topic: "主题",
  tech: "技术",
  quality: "质量",
  source_health: "数据源健康",
};
const statusLabels: Record<ReportStatus, string> = {
  draft: "草稿",
  generated: "已生成",
  reviewed: "已复核",
  published: "已发布",
  failed: "失败",
};

export function ReportToolbar({ filters, onChange }: { filters: ReportFilters; onChange: (filters: ReportFilters) => void }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="grid gap-3 md:grid-cols-[1fr_0.55fr_0.55fr]">
        <input
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          placeholder="搜索报告..."
          value={filters.keyword ?? ""}
          onChange={(event) => onChange({ ...filters, keyword: event.target.value })}
        />
        <select className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={filters.reportType ?? ""} onChange={(event) => onChange({ ...filters, reportType: (event.target.value || undefined) as ReportType | undefined })}>
          <option value="">全部报告类型</option>
          {types.map((type) => <option key={type} value={type}>{typeLabels[type]}</option>)}
        </select>
        <select className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={filters.status ?? ""} onChange={(event) => onChange({ ...filters, status: (event.target.value || undefined) as ReportStatus | undefined })}>
          <option value="">全部状态</option>
          {statuses.map((status) => <option key={status} value={status}>{statusLabels[status]}</option>)}
        </select>
      </div>
    </div>
  );
}
