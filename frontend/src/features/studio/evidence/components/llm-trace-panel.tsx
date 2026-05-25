import { EmptyState } from "@/components/common/empty-state"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { StudioLlmTrace } from "@/types/evidence"

export function LlmTracePanel({ trace }: { trace?: StudioLlmTrace }) {
  if (!trace) {
    return <EmptyState title="No LLM trace" description="This run did not expose a sanitized LLM route preview." />
  }

  const metrics = [
    ["Deployment", trace.selectedDeploymentId ?? "unknown"],
    ["Fallback", trace.fallbackUsed ? "yes" : "no"],
    ["Fallback count", trace.fallbackCount ?? 0],
    ["Provider errors", trace.providerErrorCount ?? 0],
    ["Cooldown skips", trace.cooldownSkipCount ?? 0],
    ["Router events", trace.routerEventCount ?? 0]
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle>LLM Trace</CardTitle>
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
