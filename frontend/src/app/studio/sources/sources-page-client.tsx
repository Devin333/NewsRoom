"use client";

import { PageHeader } from "@/components/layout/page-header";
import { SourceDetailPanel } from "@/features/sources/components/source-detail-panel";
import { SourceHealthTable } from "@/features/sources/components/source-health-table";
import { SourceMetrics } from "@/features/sources/components/source-metrics";
import { SourceToolbar } from "@/features/sources/components/source-toolbar";
import { useSources } from "@/features/sources/hooks/use-sources";

export function SourcesPageClient() {
  const { allSources, sources, filters, setFilters, selectedSource, setSelectedSourceId } = useSources();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="数据源运营"
        title="数据源"
        description="查看 NewsRoom 数据源层的运行健康、采集新鲜度、失败信号和连接器覆盖情况。"
      />
      <SourceMetrics sources={allSources} />
      <SourceToolbar filters={filters} onChange={setFilters} />
      <SourceHealthTable sources={sources} selectedSourceId={selectedSource?.id} onSelectSource={setSelectedSourceId} />
      <SourceDetailPanel source={selectedSource} />
    </div>
  );
}
