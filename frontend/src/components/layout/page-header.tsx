import type { ReactNode } from "react"

export type PageHeaderProps = {
  title: string
  description?: string
  eyebrow?: string
  actions?: ReactNode
}

export function PageHeader({ title, description, eyebrow, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-col gap-4 border-b border-border pb-4 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0 space-y-2">
        {eyebrow ? <p className="text-xs font-semibold uppercase tracking-normal text-primary">{eyebrow}</p> : null}
        <div>
          <h1 className="text-2xl font-semibold tracking-normal text-foreground">{title}</h1>
          {description ? <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}
