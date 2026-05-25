import { CircleAlert } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import { formatStatus } from "@/lib/i18n"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioQualityCheck, StudioQualityStatus } from "@/types/quality"

const statusVariant: Record<StudioQualityStatus, React.ComponentProps<typeof Badge>["variant"]> = {
  passed: "success",
  warning: "warning",
  failed: "danger",
  review_required: "info",
  unknown: "muted"
}

export function QualityCheckTable({ checks }: { checks: StudioQualityCheck[] }) {
  const { locale, t } = useI18n()
  return (
    <StudioPanel title={t("studio.quality.qualityChecks")} contentClassName="p-0">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-52">{t("studio.quality.check")}</TableHead>
              <TableHead className="w-40">{t("common.status")}</TableHead>
              <TableHead className="w-28">{t("studio.quality.score")}</TableHead>
              <TableHead className="min-w-80">{t("studio.quality.message")}</TableHead>
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
                  <Badge variant={statusVariant[check.status]}>{formatQualityStatus(locale, check.status)}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{check.score === undefined ? "n/a" : check.score}</TableCell>
                <TableCell className="max-w-[34rem] text-muted-foreground">
                  <span className="line-clamp-2">{check.message ?? t("studio.quality.noMessage")}</span>
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
  const { locale } = useI18n()
  return <Badge variant={statusVariant[status]}>{formatQualityStatus(locale, status)}</Badge>
}

function formatQualityStatus(locale: "zh" | "en", status: StudioQualityStatus): string {
  return formatStatus(locale, status)
}
