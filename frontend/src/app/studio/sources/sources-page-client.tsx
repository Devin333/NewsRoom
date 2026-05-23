"use client";

import { PageHeader } from "@/components/layout/page-header";
import { SourceDetailPanel } from "@/features/sources/components/source-detail-panel";
import { SourceHealthTable } from "@/features/sources/components/source-health-table";
import { SourceMetrics } from "@/features/sources/components/source-metrics";
import { SourceToolbar } from "@/features/sources/components/source-toolbar";
import { useSources } from "@/features/sources/hooks/use-sources";

export function SourcesPageClient() {
  const {
    allSources,
    sources,
    filters,
    setFilters,
    selectedSource,
    setSelectedSourceId,
    isLoading,
    isFetchingPreview,
    error,
    isUsingMockFallback,
  } = useSources();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="数据源运营"
        title="数据源"
        description="查看 NewsRoom 数据源层的运行健康、采集新鲜度、失败信号和连接器覆盖情况。"
      />
      {isLoading ? <StatusNotice tone="info" message="正在从 NewsRoom API 加载真实 source registry..." /> : null}
      {error ? (
        <StatusNotice
          tone="warning"
          message={`真实 API 暂不可用，当前显示 fallback 数据：${error instanceof Error ? error.message : "request failed"}`}
        />
      ) : null}
      {!error && !isUsingMockFallback ? (
        <StatusNotice
          tone="success"
          message={`已连接真实 source registry，共 ${allSources.length} 个 source。${isFetchingPreview ? "正在抓取选中源预览..." : ""}`}
        />
      ) : null}
      <SourceMetrics sources={allSources} />
      <SourceToolbar filters={filters} onChange={setFilters} />
      <SourceHealthTable sources={sources} selectedSourceId={selectedSource?.id} onSelectSource={setSelectedSourceId} />
      <SourceDetailPanel source={selectedSource} />
    </div>
  );
}

function StatusNotice({ tone, message }: { tone: "info" | "success" | "warning"; message: string }) {
  const toneClass =
    tone === "success"
      ? "border-success/30 bg-success/10 text-success"
      : tone === "warning"
        ? "border-warning/30 bg-warning/10 text-warning"
        : "border-border bg-card text-muted-foreground";
  return <div className={`rounded-md border px-4 py-3 text-sm ${toneClass}`}>{message}</div>;
}
