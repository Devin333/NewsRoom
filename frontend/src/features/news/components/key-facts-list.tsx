import { CheckCircle2 } from "lucide-react"
import { Badge } from "@/components/common/badge"
import type { KeyFact } from "@/types/news"

export function KeyFactsList({ facts }: { facts?: KeyFact[] }) {
  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <h2 className="text-lg font-semibold text-foreground">关键事实</h2>
      {facts?.length ? (
        <ul className="mt-4 space-y-3">
          {facts.map((fact) => (
            <li key={fact.id} className="flex gap-3 rounded-md border border-border bg-background/40 p-3">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
              <div className="min-w-0">
                <p className="text-sm leading-6 text-foreground">{fact.text}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {fact.sourceName ? <Badge tone="neutral">{fact.sourceName}</Badge> : null}
                  {fact.confidence ? <Badge tone={fact.confidence === "high" ? "success" : fact.confidence === "medium" ? "warning" : "danger"}>{confidenceLabel(fact.confidence)}可信</Badge> : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">尚未提取关键事实。</p>
      )}
    </section>
  )
}

function confidenceLabel(confidence: string) {
  return confidence === "high" ? "高" : confidence === "medium" ? "中" : "低"
}
