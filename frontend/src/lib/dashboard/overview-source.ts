import fs from "node:fs"
import path from "node:path"
import { safeApiGet } from "@/lib/api/server"
import { mockDashboardOverview } from "@/lib/api/mock-data"
import {
  adaptBoardGroupToOverview,
  adaptDashboardArtifact,
  adaptMockDashboardOverview,
  emptyDashboardOverview,
  hasDashboardContent,
  type BoardOutputSource
} from "@/lib/dashboard/overview-adapter"
import type { DashboardOverview } from "@/types/dashboard"

type JsonRecord = Record<string, unknown>

type SourceResult = {
  available: boolean
  overview: DashboardOverview | null
  notices: string[]
}

type RunListResponse = {
  runs?: unknown
  items?: unknown
}

type LocalCandidate = {
  runDir: string
  name: string
  manifest: JsonRecord | undefined
  modifiedAt: string
}

const MAX_ARTIFACT_BYTES = 8_000_000
const BACKEND_ARTIFACT_KEYS = ["cross_board_output", "board_output", "output"] as const
const LOCAL_CROSS_BOARD_FILES = ["cross_board_output.json", "board_output.json", "output.json", "report.json"]
const LOCAL_BOARD_FILES = ["board_output.json", "output.json"]
const PRODUCTIZED_BOARDS = new Set(["ai_news", "project_radar", "paper_radar", "community_pulse"])

export async function getDashboardOverview(): Promise<DashboardOverview> {
  const notices: string[] = []
  const backend = await loadBackendDashboardOverview()
  notices.push(...backend.notices)
  if (backend.overview && hasDashboardContent(backend.overview)) {
    return withNotices(backend.overview, notices)
  }

  const local = loadLocalDashboardOverview()
  notices.push(...local.notices)
  if (local.overview && hasDashboardContent(local.overview)) {
    return withNotices(local.overview, notices)
  }

  if (!backend.available && !local.available) {
    return withNotices(adaptMockDashboardOverview(mockDashboardOverview), [...notices, "Showing local fallback"])
  }

  return emptyDashboardOverview(notices.length ? notices : ["No displayable cross-board content was found."])
}

export async function loadBackendDashboardOverview(): Promise<SourceResult> {
  const notices: string[] = []
  const runsResult = await safeApiGet<RunListResponse>("/api/v1/runs?limit=50")
  if (!runsResult.ok) {
    return {
      available: false,
      overview: null,
      notices: [`Backend run lookup failed: ${runsResult.errorMessage}`]
    }
  }

  const runs = arrayRecords(runsResult.data.runs ?? runsResult.data.items).sort(compareRunTime)
  const crossBoardRuns = runs.filter(isCrossBoardRun)
  for (const run of crossBoardRuns) {
    const runId = text(run.run_id) || text(run.id)
    if (!runId) {
      continue
    }
    for (const artifactKey of BACKEND_ARTIFACT_KEYS) {
      const artifact = await loadBackendArtifact(runId, artifactKey)
      if (!artifact.ok) {
        continue
      }
      const overview = adaptDashboardArtifact(artifact.data, {
        dataState: "ready",
        generatedAt: generatedAtFromRunOrPayload(run, artifact.data),
        sourceLabel: `Backend ${artifactKey} artifact`,
        notices: []
      })
      if (overview && hasDashboardContent(overview)) {
        return { available: true, overview, notices }
      }
    }
  }

  const latestReport = await safeApiGet<unknown>("/api/v1/reports/latest")
  if (latestReport.ok) {
    const overview = adaptDashboardArtifact(latestReport.data, {
      dataState: "ready",
      sourceLabel: "Backend latest report",
      notices: []
    })
    if (overview && hasDashboardContent(overview)) {
      return { available: true, overview, notices }
    }
  } else {
    notices.push(`Backend latest report lookup failed: ${latestReport.errorMessage}`)
  }

  const reportList = await safeApiGet<{ reports?: unknown; items?: unknown }>("/api/v1/reports?limit=10")
  if (reportList.ok) {
    for (const report of arrayRecords(reportList.data.reports ?? reportList.data.items)) {
      const overview = adaptDashboardArtifact(report, {
        dataState: "ready",
        sourceLabel: "Backend report",
        notices: []
      })
      if (overview && hasDashboardContent(overview)) {
        return { available: true, overview, notices }
      }
    }
  }

  return {
    available: true,
    overview: null,
    notices: [...notices, "Backend did not expose a populated cross_board output."]
  }
}

