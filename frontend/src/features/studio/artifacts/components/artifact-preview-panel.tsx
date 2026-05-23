import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatBytes, formatDateTime, titleCase } from "@/lib/format";
import type { Artifact } from "@/types/artifact";

export function ArtifactPreviewPanel({ artifact }: { artifact?: Artifact }) {
  if (!artifact) {
    return <EmptyState title="未选择产物" description="选择一个产物以查看预览和元数据。" />;
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{artifact.filename}</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">{artifact.id}</p>
        </div>
        <Badge variant="info">{titleCase(artifact.artifactType)}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <Summary label="运行" value={artifact.runId ?? "无"} />
          <Summary label="步骤" value={artifact.stepId ?? "无"} />
          <Summary label="大小" value={formatBytes(artifact.sizeBytes)} />
          <Summary label="创建时间" value={formatDateTime(artifact.createdAt)} />
        </div>
        {artifact.preview ? (
          <pre className="max-h-96 overflow-auto rounded-md border border-border bg-background p-4 text-xs leading-6 text-muted-foreground">{artifact.preview}</pre>
        ) : (
          <div className="rounded-md border border-dashed border-border bg-secondary/40 p-4 text-sm text-muted-foreground">
            这个产物暂无预览，但仍可查看元数据用于运行检查。
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase text-muted-foreground">{label}</p>
      <p className="mt-1 truncate font-medium text-foreground">{value}</p>
    </div>
  );
}
