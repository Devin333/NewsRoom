"use client";

import { PageHeader } from "@/components/layout/page-header";
import { ArtifactList } from "@/features/studio/artifacts/components/artifact-list";
import { ArtifactPreviewPanel } from "@/features/studio/artifacts/components/artifact-preview-panel";
import { ArtifactToolbar } from "@/features/studio/artifacts/components/artifact-toolbar";
import { useArtifacts } from "@/features/studio/artifacts/hooks/use-artifacts";

export function ArtifactsPageClient() {
  const { artifacts, filters, setFilters, selectedArtifact, setSelectedArtifactId } = useArtifacts();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="运行证据"
        title="产物"
        description="浏览生成的 JSON、Markdown、HTML、日志、报告、数据集，以及与运行关联的检查材料。"
      />
      <ArtifactToolbar filters={filters} onChange={setFilters} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <ArtifactList artifacts={artifacts} selectedArtifactId={selectedArtifact?.id} onSelectArtifact={setSelectedArtifactId} />
        <ArtifactPreviewPanel artifact={selectedArtifact} />
      </div>
    </div>
  );
}
