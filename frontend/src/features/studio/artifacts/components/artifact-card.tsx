import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatBytes, formatDateTime, titleCase } from "@/lib/format";
import { useI18n } from "@/lib/i18n/use-i18n";
import type { Artifact } from "@/types/artifact";

export function ArtifactCard({ artifact, selected, onSelect }: { artifact: Artifact; selected?: boolean; onSelect?: () => void }) {
  const { t } = useI18n();
  return (
    <Card className={selected ? "border-primary/50 bg-primary/10" : undefined}>
      <button type="button" className="block w-full text-left" onClick={onSelect}>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate font-medium text-foreground">{artifact.filename}</p>
              <p className="mt-1 truncate text-xs text-muted-foreground">{artifact.id}</p>
            </div>
            <Badge variant="info">{titleCase(artifact.artifactType)}</Badge>
          </div>
          <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
            <span>{artifact.runId ?? t("studio.artifacts.noRun")}</span>
            <span>{formatBytes(artifact.sizeBytes)}</span>
            <span>{artifact.stepId ?? t("studio.artifacts.noStep")}</span>
            <span>{formatDateTime(artifact.createdAt)}</span>
          </div>
        </CardContent>
      </button>
    </Card>
  );
}
