"use client";

import { reports } from "@/lib/mock-data";
import type { MockHookResult } from "@/types/common";
import type { Report, ReportStatus, ReportType } from "@/types/report";

export type ReportFilters = {
  keyword?: string;
  reportType?: ReportType;
  status?: ReportStatus;
};

export function useReportList(filters: ReportFilters = {}): MockHookResult<Report[]> {
  const keyword = filters.keyword?.trim().toLowerCase();
  const data = reports
    .filter((report) => (!filters.reportType ? true : (report.reportType ?? report.type) === filters.reportType))
    .filter((report) => (!filters.status ? true : report.status === filters.status))
    .filter((report) => {
      if (!keyword) {
        return true;
      }
      return [report.title, report.agentName, report.reportType ?? report.type, report.status, report.markdown].filter(Boolean).join(" ").toLowerCase().includes(keyword);
    })
    .sort((a, b) => new Date(b.generatedAt).getTime() - new Date(a.generatedAt).getTime());

  return { data, isLoading: false, isError: false, refetch: () => undefined };
}
