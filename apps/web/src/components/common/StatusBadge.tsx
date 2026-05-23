const statusClasses: Record<string, string> = {
  ok: "border-good/30 bg-good/10 text-good",
  healthy: "border-good/30 bg-good/10 text-good",
  succeeded: "border-good/30 bg-good/10 text-good",
  ready: "border-good/30 bg-good/10 text-good",
  running: "border-accent/30 bg-accent/10 text-accent",
  queued: "border-accent/30 bg-accent/10 text-accent",
  accepted: "border-accent/30 bg-accent/10 text-accent",
  blocked: "border-warn/30 bg-warn/10 text-warn",
  failed: "border-bad/30 bg-bad/10 text-bad",
  unavailable: "border-bad/30 bg-bad/10 text-bad"
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase()
  const className = statusClasses[normalized] ?? "border-line bg-surface text-muted"

  return (
    <span className={`inline-flex min-h-6 items-center rounded-md border px-2 py-1 text-xs font-medium ${className}`}>
      {status}
    </span>
  )
}
