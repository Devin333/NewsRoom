import type { Paper } from "@/lib/papers/types"

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

type GitHubRepoStats = {
  githubStars: number
  repoUrl: string
  repoSlug: string
}

type OpenAlexCitation = {
  citationCount: number
  openAlexId?: string
}

const GITHUB_HOST = "github.com"
const OPENALEX_ENDPOINT = "https://api.openalex.org/works"
const REPO_PATH_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/
const REQUEST_HEADERS = {
  Accept: "application/json",
  "User-Agent": "NewsRoomResearch/0.1"
}

const paperCache = new Map<string, Promise<Paper | null>>()

export function normalizeGithubRepoUrl(value?: string) {
  const slug = githubRepoSlug(value)
  return slug ? `https://${GITHUB_HOST}/${slug}` : undefined
}

export function githubRepoSlug(value?: string) {
  if (!value) {
    return undefined
  }

  const cleanValue = value.trim().replace(/\.git$/i, "")
  if (!cleanValue) {
    return undefined
  }

  if (REPO_PATH_PATTERN.test(cleanValue)) {
    return cleanValue
  }

  let parsed: URL
  try {
    parsed = new URL(cleanValue.replace(/^http:\/\//i, "https://"))
  } catch {
    return undefined
  }

  if (parsed.protocol !== "https:" || parsed.hostname.toLowerCase().replace(/^www\./, "") !== GITHUB_HOST) {
    return undefined
  }

  const [owner, repo] = parsed.pathname.split("/").filter(Boolean)
  const slug = owner && repo ? `${owner}/${repo.replace(/\.git$/i, "")}` : undefined
  return slug && REPO_PATH_PATTERN.test(slug) ? slug : undefined
}

export function normalizeDoi(value?: string) {
  if (!value) {
    return undefined
  }
  const doi = value.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
  return doi ? doi.toLowerCase() : undefined
}

export function arxivIdFromPaper(paper: Pick<Paper, "arxivUrl" | "paperUrl" | "pdfUrl">) {
  for (const value of [paper.arxivUrl, paper.pdfUrl, paper.paperUrl]) {
    const id = arxivIdFromUrl(value)
    if (id) {
      return id
    }
  }
  return undefined
}

export function arxivIdFromUrl(value?: string) {
  if (!value) {
    return undefined
  }

  let parsed: URL
  try {
    parsed = new URL(value.trim().replace(/^http:\/\//i, "https://"))
  } catch {
    return undefined
  }

  if (parsed.hostname.toLowerCase().replace(/^www\./, "") !== "arxiv.org") {
    return undefined
  }

  const match = parsed.pathname.match(/^\/(?:abs|pdf)\/([^/?#]+?)(?:\.pdf)?$/i)
  return match?.[1]?.replace(/v\d+$/i, "")
}

export async function enrichPapersForPublicStream(papers: Paper[], fetchImpl: FetchLike = fetch) {
  const enriched = await Promise.all(papers.map((paper) => enrichPaperForPublicStream(paper, fetchImpl)))
  return enriched.filter(isPaper)
}

export function clearPaperEnrichmentCache() {
  paperCache.clear()
}

export async function enrichPaperForPublicStream(paper: Paper, fetchImpl: FetchLike = fetch) {
  const repoUrl = normalizeGithubRepoUrl(paper.repoUrl)
  if (!paper.isPublished || !repoUrl) {
    return null
  }

  const cacheKey = `${paper.id}:${repoUrl}:${paper.citationDoi ?? paper.arxivUrl ?? paper.paperUrl ?? paper.title}`
  let cached = paperCache.get(cacheKey)
  if (!cached) {
    cached = enrichPaper(paper, repoUrl, fetchImpl)
    paperCache.set(cacheKey, cached)
  }
  return cached
}

export async function fetchGitHubRepoStats(repoUrl: string, fetchImpl: FetchLike = fetch): Promise<GitHubRepoStats | null> {
  const slug = githubRepoSlug(repoUrl)
  if (!slug) {
    return null
  }

  const response = await fetchImpl(`https://api.github.com/repos/${slug}`, { headers: REQUEST_HEADERS })
  if (!response.ok) {
    return null
  }

  const payload = await response.json() as Record<string, unknown>
  const stars = typeof payload.stargazers_count === "number" ? payload.stargazers_count : undefined
  const htmlUrl = typeof payload.html_url === "string" ? normalizeGithubRepoUrl(payload.html_url) : undefined
  const fullName = typeof payload.full_name === "string" ? payload.full_name : slug

  if (stars === undefined || !htmlUrl) {
    return null
  }

  return {
    githubStars: stars,
    repoUrl: htmlUrl,
    repoSlug: fullName
  }
}

export async function fetchOpenAlexCitation(paper: Paper, fetchImpl: FetchLike = fetch): Promise<OpenAlexCitation | null> {
  const doi = normalizeDoi(paper.citationDoi) ?? doiFromArxivId(arxivIdFromPaper(paper))
  if (!doi) {
    return null
  }

  const openAlexId = `https://doi.org/${doi}`
  const response = await fetchImpl(`${OPENALEX_ENDPOINT}/${encodeURIComponent(openAlexId)}`, { headers: REQUEST_HEADERS })
  if (!response.ok) {
    return null
  }

  const payload = await response.json() as Record<string, unknown>
  const title = typeof payload.display_name === "string" ? payload.display_name : ""
  const citationCount = typeof payload.cited_by_count === "number" ? payload.cited_by_count : undefined
  const id = typeof payload.id === "string" ? payload.id : undefined

  if (citationCount === undefined || !titlesMatch(paper.title, title)) {
    return null
  }

  return { citationCount, openAlexId: id }
}

function doiFromArxivId(arxivId?: string) {
  return arxivId ? `10.48550/arxiv.${arxivId}` : undefined
}

async function enrichPaper(paper: Paper, repoUrl: string, fetchImpl: FetchLike) {
  const [repoStats, citation] = await Promise.all([
    fetchGitHubRepoStats(repoUrl, fetchImpl),
    fetchOpenAlexCitation(paper, fetchImpl)
  ])

  if (!repoStats || !citation) {
    return null
  }

  return {
    ...paper,
    repoUrl: repoStats.repoUrl,
    githubStars: repoStats.githubStars,
    citationCount: citation.citationCount,
    starsPerHour: undefined
  }
}

function titlesMatch(left: string, right: string) {
  const normalizedLeft = normalizeTitle(left)
  const normalizedRight = normalizeTitle(right)
  return normalizedLeft === normalizedRight || normalizedLeft.includes(normalizedRight) || normalizedRight.includes(normalizedLeft)
}

function normalizeTitle(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()
}

function isPaper(value: Paper | null): value is Paper {
  return value !== null
}
