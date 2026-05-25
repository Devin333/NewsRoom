import { Badge } from "@/components/common/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatStatus } from "@/lib/i18n"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioClaimEvidence } from "@/types/evidence"

const STATUS_TONE = {
  accepted: "success",
  rejected: "danger",
  uncertain: "warning",
  unsupported: "info"
} as const

export function QualityLineageGraph({ claims }: { claims: StudioClaimEvidence[] }) {
  const { locale, t } = useI18n()
  const featuredClaims = claims.slice(0, 5)

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("studio.evidence.lineage")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 text-xs font-semibold uppercase tracking-normal text-muted-foreground md:grid-cols-5">
          <span>{t("studio.sources.source")}</span>
          <span>{t("studio.evidence.evidence")}</span>
          <span>{t("studio.evidence.claim")}</span>
          <span>{t("studio.evidence.reportSection")}</span>
          <span>{t("studio.evidence.qualityDecision")}</span>
        </div>
        {featuredClaims.length ? (
          <div className="space-y-3">
            {featuredClaims.map((claim) => (
              <div key={claim.claimId} className="grid gap-2 rounded-md border border-border bg-card p-3 text-sm md:grid-cols-5">
                <LineageCell value={claim.sourceRefs[0]?.url ?? claim.sourceRefs[0]?.title ?? claim.sourceRefs[0]?.sourceId ?? t("studio.evidence.noSource")} />
                <LineageCell value={claim.evidenceRefs[0]?.evidenceId ?? claim.evidenceRefs[0]?.summary ?? claim.evidenceRefs[0]?.quote ?? t("studio.evidence.noEvidence")} />
                <LineageCell value={claim.claimText} strong />
                <LineageCell value={claim.reportSection ?? t("studio.evidence.noSection")} />
                <div className="min-w-0">
                  <Badge tone={STATUS_TONE[claim.status]}>{formatStatus(locale, claim.status)}</Badge>
                  {claim.failureReason ? <p className="mt-2 text-xs leading-5 text-muted-foreground">{claim.failureReason}</p> : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">{t("studio.evidence.noClaimLineage")}</p>
        )}
      </CardContent>
    </Card>
  )
}

function LineageCell({ value, strong = false }: { value: string; strong?: boolean }) {
  return <p className={`min-w-0 break-words leading-5 ${strong ? "font-medium text-foreground" : "text-muted-foreground"}`}>{value}</p>
}
