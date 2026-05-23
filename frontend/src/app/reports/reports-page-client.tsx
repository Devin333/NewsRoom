"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { ReportList } from "@/features/reports/components/report-list";
import { ReportToolbar } from "@/features/reports/components/report-toolbar";
import { useReportList, type ReportFilters } from "@/features/reports/hooks/use-report-list";

export function ReportsPageClient() {
  const [filters, setFilters] = useState<ReportFilters>({});
  const reports = useReportList(filters);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="报告" title="生成报告" description="由 NewsRoom 智能体生成的日报、周报、主题、技术、质量和数据源健康报告。" />
      <ReportToolbar filters={filters} onChange={setFilters} />
      <ReportList reports={reports.data} />
    </div>
  );
}
