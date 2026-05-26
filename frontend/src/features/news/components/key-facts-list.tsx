import { CheckCircle2 } from "lucide-react"
import { Badge } from "@/components/common/badge"
import type { KeyFact } from "@/types/news"

export function KeyFactsList({ facts }: { facts?: KeyFact[] }) {
  return (
    <section className="rounded-md border border-[#dbe3dc] bg-white/85 p-5 dark:border-border dark:bg-card">
      <h2 className="text-lg font-semibold text-[#334155] dark:text-foreground">Key facts</h2>
      {facts?.length ? (
        <ul className="mt-4 space-y-3">
          {facts.map((fact) => (
            <li key={fact.id} className="flex gap-3 rounded-md border border-[#edf1ed] bg-[#f7f9f6] p-3 dark:border-border dark:bg-background/60">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
              <div className="min-w-0">
                <p className="text-sm leading-6 text-[#334155] dark:text-foreground">{fact.text}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {fact.sourceName ? <Badge tone="neutral">{fact.sourceName}</Badge> : null}
                  {fact.confidence ? (
                    <Badge tone={fact.confidence === "high" ? "success" : fact.confidence === "medium" ? "warning" : "danger"}>
                      {fact.confidence} confidence
                    </Badge>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-[#334155]/60 dark:text-muted-foreground">No key facts have been extracted yet.</p>
      )}
    </section>
  )
}
