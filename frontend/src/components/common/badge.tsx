import { cn } from "@/lib/utils"

const toneClass = {
  neutral: "border-border bg-secondary text-secondary-foreground",
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  danger: "border-danger/30 bg-danger/10 text-danger",
  info: "border-info/30 bg-info/10 text-info",
  accent: "border-accent/30 bg-accent/10 text-accent"
}

export function Badge({
  children,
  tone = "neutral",
  className
}: {
  children: React.ReactNode
  tone?: keyof typeof toneClass
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-md border px-2 py-1 text-xs font-medium leading-none",
        toneClass[tone],
        className
      )}
    >
      {children}
    </span>
  )
}
