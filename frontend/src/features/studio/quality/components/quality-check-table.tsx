import { CircleAlert } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import type { StudioQualityCheck, StudioQualityStatus } from "@/types/quality"

const statusVariant: Record<StudioQualityStatus, React.ComponentProps<typeof Badge>["variant"]> = {
  passed: "success",
  warning: "warning",
  failed: "danger",
  review_required: "info",
  unknown: "muted"
}

export function QualityCheckTable({ checks }: { checks: StudioQualityCheck[] }) {
  return (
    <StudioPanel title="Quality checks" contentClassName="p-0">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-52">Check</TableHead>
              <TableHead className="w-40">Status</TableHead>
              <TableHead className="w-28">Score</TableHead>
              <TableHead className="min-w-80">Message</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {checks.map((check) => (
              <TableRow key={check.id}>
                <TableCell>
                  <div className="flex min-w-0 items-center gap-2">
                    {check.userActionRequired ? <CircleAlert className="size-4 shrink-0 text-warning" /> : null}
                    <span className="truncate font-medium text-foreground">{check.name}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant[check.status]}>{statusLabel(check.status)}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{check.score === undefined ? "n/a" : check.score}</TableCell>
                <TableCell className="max-w-[34rem] text-muted-foreground">
                  <span className="line-clamp-2">{check.message ?? "No message."}</span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </StudioPanel>
  )
}

export function QualityStatusBadge({ status }: { status: StudioQualityStatus }) {
  return <Badge variant={statusVariant[status]}>{statusLabel(status)}</Badge>
}

function statusLabel(status: StudioQualityStatus): string {
  if (status === "review_required") return "Review required"
  return status.charAt(0).toUpperCase() + status.slice(1)
}
