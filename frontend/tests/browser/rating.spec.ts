import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("меню ведёт на «Рейтинг» после «Сравнения», без параметра площадки", async ({ page }) => {
  await page.goto("/review?platform=vk");
  const links = page.getByTestId("main-nav").locator("a");
  const labels = await links.allTextContents();
  expect(labels.indexOf("Рейтинг")).toBe(labels.indexOf("Сравнение") + 1);
  // В мобильной шапке меню свёрнуто: ссылку ищем без требования видимости.
  await expect(links.filter({ hasText: "Рейтинг" })).toHaveAttribute("href", "/rating");
});

test("прогноз: статус, категории, диапазон места и пометка неполных данных", async ({ page }) => {
  await page.goto("/rating");
  await expect(page.getByRole("heading", { level: 1, name: "Рейтинг" })).toBeVisible();
  await expect(page.getByTestId("rating-status")).toContainText("Месяц не закончен");
  await expect(page.getByTestId("rating-row").first()).toContainText("СКФУ");
  await expect(page.getByTestId("rating-row").first()).toContainText("5–14");
  // Под сокращением — полное название вуза.
  await expect(page.getByTestId("rating-row").first()).toContainText("Северо-Кавказский федеральный университет");
  await page.getByTestId("rating-category").getByRole("link", { name: "VK" }).click();
  await expect(page).toHaveURL(/category=vk/);
  // Неполные данные — «*» перед числом, причина — в подсказке и для читалок.
  const partial = page.getByTestId("rating-row").filter({ hasText: "Нижневартовский" });
  await expect(partial).toContainText("*");
  await expect(partial.getByTitle(/нет полных данных/)).not.toHaveCount(0);
  await expect(page.getByTestId("rating-incomplete-note")).toContainText("неполные данные");
  await expect(page.getByTestId("rating-scatter")).toHaveCount(0);
  const axe = await new AxeBuilder({ page }).include("main").analyze();
  expect(axe.violations).toEqual([]);
});

test("ретроспективный месяц показывает факт, ± и разброс", async ({ page }) => {
  await page.goto("/rating?month=2026-09");
  await expect(page.getByTestId("rating-status")).toContainText("Ретроспективный расчёт");
  const headers = page.getByTestId("rating-table").getByRole("columnheader");
  await expect(headers.nth(0)).toContainText(/прогноз/i);
  await expect(headers.nth(1)).toContainText(/факт/i);
  await expect(headers.nth(2)).toHaveText("±");
  // Прогноз 8, факт 9: факт на место ниже прогноза.
  await expect(page.getByTestId("rating-row").first()).toContainText("−1");
  await expect(page.getByTestId("rating-scatter")).toBeVisible();
});

test("режим «Факт»: порядок по официальному месту, ± — прогноз против факта", async ({ page }) => {
  await page.goto("/rating?month=2026-09");
  await page.getByTestId("rating-view").getByRole("link", { name: "Факт" }).click();
  await expect(page).toHaveURL(/view=fact/);
  await expect(page.getByTestId("rating-table")).toHaveAttribute("data-view", "fact");
  const headers = page.getByTestId("rating-table").getByRole("columnheader");
  await expect(headers.nth(0)).toContainText(/факт/i);
  await expect(headers.nth(1)).toContainText(/прогноз/i);
  await expect(page.getByTestId("rating-row").first()).toContainText("+1");
  // Переход на другую категорию сохраняет режим.
  await page.getByTestId("rating-category").getByRole("link", { name: "VK" }).click();
  await expect(page).toHaveURL(/view=fact/);
  const axe = await new AxeBuilder({ page }).include("main").analyze();
  expect(axe.violations).toEqual([]);
});

test("режим «Факт» неопубликованного месяца объясняет, что факта ещё нет", async ({ page }) => {
  await page.goto("/rating?view=fact");
  await expect(page.getByText("Официальный рейтинг за октябрь 2026 ещё не опубликован или не загружен")).toBeVisible();
  await expect(page.getByTestId("rating-table")).toHaveCount(0);
});

test("прогноз неопубликованного месяца без колонок факта", async ({ page }) => {
  await page.goto("/rating");
  const headers = page.getByTestId("rating-table").getByRole("columnheader");
  await expect(headers.filter({ hasText: "±" })).toHaveCount(0);
  await expect(headers.filter({ hasText: /факт/i })).toHaveCount(0);
});

test("«Наша формула» — каркас с открытыми вопросами", async ({ page }) => {
  await page.goto("/rating/own/formula");
  await expect(page.getByTestId("rating-tabs").getByRole("link", { name: "Наш рейтинг" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("own-tabs").getByRole("link", { name: "Наша формула" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("Методика в разработке")).toBeVisible();
  await expect(page.getByText("Какие площадки входят и с какими весами.")).toBeVisible();
});

test("«М-Рейтинг без накрутки» — формула перед таблицей, места и что убрано", async ({ page }) => {
  await page.goto("/rating/own");
  await expect(page.getByTestId("own-tabs").getByRole("link", { name: "М-Рейтинг без накрутки" })).toHaveAttribute("aria-current", "page");
  const method = page.getByTestId("clean-method");
  await expect(method).toContainText("соцсети = 0.4 × MAX + 0.3 × VK + 0.3 × Rutube");
  // Пояснение стоит перед таблицей.
  const methodBox = await method.boundingBox();
  const tableBox = await page.getByTestId("clean-table").boundingBox();
  expect(methodBox!.y).toBeLessThan(tableBox!.y);
  const rows = page.getByTestId("clean-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(2)).toContainText("Университет с пакетами реакций");
  await expect(rows.nth(2).getByLabel("ниже на 19")).toBeVisible();
  await expect(rows.nth(2).getByTestId("rutube-batch")).toContainText("Rutube: 4 из 5 видео загружены 16 октября");
  await expect(rows.nth(0).getByTestId("rutube-batch")).toHaveCount(0);
  await page.getByTestId("clean-filter").getByRole("link", { name: "Только со сдвигом" }).click();
  await expect(page).toHaveURL(/filter=changed/);
  await expect(page.getByTestId("clean-row")).toHaveCount(2);
});

