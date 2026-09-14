import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Ждёт, пока доиграют анимации появления.
 *
 * Список проявляется волной сверху вниз, и пока строка не дошла до своей
 * очереди, она прозрачна. Проверять контраст в этот момент значит мерить
 * промежуточное состояние перехода, а не то, что читатель видит.
 */
async function settled(page: Page) {
  await page.evaluate(() => Promise.all(
    document.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
}

for (const theme of ["light", "dark"]) {
  test(`remaining screens fit the viewport and meet axe AA in ${theme} theme`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("m-ranked-theme", value), theme);
    await page.setExtraHTTPHeaders({ authorization: `Basic ${Buffer.from("admin:fixture-password").toString("base64")}` });
    for (const path of ["/rating?platform=telegram", "/accounts/00000001-0000-4000-8000-000000000001", "/compare?platform=max", "/missing-page", "/manage"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await settled(page);
      expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    }
  });
}

for (const path of ["/compare?platform=vk", "/posts/1"]) {
  test(`${path} controls work while the SVG runtime is still downloading`, async ({ page }) => {
    let release: (() => void) | undefined;
    const pending = new Promise<void>(resolve => { release = resolve; });
    let delayed = false;
    await page.route("**/_next/static/chunks/*.js", async route => {
      const response = await route.fetch();
      const body = await response.text();
      if (body.includes("recharts-wrapper")) {
        delayed = true;
        await pending;
      }
      await route.fulfill({ response, body });
    });
    try {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      const control = path.startsWith("/compare")
        ? page.getByTestId("comparison-legend-toggle").first()
        : page.getByRole("button", { name: "Авто", exact: true }).first();
      await control.click();
      await expect(control).toHaveAttribute("aria-pressed", path.startsWith("/compare") ? "false" : "true");
      await expect.poll(() => delayed).toBe(true);
      await expect(page.locator("svg.recharts-surface")).toHaveCount(0);
      release!();
      await expect(page.locator('[data-chart-ready="true"] svg.recharts-surface')).toHaveCount(2);
      await expect(control).toHaveAttribute("aria-pressed", path.startsWith("/compare") ? "false" : "true");
    } finally { release?.(); }
  });
}

test("keyboard skip link becomes visible and focuses the main content", async ({ page }) => {
  await page.goto("/rating?platform=telegram");
  await page.getByRole("heading", { level: 1 }).waitFor();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Перейти к содержимому" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
});

test("недельный график площадки рисуется двумя линиями со своими шкалами", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  const trend = page.getByRole("region", { name: "Динамика за неделю" });
  await expect(trend).toContainText("вышло 17 публикаций за 7 дней");
  // Две линии на двух шкалах: медианы реакций и просмотров живут в разных
  // порядках величин и общей шкалы не терпят.
  await expect(trend.locator("path.recharts-line-curve")).toHaveCount(2);
  await expect(trend.locator(".recharts-yAxis")).toHaveCount(2);
  // Обе шкалы подписаны: без подписей две линии в разных порядках величин
  // читаются как одна кривая неизвестного масштаба. Подписи в этой версии
  // Recharts лежат не внутри группы оси, а в отдельных слоях, поэтому
  // считаются по самой картинке.
  const labelled = await trend.locator("svg.recharts-surface text").count();
  expect(labelled).toBeGreaterThan(10);
  // Публикации дня — фоновыми столбцами, по одному на каждый день ряда.
  await expect(trend.locator(".recharts-bar-rectangle")).toHaveCount(6);
  await expect(trend).toContainText("публикаций в день");
});

test("нажатие по дню на графике переносит к публикациям этого дня", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  const trend = page.getByRole("region", { name: "Динамика за неделю" });
  await expect(trend.locator(".recharts-bar-rectangle").first()).toBeVisible();

  const rows = page.locator("tbody tr[data-published-day]");
  await expect(rows.first()).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0);

  // Столбец первого дня ряда — 1 июля, тот же день, что и у публикаций.
  await trend.locator(".recharts-bar-rectangle").first().click();

  const banner = page.getByRole("status");
  await expect(banner).toContainText("публикации этого дня");
  await expect(banner).toContainText("1.07");
  await expect(page.locator('tbody tr[data-published-day="2026-07-01"]').first()).toBeVisible();

  await banner.getByRole("button", { name: "показать все" }).click();
  await expect(page.getByRole("status")).toHaveCount(0);
});

