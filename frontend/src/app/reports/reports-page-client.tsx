"use client"

import { useState } from "react"
import { PageHeader } from "@/components/layout/page-header"
import { ReportList } from "@/features/reports/components/report-list"
import { ReportToolbar } from "@/features/reports/components/report-toolbar"
import { useReportList, type ReportFilters } from "@/features/reports/hooks/use-report-list"
import { useI18n } from "@/lib/i18n/use-i18n"

export function ReportsPageClient() {
  const { t } = useI18n()
  const [filters, setFilters] = useState<ReportFilters>({})
  const reports = useReportList(filters)

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={t("portal.reports.eyebrow")} title={t("portal.reports.title")} description={t("portal.reports.description")} />
      <ReportToolbar filters={filters} onChange={setFilters} />
      <ReportList reports={reports.data} />
    </div>
  )
}
