import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("методология: обзор ведёт к статьям, статья — с оглавлением и соседями", async ({ page }) => {
  await page.goto("/methodology");
  await expect(page.getByRole("heading", { level: 1, name: "Методология" })).toBeVisible();
  await expect(page.getByTestId("methodology-articles").getByRole("link")).toHaveCount(8);
  await page.getByTestId("methodology-articles").getByRole("link", { name: /Расписание сбора/ }).click();
  await expect(page).toHaveURL(/\/methodology\/schedule$/);
  await expect(page.getByRole("heading", { level: 1, name: "Расписание сбора" })).toBeVisible();
  await expect(page.getByRole("table").first()).toContainText("каждые 5 минут");
  await expect(page.getByRole("navigation", { name: "Соседние статьи" })).toContainText("Только изменения и пробелы");
  await expect(page.locator('[data-article] a[href*="/edit/main/frontend/content/methodology/schedule.mdx"]')).toHaveCount(1);
});

test("оглавление статьи ведёт к её заголовкам", async ({ page }) => {
  test.skip(page.viewportSize()!.width < 1280, "оглавление показывается на широком экране");
  await page.goto("/methodology/analysis");
  const toc = page.getByTestId("article-toc");
  await expect(toc.getByRole("link")).not.toHaveCount(0);
  for (const href of await toc.getByRole("link").evaluateAll((links) => links.map((link) => link.getAttribute("href")!))) {
    await expect(page.locator(`[id="${decodeURIComponent(href.slice(1))}"]`)).toHaveCount(1);
  }
});

test("меню ведёт в методологию без параметра площадки", async ({ page }) => {
  await page.goto("/rating?platform=vk");
  await expect(page.locator('[data-testid="main-nav"] a[href="/methodology"], nav a[href="/methodology"]').first()).toBeAttached();
});

test("неизвестная статья — 404", async ({ request }) => {
  expect((await request.get("/methodology/unknown-article")).status()).toBe(404);
});

test("справочник API перечисляет публичные методы с примерами запросов", async ({ page }) => {
  await page.goto("/methodology/api");
  const reference = page.getByTestId("api-reference");
  await expect(reference.locator("[data-operation]")).not.toHaveCount(0);
  await expect(reference).toContainText("/api/v1/publications/{legacyId}/history");
  await expect(reference).not.toContainText("/api/v1/admin/");
  await expect(reference.locator('[data-operation="getSiteSummary"] code')).toContainText("/api/v1/site/summary");
});

for (const theme of ["light", "dark"]) {
  test(`методология и API проходят axe AA и не шире экрана в ${theme} теме`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("m-ranked-theme", value), theme);
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const path of ["/methodology", "/methodology/data-quality", "/methodology/api"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), path).toBe(0);
      expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations, path).toEqual([]);
    }
  });
}

test("карточки справочника не заезжают под оглавление", async ({ page }) => {
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/methodology/api");
    const overflow = await page.evaluate(() => {
      const article = document.querySelector("[data-testid=api-reference]")!.getBoundingClientRect();
      return [...document.querySelectorAll("[data-operation]")]
        .map((card) => Math.round(card.getBoundingClientRect().right - article.right))
        .filter((excess) => excess > 1);
    });
    expect(overflow, `${width}px`).toEqual([]);
  }
});
