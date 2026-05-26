import { access, readdir, readFile, stat } from "node:fs/promises"
import path from "node:path"
import { safeApiGet } from "@/lib/api/server"
import {
  buildProjectDetailResult,
  buildProjectListResult,
  normalizeProjectParams,
} from "@/lib/projects/mapper"
import type { ProjectDetailResult, ProjectListParams, ProjectListResult } from "@/types/projects"

type BackendRun = {
  run_id?: string
  workflow_id?: string
  started_at?: string
  finished_at?: string
}

type BackendRunList = {
  runs?: BackendRun[]
}

type BackendArtifact = {
  content?: unknown
  run_id?: string
  artifact_key?: string
}

type RawProjectPayload = {
  payload: unknown
  source: "backend" | "artifact"
  runId?: string
  generatedAt?: string
}

const PROJECT_WORKFLOW_ID = "project_radar-productized-board"
const LOCAL_ARTIFACT_FILES = ["board_output.json", "output.json", "cards.json"]

export async function getProjectList(params: ProjectListParams = {}): Promise<ProjectListResult> {
  const payload = (await loadBackendProjectPayload()) ?? (await loadLocalProjectPayload())
  if (!payload) {
    return buildProjectListResult(null, normalizeProjectParams(params), { source: "none" })
  }
  return buildProjectListResult(payload.payload, normalizeProjectParams(params), {
    source: payload.source,
    sourceRunId: payload.runId,
    generatedAt: payload.generatedAt,
  })
}

export async function getProjectDetail(slug: string): Promise<ProjectDetailResult | null> {
  const payload = (await loadBackendProjectPayload()) ?? (await loadLocalProjectPayload())
  if (!payload) return null
  return buildProjectDetailResult(payload.payload, slug, {
    source: payload.source,
    sourceRunId: payload.runId,
    generatedAt: payload.generatedAt,
  })
}

async function loadBackendProjectPayload(): Promise<RawProjectPayload | null> {
  const runsResult = await safeApiGet<BackendRunList>("/api/v1/runs?limit=80")
  if (!runsResult.ok) return null
  const projectRuns = (runsResult.data.runs ?? [])
    .filter(isProjectRun)
    .sort((left, right) => compareRunTime(right, left))

  for (const run of projectRuns) {
    const runId = run.run_id
    if (!runId) continue
    const artifact = await readBackendArtifact(runId, "board_output")
    if (artifact !== null) {
      return {
        payload: artifact,
        source: "backend",
        runId,
        generatedAt: extractGeneratedAt(artifact) ?? run.finished_at ?? run.started_at,
      }
    }
    const output = await readBackendArtifact(runId, "output")
    if (output !== null) {
      return {
        payload: output,
        source: "backend",
        runId,
        generatedAt: extractGeneratedAt(output) ?? run.finished_at ?? run.started_at,
      }
    }
  }

  return null
}

async function readBackendArtifact(runId: string, artifactKey: string): Promise<unknown | null> {
  const result = await safeApiGet<BackendArtifact>(
    `/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactKey)}`
  )
  if (!result.ok) return null
  return result.data.content ?? result.data
}

async function loadLocalProjectPayload(): Promise<RawProjectPayload | null> {
  const runsRoot = await resolveRunsRoot()
  if (!runsRoot) return null
  const entries = await readdir(runsRoot, { withFileTypes: true })
  const projectRuns = await Promise.all(
    entries
      .filter((entry) => entry.isDirectory() && entry.name.toLowerCase().includes("project_radar"))
      .map(async (entry) => {
        const runDir = path.join(runsRoot, entry.name)
        const info = await stat(runDir)
        return { runId: entry.name, runDir, mtimeMs: info.mtimeMs }
      })
  )

  for (const run of projectRuns.sort((left, right) => right.mtimeMs - left.mtimeMs)) {
    for (const fileName of LOCAL_ARTIFACT_FILES) {
      const filePath = path.join(run.runDir, fileName)
      const payload = await readJsonIfExists(filePath)
      if (payload !== null) {
        return {
          payload,
          source: "artifact",
          runId: run.runId,
          generatedAt: extractGeneratedAt(payload),
        }
      }
    }
  }

  return null
}

async function resolveRunsRoot(): Promise<string | null> {
  const candidates = [
    process.env.NEWSROOM_RUNS_DIR,
    path.resolve(process.cwd(), ".newsroom", "runs"),
    path.resolve(process.cwd(), "..", ".newsroom", "runs"),
  ].filter(Boolean) as string[]

  for (const candidate of candidates) {
    try {
      await access(candidate)
      return candidate
    } catch {
      continue
    }
  }
  return null
}

async function readJsonIfExists(filePath: string): Promise<unknown | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf8")) as unknown
  } catch {
    return null
  }
}

function isProjectRun(run: BackendRun): boolean {
  const workflow = run.workflow_id?.toLowerCase() ?? ""
  const runId = run.run_id?.toLowerCase() ?? ""
  return workflow === PROJECT_WORKFLOW_ID || workflow.includes("project_radar") || runId.includes("project_radar")
}

function compareRunTime(left: BackendRun, right: BackendRun): number {
  return timeValue(left.finished_at ?? left.started_at) - timeValue(right.finished_at ?? right.started_at)
}

function timeValue(value: string | undefined): number {
  if (!value) return Number.NEGATIVE_INFINITY
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : Number.NEGATIVE_INFINITY
}

function extractGeneratedAt(payload: unknown): string | undefined {
  const record = recordValue(payload)
  if (!record) return undefined
  const artifactMetadata = recordValue(record.artifact_metadata)
  return stringValue(record.generated_at) ?? stringValue(record.generatedAt) ?? stringValue(artifactMetadata?.generated_at)
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined
}
