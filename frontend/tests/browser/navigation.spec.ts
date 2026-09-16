import { test, expect, type Page } from "@playwright/test";

/** Метка живёт только до перезагрузки документа, поэтому по ней видно, был
 *  переход клиентским или страница загрузилась заново. */
async function stamp(page: Page) {
  await page.evaluate(() => { (window as unknown as { __stamp?: string }).__stamp = "kept"; });
}
function kept(page: Page) {
  return page.evaluate(() => (window as unknown as { __stamp?: string }).__stamp);
}

async function delayMatchingNavigation(page: Page, matches: (url: URL) => boolean) {
  await page.route("**/*", async (route) => {
    if (matches(new URL(route.request().url()))) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
    await route.continue();
  });
}

test("переход по меню и открытие карточки не перезагружают документ", async ({ page }, info) => {
  test.skip(info.project.name === "mobile", "меню спрятано за гамбургером; переходы проверяются на широком экране");
  await page.goto("/?platform=telegram");
  await stamp(page);

  await page.getByTestId("main-nav").getByRole("link", { name: "Рейтинг" }).click();
  await expect(page).toHaveURL(/\/rating\?platform=telegram/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await kept(page)).toBe("kept");

  await page.goBack();
  await expect(page).toHaveURL(/\/\?platform=telegram/);
  expect(await kept(page)).toBe("kept");

  await page.getByTestId("platform-overview-card").first().click();
  await expect(page).toHaveURL(/\/accounts\//);
  expect(await kept(page)).toBe("kept");
});

test("смена периода и площадки не перезагружает документ", async ({ page }) => {
  await page.goto("/?platform=telegram");
  await stamp(page);

  await page.locator('select[name="period"]').selectOption("7d");
  await page.getByRole("button", { name: "Применить фильтры" }).click();
  await expect(page).toHaveURL(/period=7d/);
  expect(await kept(page)).toBe("kept");

  await page.getByTestId("platform-segments").locator('label:has(input[value="vk"])').click();
  await expect(page).toHaveURL(/platform=vk/);
  expect(await kept(page)).toBe("kept");
});

test.describe("без JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("меню и фильтры остаются рабочими обычной навигацией", async ({ page }, info) => {
    test.skip(info.project.name === "mobile", "гамбургер требует скриптов; на узком экране меню недоступно без них");
    await page.goto("/?platform=telegram");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    await page.getByTestId("main-nav").getByRole("link", { name: "Рейтинг" }).click();
    await expect(page).toHaveURL(/\/rating\?platform=telegram/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    await page.goto("/?platform=telegram");
    await page.locator('select[name="period"]').selectOption("7d");
    await page.getByRole("button", { name: "Применить фильтры" }).click();
    await expect(page).toHaveURL(/period=7d/);
    await expect(page.getByTestId("platform-overview-card").first()).toBeVisible();
  });
});

test("заготовка при переходе принадлежит той странице, куда идём", async ({ page }, info) => {
  test.skip(info.project.name === "mobile", "меню спрятано за гамбургером; переходы проверяются на широком экране");
  await page.goto("/?platform=telegram");
  // Ответ задерживается, чтобы заготовка успела показаться и её можно было
  // разглядеть: без задержки переход завершается за один кадр.
  await page.route("**/rating**", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.continue();
  });
  await page.getByTestId("main-nav").getByRole("link", { name: "Рейтинг" }).click();
  // На экране заготовка таблицы рейтинга, а не сетка карточек обзора и не
  // её заголовок с фильтрами.
  await expect(page.getByText("Загрузка таблицы")).toBeVisible();
  await expect(page.getByRole("searchbox", { name: "Поиск вуза" })).toHaveCount(0);
  await expect(page).toHaveURL(/\/rating/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("локальные заготовки не дублируют постоянную шапку страницы", async ({ page }) => {
  await page.goto("/?platform=telegram");
  await delayMatchingNavigation(page, (url) => ["/", "/rating"].includes(url.pathname) && url.searchParams.get("period") === "7d");

  await page.locator('select[name="period"]').selectOption("7d");
  await page.getByRole("button", { name: "Применить фильтры" }).click();

  await expect(page.getByText("Загрузка карточек")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);

  await expect(page).toHaveURL(/period=7d/);
  await page.goto("/rating?platform=telegram");
  await page.locator('select[name="period"]').selectOption("7d");
  await page.getByRole("button", { name: "Применить период" }).click();

  await expect(page.getByText("Загрузка таблицы")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
});

test("локальная заготовка карточки не повторяет название и переключатель", async ({ page }) => {
  const currentId = "00000001-0000-4000-8000-000000000002";
  const siblingId = "00000002-0000-4000-8000-000000000001";
  await page.goto(`/accounts/${currentId}`);
  await delayMatchingNavigation(page, (url) => url.pathname === `/accounts/${siblingId}`);

  await page.getByRole("navigation", { name: "Площадки вуза" })
    .getByRole("link", { name: /Канал 1/ }).click();

  const loading = page.locator('[role="status"]').filter({ hasText: "Загрузка данных площадки" });
  await expect(loading).toBeVisible();
  await expect(loading.locator(':scope > [data-slot="skeleton"]')).toHaveCount(0);
  await expect(loading.locator(":scope > .flex")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
});
