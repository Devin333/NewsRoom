import { EmptyState } from "@/components/common/empty-state"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import { formatDateTime } from "@/lib/format"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioLineageRef } from "@/types/artifact"

export function LineageViewer({ lineage }: { lineage: StudioLineageRef[] }) {
  const { t } = useI18n()
  return (
    <StudioPanel title={t("studio.artifacts.lineage")} description={t("studio.artifacts.lineageDescription")} contentClassName="p-0">
      {!lineage.length ? (
        <div className="p-4">
          <EmptyState title={t("studio.artifacts.noLineage")} description={t("studio.artifacts.noLineageDescription")} />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("studio.artifacts.direction")}</TableHead>
                <TableHead>{t("studio.sources.source")}</TableHead>
                <TableHead>{t("studio.artifacts.target")}</TableHead>
                <TableHead>{t("studio.runs.runId")}</TableHead>
                <TableHead>{t("studio.artifacts.relation")}</TableHead>
                <TableHead>{t("studio.artifacts.created")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lineage.map((item) => (
                <TableRow key={item.lineageId ?? `${item.sourceType}:${item.sourceId}:${item.targetId}`}>
                  <TableCell>
                    <Badge variant="info">{item.direction}</Badge>
                  </TableCell>
                  <TableCell className="max-w-[18rem]">
                    <p className="truncate font-medium">{item.sourceType}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.sourceId}</p>
                  </TableCell>
                  <TableCell className="max-w-[18rem]">
                    <p className="truncate font-medium">{item.targetType}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.targetId}</p>
                  </TableCell>
                  <TableCell className="max-w-[14rem] truncate">{item.runId}</TableCell>
                  <TableCell>{item.relationType ?? "derived_from"}</TableCell>
                  <TableCell>{formatDateTime(item.createdAt)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </StudioPanel>
  )
}
