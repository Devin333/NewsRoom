"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { ExternalLink, X } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ProjectDetailContent } from "@/features/projects/components/project-detail-panel"
import { fetchProjectDetail } from "@/lib/projects/api"
import { cn } from "@/lib/utils"
import type { ProjectItem } from "@/types/projects"

const CLOSE_ANIMATION_MS = 320

export function ProjectDetailDrawer({
  projectSlug,
  open,
  closeHref,
  onOpenChange,
}: {
  projectSlug?: string | null
  open: boolean
  closeHref: string
  onOpenChange: (open: boolean) => void
}) {
  const [project, setProject] = useState<ProjectItem | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !projectSlug) {
      const timeout = window.setTimeout(() => setProject(null), CLOSE_ANIMATION_MS)
      return () => window.clearTimeout(timeout)
    }

    let cancelled = false
    setIsLoading(true)
    setError(null)
    fetchProjectDetail(projectSlug)
      .then((result) => {
        if (!cancelled) {
          setProject(result)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(requestError instanceof Error ? requestError.message : "Project detail request failed.")
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [open, projectSlug])

  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onOpenChange(false)
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [onOpenChange, open])

  const isVisible = open && Boolean(projectSlug)
  const content = project ? (
    <>
      <header className="border-b border-[#d8dfd8] px-6 py-5 dark:border-border">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-[#334155]/55 dark:text-muted-foreground">
              Project Radar / {project.fullName}
            </p>
            <h2 className="mt-2 text-3xl font-black leading-tight text-[#334155] dark:text-foreground">{project.name}</h2>
            <p className="mt-3 max-w-4xl text-sm leading-6 text-[#334155]/68 dark:text-muted-foreground">{project.description}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Badge variant={project.maturity ? "info" : "muted"}>{project.maturity ? labelize(project.maturity) : "Maturity unavailable"}</Badge>
              {project.language ? <Badge variant="muted">{project.language}</Badge> : null}
            </div>
          </div>
          <Link
            href={closeHref}
            role="button"
            aria-label="Close project detail"
            className="rounded-full p-2 text-[#334155]/55 transition-colors hover:bg-white hover:text-[#334155] dark:hover:bg-card dark:hover:text-foreground"
            onClick={(event) => {
              event.preventDefault()
              onOpenChange(false)
            }}
          >
            <X className="size-5" />
          </Link>
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button asChild>
            <a href={project.repoUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" />
              Open repo
            </a>
          </Button>
          <Button asChild variant="outline">
            <Link href={`/projects/${project.slug}`}>Open full detail</Link>
          </Button>
        </div>
      </header>
      <div className="px-6 py-6">
        <ProjectDetailContent project={project} />
      </div>
    </>
  ) : null

  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-50 bg-[#0f172a]/25 backdrop-blur-sm transition-[opacity,backdrop-filter] duration-300",
          isVisible ? "opacity-100" : "pointer-events-none opacity-0 backdrop-blur-0"
        )}
        aria-hidden="true"
        onClick={() => onOpenChange(false)}
      />
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-[min(58rem,96vw)] flex-col border-l border-[#d8dfd8] bg-[#f7f9f6] shadow-[-24px_0_70px_rgba(15,23,42,0.18)] transition-[transform,opacity] duration-300 dark:border-border dark:bg-background xl:w-[min(76rem,72vw)]",
          isVisible ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-full opacity-0"
        )}
        aria-label="Project detail"
        aria-modal="true"
        role="dialog"
      >
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading ? <PageSkeleton /> : null}
          {error ? (
            <div className="p-6">
              <ErrorState title="Project detail failed to load" message={error} />
            </div>
          ) : null}
          {!isLoading && !error && !project ? (
            <div className="p-6">
              <EmptyState title="Project detail unavailable" description="No project detail was returned by the current real data source." />
            </div>
          ) : null}
          {!isLoading && !error ? content : null}
        </div>
      </aside>
    </>
  )
}

function labelize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}
