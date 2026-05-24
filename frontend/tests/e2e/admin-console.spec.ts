import { expect, test } from "@playwright/test"

test("admin console supports bilingual navigation and core selections", async ({ page }) => {
  await page.goto("/admin")

  await expect(page.getByRole("heading", { name: "总览" })).toBeVisible()
  await expect(page.getByText("今日采集")).toBeVisible()
  await expect(page.getByText("情报控制台 / Intelligence Console")).toBeVisible()

  await page.getByRole("button", { name: "Toggle language" }).click()
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible()
  await expect(page.getByText("Collected Today")).toBeVisible()

  await page.getByRole("button", { name: /OpenAI model release brief lacks primary evidence/ }).first().click()
  await expect(page.locator("h1", { hasText: "Review Queue" })).toBeVisible()
  await expect(page.getByText("Raw Input")).toBeVisible()
  await expect(page.getByText("Claim Evidence", { exact: true }).first()).toBeVisible()

  await page.getByRole("button", { name: /Pipeline Runs/ }).click()
  await page.getByRole("button", { name: /Verifier/ }).click()
  await expect(page.getByRole("heading", { name: "Verifier Inspector" }).first()).toBeVisible()
  await expect(page.getByText("artifacts/runs/run_2026_05_23_1430/verification.jsonl")).toBeVisible()

  await page.getByRole("button", { name: /Data Ingestion/ }).click()
  await page.getByRole("button", { name: /GitHub Trending/ }).click()
  await expect(page.getByRole("heading", { name: "GitHub Trending" })).toBeVisible()
  await expect(page.getByText("Repository with unusual star growth")).toBeVisible()
})
