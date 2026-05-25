import { EmptyState } from "@/components/common/empty-state"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioLlmTrace } from "@/types/evidence"

export function LlmTracePanel({ trace }: { trace?: StudioLlmTrace }) {
  const { t } = useI18n()
  if (!trace) {
    return <EmptyState title={t("studio.evidence.noLlmTrace")} description={t("studio.evidence.noLlmTraceDescription")} />
  }

  const metrics = [
    [t("studio.evidence.deployment"), trace.selectedDeploymentId ?? t("common.unknown")],
    [t("studio.evidence.fallback"), trace.fallbackUsed ? t("common.yes") : t("common.no")],
    [t("studio.evidence.fallbackCount"), trace.fallbackCount ?? 0],
    [t("studio.evidence.providerErrors"), trace.providerErrorCount ?? 0],
    [t("studio.evidence.cooldownSkips"), trace.cooldownSkipCount ?? 0],
    [t("studio.evidence.routerEvents"), trace.routerEventCount ?? 0]
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("studio.evidence.llmTrace")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {metrics.map(([label, value]) => (
            <div key={label} className="rounded-md border border-border bg-secondary/30 p-3">
              <p className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">{label}</p>
              <p className="mt-1 text-sm font-medium text-foreground">{String(value)}</p>
            </div>
          ))}
        </div>
        <pre className="max-h-80 overflow-auto rounded-md border border-border bg-secondary/40 p-3 text-xs leading-5 text-foreground">
          {JSON.stringify(trace.sanitized, null, 2)}
        </pre>
      </CardContent>
    </Card>
  )
}
