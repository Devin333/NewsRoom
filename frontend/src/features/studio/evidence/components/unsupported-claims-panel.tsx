import { Badge } from "@/components/common/badge"
import { EmptyState } from "@/components/common/empty-state"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatStatus } from "@/lib/i18n"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioClaimEvidence } from "@/types/evidence"

export function UnsupportedClaimsPanel({ claims }: { claims: StudioClaimEvidence[] }) {
  const { locale, t } = useI18n()
  const unsupportedClaims = claims.filter((claim) => claim.status === "unsupported" || claim.status === "rejected")

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("studio.evidence.unsupportedRejected")}</CardTitle>
      </CardHeader>
      <CardContent>
        {unsupportedClaims.length ? (
          <div className="space-y-3">
            {unsupportedClaims.map((claim) => (
              <article key={claim.claimId} className="rounded-md border border-border p-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-foreground">{claim.claimText}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{claim.reportSection ?? t("studio.evidence.noReportSection")}</p>
                  </div>
                  <Badge tone={claim.status === "rejected" ? "danger" : "info"}>{formatStatus(locale, claim.status)}</Badge>
                </div>
                {claim.failureReason ? <p className="mt-2 text-sm leading-6 text-muted-foreground">{claim.failureReason}</p> : null}
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title={t("studio.evidence.noUnsupported")} description={t("studio.evidence.noUnsupportedDescription")} />
        )}
      </CardContent>
    </Card>
  )
}
