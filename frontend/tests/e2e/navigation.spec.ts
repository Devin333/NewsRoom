import { expect, test } from "@playwright/test"

const routes = [
  "/",
  "/news",
  "/news/news-1-a",
  "/topics",
  "/topics/agent-runtime-observability",
  "/tech",
  "/tech/papers",
  "/tech/repos",
  "/tech/frameworks",
  "/reports",
  "/reports/report-daily-ai-runtime",
  "/search?q=agent&type=topic",
  "/studio",
  "/studio/runs",
  "/studio/runs/run-daily-20260522-0800",
  "/studio/runs/not-found-run",
  "/studio/sources",
  "/studio/memory",
  "/studio/quality",
  "/studio/artifacts",
]

for (const route of routes) {
  test(`${route} is reachable`, async ({ page }) => {
    const response = await page.goto(route)
    expect(response?.ok()).toBeTruthy()
    await expect(page.locator("body")).toBeVisible()
  })
}
