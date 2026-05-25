"use client"

import Link from "next/link"
import { Search } from "lucide-react"
import { useMemo, useState } from "react"
import { EmptyState } from "@/components/common/empty-state"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { formatBytes } from "@/lib/format"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioArtifact } from "@/types/artifact"

export function ArtifactListPanel({
  runId,
  artifacts,
  selectedArtifactKey
}: {
  runId: string
  artifacts: StudioArtifact[]
  selectedArtifactKey?: string
}) {
  const { t } = useI18n()
  const [query, setQuery] = useState("")
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return artifacts
    return artifacts.filter((artifact) =>
      [artifact.artifactKey, artifact.relativePath, artifact.contentType, artifact.previewKind]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(normalized)
    )
  }, [artifacts, query])

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("studio.artifacts.list")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <label className="relative block">
          <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
          <Input className="pl-9" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("studio.artifacts.searchPlaceholder")} />
        </label>

        {!filtered.length ? (
          <EmptyState title={t("studio.artifacts.empty")} description={t("studio.artifacts.emptyDescription")} />
        ) : (
          <div className="space-y-2">
            {filtered.map((artifact) => (
              <Link
                key={artifact.artifactKey}
                href={`/studio/artifacts/runs/${encodeURIComponent(runId)}?artifact=${encodeURIComponent(artifact.artifactKey)}`}
                className={[
                  "block rounded-md border p-3 transition-colors hover:border-primary/50 hover:bg-secondary/40",
                  artifact.artifactKey === selectedArtifactKey ? "border-primary/50 bg-primary/10" : "border-border"
                ].join(" ")}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">{artifact.artifactKey}</p>
                    <p className="mt-1 truncate text-xs text-muted-foreground">{artifact.relativePath ?? t("studio.artifacts.noPath")}</p>
                  </div>
                  <Badge variant={artifact.readError ? "danger" : "info"}>{artifact.previewKind}</Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span>{artifact.contentType ?? "unknown"}</span>
                  <span>{formatBytes(artifact.sizeBytes)}</span>
                  {artifact.truncated ? <span>{t("studio.artifacts.truncated")}</span> : null}
                  {artifact.redacted ? <span>{t("studio.artifacts.redacted")}</span> : null}
                </div>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
