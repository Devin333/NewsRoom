import { EmptyState } from "@/components/common/empty-state"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import { formatDateTime } from "@/lib/format"
import type { StudioLineageRef } from "@/types/artifact"

export function LineageViewer({ lineage }: { lineage: StudioLineageRef[] }) {
  return (
    <StudioPanel title="Lineage" description="Source to evidence to claim to report relationships." contentClassName="p-0">
      {!lineage.length ? (
        <div className="p-4">
          <EmptyState title="No lineage" description="This run did not return upstream or downstream relationships." />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Direction</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Run</TableHead>
                <TableHead>Relation</TableHead>
                <TableHead>Created</TableHead>
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
