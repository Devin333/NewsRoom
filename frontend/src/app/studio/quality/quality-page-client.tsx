"use client";

import { PageHeader } from "@/components/layout/page-header";
import { QualityDetailPanel } from "@/features/quality/components/quality-detail-panel";
import { QualityMetrics } from "@/features/quality/components/quality-metrics";
import { QualityResultTable } from "@/features/quality/components/quality-result-table";
import { QualityToolbar } from "@/features/quality/components/quality-toolbar";
import { useQualityResults } from "@/features/quality/hooks/use-quality-results";

export function QualityPageClient() {
  const { results, filters, setFilters, selectedResult, setSelectedResultId } = useQualityResults();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="治理"
        title="质量"
        description="复核 NewsRoom 对象的质量门控结果、分数分布、失败检查和人工复核需求。"
      />
      <QualityMetrics results={results} />
      <QualityToolbar filters={filters} onChange={setFilters} />
      <QualityResultTable results={results} selectedResultId={selectedResult?.id} onSelectResult={setSelectedResultId} />
      <QualityDetailPanel result={selectedResult} />
    </div>
  );
}
