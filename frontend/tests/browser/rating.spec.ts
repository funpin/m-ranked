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
  await expect(page.getByTestId("rating-row").first()).toContainText("8 (5–14)");
  await page.getByTestId("rating-category").getByRole("link", { name: "VK" }).click();
  await expect(page).toHaveURL(/category=vk/);
  await expect(page.getByTestId("rating-row").filter({ hasText: "Нижневартовский" })).toContainText("нет полных данных");
  await expect(page.getByTestId("rating-scatter")).toHaveCount(0);
  const axe = await new AxeBuilder({ page }).include("main").analyze();
  expect(axe.violations).toEqual([]);
});

test("ретроспективный месяц показывает факт, ошибку и разброс", async ({ page }) => {
  await page.goto("/rating?month=2026-09");
  await expect(page.getByTestId("rating-status")).toContainText("Ретроспективный расчёт");
  await expect(page.getByRole("columnheader", { name: "Факт" })).toBeVisible();
  await expect(page.getByTestId("rating-scatter")).toBeVisible();
});

test("«Наш рейтинг» — каркас с открытыми вопросами", async ({ page }) => {
  await page.goto("/rating/own");
  await expect(page.getByTestId("rating-tabs").getByRole("link", { name: "Наш рейтинг" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("Методика в разработке")).toBeVisible();
  await expect(page.getByText("Какие площадки входят и с какими весами.")).toBeVisible();
});