export function loadLocalDashboardOverview(): SourceResult {
  const roots = runsRoots()
  const existingRoots = roots.filter((root) => fs.existsSync(root) && fs.statSync(root).isDirectory())
  if (!existingRoots.length) {
    return {
      available: false,
      overview: null,
      notices: [`No local runs root found at ${roots.join(", ")}.`]
    }
  }

  const candidates = existingRoots.flatMap(localCandidates)
  for (const candidate of candidates.filter(isCrossBoardCandidate)) {
    for (const fileName of LOCAL_CROSS_BOARD_FILES) {
      const payload = readJsonFile(path.join(candidate.runDir, fileName))
      const overview = adaptDashboardArtifact(payload, {
        dataState: "ready",
        generatedAt: generatedAtFromPayload(payload) ?? candidate.modifiedAt,
        sourceLabel: `Local ${candidate.name}/${fileName}`,
        notices: [`Loaded local cross-board artifact from ${candidate.name}.`]
      })
      if (overview && hasDashboardContent(overview)) {
        return { available: true, overview, notices: [] }
      }
    }
  }

  const grouped = latestProductizedBoardGroup(candidates)
  if (grouped.length) {
    const overview = adaptBoardGroupToOverview(grouped, {
      sourceLabel: "Local productized board outputs",
      notices: ["Built partial cross-board overview from local productized board outputs."]
    })
    if (overview && hasDashboardContent(overview)) {
      return { available: true, overview, notices: [] }
    }
  }

  return {
    available: true,
    overview: null,
    notices: ["No local cross_board artifact or productized board output with displayable content was found."]
  }
}

async function loadBackendArtifact(runId: string, artifactKey: string) {
  return safeApiGet<unknown>(`/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactKey)}`)
}

function localCandidates(root: string): LocalCandidate[] {
  return fs
    .readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name !== "_records")
    .map((entry) => {
      const runDir = path.join(root, entry.name)
      const manifest = asRecord(readJsonFile(path.join(runDir, "manifest.json")))
      const modifiedAt = latestModifiedAt([
        path.join(runDir, "cross_board_output.json"),
        path.join(runDir, "board_output.json"),
        path.join(runDir, "output.json"),
        path.join(runDir, "manifest.json")
      ])
      return { runDir, name: entry.name, manifest, modifiedAt }
    })
    .sort((left, right) => Date.parse(right.modifiedAt) - Date.parse(left.modifiedAt))
}

function latestProductizedBoardGroup(candidates: LocalCandidate[]): BoardOutputSource[] {
  const groups = new Map<string, BoardOutputSource[]>()
  for (const candidate of candidates) {
    const payload = firstExistingPayload(candidate, LOCAL_BOARD_FILES)
    if (!payload) {
      continue
    }
    const boardType = boardTypeFromCandidate(candidate, payload)
    if (!PRODUCTIZED_BOARDS.has(boardType)) {
      continue
    }
    const dateKey = dateKeyFromCandidate(candidate, payload)
    const group = groups.get(dateKey) ?? []
    if (!group.some((item) => item.boardType === boardType)) {
      group.push({
        boardType,
        payload,
        generatedAt: generatedAtFromPayload(payload) ?? candidate.modifiedAt,
        sourceLabel: candidate.name
      })
    }
    groups.set(dateKey, group)
  }

  return [...groups.entries()]
    .sort((left, right) => {
      const leftScore = left[1].length * 10_000 + Number(left[0])
      const rightScore = right[1].length * 10_000 + Number(right[0])
      return rightScore - leftScore
    })[0]?.[1] ?? []
}

function firstExistingPayload(candidate: LocalCandidate, fileNames: string[]) {
  for (const fileName of fileNames) {
    const payload = readJsonFile(path.join(candidate.runDir, fileName))
    if (payload) {
      return payload
    }
  }
  return undefined
}

