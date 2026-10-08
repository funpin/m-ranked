import { expect, test } from "@playwright/test";

// Поиск вуза на медленном устройстве: поле, отрисованное сервером, принимало
// ввод до гидратации и теряло его — список не открывался. Замедление CPU
// воспроизводит то, что CI под нагрузкой ловил изредка.
test.beforeEach(async ({ page }) => {
  test.skip(page.viewportSize()!.width < 1024, "одной компоновки достаточно");
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
});

test("institution search on statistics works before the page settles", async ({ page }) => {
  await page.goto("/statistics?mode=institution");
  await page.getByRole("combobox", { name: "Вуз" }).fill("002");
  await page.getByRole("option", { name: /Вуз 002/ }).click();
  await expect(page).toHaveURL(/institution=2/);
});

test("highlight search on compare works before the page settles", async ({ page }) => {
  await page.goto("/compare");
  const main = page.getByRole("main");
  await main.getByTestId("highlight-search").click();
  await expect(main.getByRole("combobox", { name: "Найти вуз для выделения" })).toBeFocused({ timeout: 15_000 });
  await page.keyboard.type("Альфа");
  await page.getByRole("option").first().click();
  await expect(main.getByTestId("highlight-chip")).toHaveCount(1);
});
