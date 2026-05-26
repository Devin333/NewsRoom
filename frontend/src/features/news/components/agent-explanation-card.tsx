import { Bot } from "lucide-react"

export function AgentExplanationCard({ items }: { items?: string[] }) {
  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-center gap-2">
        <Bot className="h-4 w-4 text-accent" />
        <h2 className="text-lg font-semibold text-foreground">智能体解释</h2>
      </div>
      {items?.length ? (
        <ul className="mt-4 list-disc space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">暂无公开智能体解释。</p>
      )}
    </section>
  )
}
