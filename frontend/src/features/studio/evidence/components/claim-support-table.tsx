"use client"

import { useMemo, useState } from "react"
import { Badge } from "@/components/common/badge"
import { EmptyState } from "@/components/common/empty-state"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { filterClaimsByStatus } from "@/features/studio/evidence/lib/evidence-adapter"
import type { ClaimSupportStatus, StudioClaimEvidence } from "@/types/evidence"

const FILTERS: Array<ClaimSupportStatus | "all"> = ["all", "accepted", "rejected", "uncertain", "unsupported"]

const STATUS_LABEL: Record<ClaimSupportStatus, string> = {
  accepted: "Accepted",
  rejected: "Rejected",
  uncertain: "Uncertain",
  unsupported: "Unsupported"
}

const STATUS_TONE: Record<ClaimSupportStatus, "success" | "danger" | "warning" | "info"> = {
  accepted: "success",
  rejected: "danger",
  uncertain: "warning",
  unsupported: "info"
}

export function ClaimSupportTable({ claims }: { claims: StudioClaimEvidence[] }) {
  const [statusFilter, setStatusFilter] = useState<ClaimSupportStatus | "all">("all")
  const filteredClaims = useMemo(() => filterClaimsByStatus(claims, statusFilter), [claims, statusFilter])

  if (!claims.length) {
    return <EmptyState title="No evidence matrix" description="This run did not generate claim-level evidence rows." />
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2" aria-label="Claim status filters">
        {FILTERS.map((filter) => (
          <Button
            key={filter}
            type="button"
            variant={statusFilter === filter ? "default" : "outline"}
            size="sm"
            onClick={() => setStatusFilter(filter)}
          >
            {filter === "all" ? "All" : STATUS_LABEL[filter]}
          </Button>
        ))}
      </div>
      {!filteredClaims.length ? (
        <EmptyState title="No matching claims" description="No claims match the selected evidence status." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Claim</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Sources</TableHead>
              <TableHead>Evidence</TableHead>
              <TableHead>Section</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredClaims.map((claim) => (
              <TableRow key={claim.claimId}>
                <TableCell className="min-w-[280px]">
                  <p className="font-medium text-foreground">{claim.claimText}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{claim.claimId}</p>
                  {claim.failureReason ? <p className="mt-2 text-xs text-muted-foreground">{claim.failureReason}</p> : null}
                </TableCell>
                <TableCell>
                  <Badge tone={STATUS_TONE[claim.status]}>{STATUS_LABEL[claim.status]}</Badge>
                  {claim.confidence !== undefined ? <p className="mt-2 text-xs text-muted-foreground">{formatConfidence(claim.confidence)} confidence</p> : null}
                </TableCell>
                <TableCell className="min-w-[220px]">
                  {claim.sourceRefs.length ? (
                    <div className="space-y-1">
                      {claim.sourceRefs.slice(0, 3).map((source, index) => (
                        <p key={`${source.url ?? source.sourceId ?? source.title}-${index}`} className="break-words text-xs text-muted-foreground">
                          {source.url ?? source.title ?? source.sourceId}
                        </p>
                      ))}
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">No sources</span>
                  )}
                </TableCell>
                <TableCell className="min-w-[180px]">
                  {claim.evidenceRefs.length ? (
                    <div className="space-y-1">
                      {claim.evidenceRefs.slice(0, 3).map((evidence, index) => (
                        <p key={`${evidence.evidenceId ?? evidence.quote ?? evidence.summary}-${index}`} className="break-words text-xs text-muted-foreground">
                          {evidence.evidenceId ?? evidence.quote ?? evidence.summary}
                        </p>
                      ))}
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">No evidence</span>
                  )}
                </TableCell>
                <TableCell>{claim.reportSection ? <span className="text-sm">{claim.reportSection}</span> : <span className="text-xs text-muted-foreground">No section</span>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  )
}

function formatConfidence(value: number): string {
  return `${Math.round(value <= 1 ? value * 100 : value)}%`
}