function isCrossBoardCandidate(candidate: LocalCandidate) {
  const manifest = candidate.manifest
  const productization = asRecord(manifest?.business_productization)
  return (
    candidate.name.toLowerCase().includes("cross_board") ||
    candidate.name.toLowerCase().includes("cross-board") ||
    text(manifest?.workflow_id).toLowerCase().includes("cross") ||
    text(manifest?.run_id).toLowerCase().includes("cross") ||
    text(productization?.board_type) === "cross_board"
  )
}

function isCrossBoardRun(run: JsonRecord) {
  const values = [run.workflow_id, run.profile, run.run_id, run.id, run.board_type].map(text).join(" ").toLowerCase()
  return values.includes("cross_board") || values.includes("cross-board") || values.includes("cross board")
}

function boardTypeFromCandidate(candidate: LocalCandidate, payload: unknown) {
  const payloadRecord = asRecord(unwrapPayload(payload))
  const productization = asRecord(candidate.manifest?.business_productization)
  return (
    text(payloadRecord?.board_type) ||
    text(payloadRecord?.boardType) ||
    text(productization?.board_type) ||
    [...PRODUCTIZED_BOARDS].find((board) => candidate.name.toLowerCase().includes(board)) ||
    ""
  )
}

function dateKeyFromCandidate(candidate: LocalCandidate, payload: unknown) {
  const nameDate = candidate.name.match(/20\d{6}/)?.[0]
  if (nameDate) {
    return nameDate
  }
  const generatedAt = generatedAtFromPayload(payload) ?? candidate.modifiedAt
  return generatedAt.slice(0, 10).replace(/-/g, "")
}

function runsRoots() {
  if (process.env.NEWSROOM_RUNS_ROOT) {
    return [process.env.NEWSROOM_RUNS_ROOT]
  }
  return [
    path.resolve(process.cwd(), ".newsroom", "runs"),
    path.resolve(process.cwd(), "..", ".newsroom", "runs")
  ]
}

function readJsonFile(filePath: string): unknown {
  if (!fs.existsSync(filePath)) {
    return undefined
  }
  const stat = fs.statSync(filePath)
  if (!stat.isFile() || stat.size <= 2 || stat.size > MAX_ARTIFACT_BYTES) {
    return undefined
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8")) as unknown
  } catch {
    return undefined
  }
}

function latestModifiedAt(filePaths: string[]) {
  const times = filePaths
    .filter((filePath) => fs.existsSync(filePath))
    .map((filePath) => fs.statSync(filePath).mtimeMs)
  return new Date(Math.max(0, ...times)).toISOString()
}

function generatedAtFromRunOrPayload(run: JsonRecord, payload: unknown) {
  return generatedAtFromPayload(payload) ?? text(run.finished_at) ?? text(run.finishedAt) ?? text(run.started_at) ?? text(run.startedAt) ?? null
}

function generatedAtFromPayload(payload: unknown): string | null {
  const record = asRecord(unwrapPayload(payload))
  const boardOutput = asRecord(record?.board_output) ?? asRecord(record?.boardOutput)
  const output = asRecord(record?.output)
  const crossBoard = asRecord(record?.cross_board_output) ?? asRecord(output?.cross_board_output)
  return (
    text(record?.generated_at) ||
    text(record?.generatedAt) ||
    text(boardOutput?.generated_at) ||
    text(boardOutput?.generatedAt) ||
    text(crossBoard?.generated_at) ||
    text(crossBoard?.generatedAt) ||
    null
  )
}

function unwrapPayload(payload: unknown): unknown {
  const record = asRecord(payload)
  if (!record) {
    return payload
  }
  return record.content ?? record.data ?? payload
}

function compareRunTime(left: JsonRecord, right: JsonRecord) {
  return runTime(right) - runTime(left)
}

function runTime(run: JsonRecord) {
  const value = text(run.finished_at) || text(run.finishedAt) || text(run.started_at) || text(run.startedAt)
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : 0
}

function withNotices(overview: DashboardOverview, notices: string[]): DashboardOverview {
  return {
    ...overview,
    notices: uniqueStrings([...(overview.notices ?? []), ...notices])
  }
}

function arrayRecords(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is JsonRecord => item !== undefined) : []
}

function asRecord(value: unknown): JsonRecord | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : undefined
}

function text(value: unknown) {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : ""
}

function uniqueStrings(values: string[]) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))]
}
