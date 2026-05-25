import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatBytes, formatDateTime, titleCase } from "@/lib/format";
import { useI18n } from "@/lib/i18n/use-i18n";
import type { Artifact } from "@/types/artifact";

export function ArtifactPreviewPanel({ artifact }: { artifact?: Artifact }) {
  const { t } = useI18n();
  if (!artifact) {
    return <EmptyState title={t("studio.artifacts.notSelected")} description={t("studio.artifacts.notSelectedDescription")} />;
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
          <Summary label={t("studio.artifacts.run")} value={artifact.runId ?? t("common.none")} />
          <Summary label={t("studio.artifacts.step")} value={artifact.stepId ?? t("common.none")} />
          <Summary label={t("studio.artifacts.size")} value={formatBytes(artifact.sizeBytes)} />
          <Summary label={t("studio.artifacts.createdAt")} value={formatDateTime(artifact.createdAt)} />
        </div>
        {artifact.preview ? (
          <pre className="max-h-96 overflow-auto rounded-md border border-border bg-background p-4 text-xs leading-6 text-muted-foreground">{artifact.preview}</pre>
        ) : (
          <div className="rounded-md border border-dashed border-border bg-secondary/40 p-4 text-sm text-muted-foreground">
            {t("studio.artifacts.noPreview")}
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