test("значки ссылаются на общий набор, а не возят свои контуры", async ({ page }) => {
  const response = await page.goto("/");
  const html = (await response!.text());
  // Контуры объявлены один раз, значки ссылаются на объявление.
  expect(html.match(/<use href="#i-/g)?.length ?? 0).toBeGreaterThan(3);
  expect(html.match(/id="i-info"/g)?.length ?? 0).toBe(1);
  // Ни один значок из набора больше не приезжает своими контурами.
  expect(html).not.toContain("lucide-info");
  expect(html).not.toContain("lucide-file-text");
  expect(html).not.toContain("lucide-trending-up");
  // И значок всё ещё виден на экране.
  await expect(page.locator('svg use[href="#i-info"]').first()).toBeAttached();
});

test("плашка изменения показывается рядом с числом и молчит, когда сравнивать не с чем", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  const tiles = page.getByText("медиана реакций").locator("xpath=ancestor::div[1]");
  // В заглушке вчерашняя медиана реакций 4, сегодняшняя 5 — плашка «+1».
  await expect(tiles.getByTitle(/медиана реакций/)).toContainText("+1");
  // Место в рейтинге сравнивается с прошлым периодом и знак читается наоборот:
  // было пятое, стало второе — это подъём, значит зелёная стрелка вверх.
  const rating = page.getByText(/М‑Рейтинг/).locator("xpath=ancestor::div[1]");
  await expect(rating.getByTitle(/место против периода/)).toContainText("−3");
});

test("переключатель у графика меняет ряд, а столбцы публикаций остаются", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  const trend = page.getByRole("region", { name: "Динамика за неделю" });
  const toggle = trend.getByRole("group", { name: "Что показывают линии" });
  await expect(toggle.getByRole("button", { name: "Медианы" })).toHaveAttribute("aria-pressed", "true");
  await expect(trend).toContainText("медиана просмотров");

  await toggle.getByRole("button", { name: "Всего за день" }).click();
  await expect(toggle.getByRole("button", { name: "Всего за день" })).toHaveAttribute("aria-pressed", "true");
  await expect(trend).toContainText("всего просмотров");
  // Линий по-прежнему две, и столбцы публикаций на месте в обоих режимах.
  await expect(trend.locator("path.recharts-line-curve")).toHaveCount(2);
  await expect(trend.locator(".recharts-bar-rectangle")).toHaveCount(6);
  await expect(trend).toContainText("публикаций в день");
});

test("переключение режима не меняет высоту блока", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  const trend = page.getByRole("region", { name: "Динамика за неделю" });
  const toggle = trend.getByRole("group", { name: "Что показывают линии" });
  const legend = trend.locator("ul");
  const height = async (target: typeof trend) => (await target.boundingBox())!.height;
  // Ждём саму картинку: пока на её месте заготовка, страница короче, полоса
  // прокрутки то появляется, то нет, и от этого переносится текст вокруг.
  await expect(trend.locator("svg.recharts-surface")).toBeVisible();

  const medians = { block: await height(trend), legend: await height(legend) };
  await toggle.getByRole("button", { name: "Всего за день" }).click();
  await expect(trend).toContainText("всего просмотров");
  const totals = { block: await height(trend), legend: await height(legend) };

  // Подписи в двух режимах разной длины, и раньше легенда переносилась по
  // ширине — число строк менялось, блок прыгал. Сетка с постоянным числом
  // колонок этого не допускает.
  expect(totals.legend).toBe(medians.legend);
  expect(totals.block).toBe(medians.block);

  // И легенда стоит под графиком, а не над ним.
  const plot = trend.locator("svg.recharts-surface");
  expect((await legend.boundingBox())!.y).toBeGreaterThan((await plot.boundingBox())!.y);
});

test("строка таблицы открывает публикацию, а ссылка рядом уводит на площадку", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  const row = page.locator("tbody tr[data-published-day]").first();
  await expect(row).toHaveClass(/cursor-pointer/);
  // Ссылка на сам пост остаётся отдельной и уводит наружу.
  const outward = row.locator('a[target="_blank"]');
  await expect(outward).toHaveCount(1);
  await expect(outward).toHaveAttribute("rel", /noopener/);
  // А ссылка на нашу страницу публикации — первая в строке, как и была.
  await expect(row.locator('a[href^="/publications/"]')).toHaveCount(1);
  // Нажатие мимо ссылок открывает нашу страницу публикации.
  await row.getByRole("cell").nth(1).click();
  await expect(page).toHaveURL(/\/(publications|posts)\//);
});

test("список проявляется волной, а не разом", async ({ page }) => {
  await page.goto("/");
  const cards = page.locator("section.reveal > *");
  await expect(cards.first()).toBeVisible();
  // Волна идёт сверху вниз: у каждой следующей задержка больше предыдущей.
  const delays = await cards.evaluateAll((nodes) =>
    nodes.slice(0, 5).map((node) => getComputedStyle(node).animationDelay));
  expect(delays.length).toBeGreaterThan(1);
  expect(new Set(delays).size).toBe(delays.length);
  // И вся волна коротка: даже пятая карточка ждёт меньше десятой доли секунды.
  const last = Number.parseFloat(delays.at(-1) ?? "0");
  expect(last).toBeGreaterThan(0);
  expect(last).toBeLessThan(0.15);
});

test("шапка таблицы не участвует в волне", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  const head = page.locator("table.reveal > thead");
  await expect(head).toBeVisible();
  expect(await head.evaluate((node) => getComputedStyle(node).animationName)).toBe("none");
  // А строки — участвуют.
  const row = page.locator("table.reveal > tbody > tr").first();
  expect(await row.evaluate((node) => getComputedStyle(node).animationName)).toBe("reveal");
});
