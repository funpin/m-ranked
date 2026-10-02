import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("institution facts keep their identity across platforms and explain their source", async ({ page }) => {
  for (const path of ["/channels/1", "/platform-accounts/1", "/platform-accounts/3", "/platform-accounts/4"]) {
    await page.goto(path);
    const facts = page.getByRole("region", { name: "Сводка вуза" });
    await expect(facts).toContainText("02.07.2026");
    await expect(facts).toContainText(/8\s202/);
    await expect(facts).toContainText("На 30.09.2026");
    await expect(facts.getByRole("link", {name: /ведомость/})).toHaveAttribute("href", "https://mipt.ru/vikon/sveden/files/eiw/Svedeniya_o_chislennosti_obuchayuschixsya_ot_30.09.2026%281%29.pdf");
    expect((await new AxeBuilder({ page }).include('[aria-label="Сводка вуза"]').withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  }
  const facts = page.getByRole("region", { name: "Сводка вуза" });
  await facts.getByRole("button", { name: "Как считается: Студентов" }).click();
  await expect(page.getByRole("dialog")).toContainText("Без филиалов, СПО и аспирантуры");
});

test("an older API can omit the new profile without breaking the account page", async ({ page }) => {
  await page.goto("/channels/2");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const facts = page.getByRole("region", { name: "Сводка вуза" });
  await expect(facts).toContainText("Дата не указана");
  await expect(facts).toContainText("Нет данных");
  await expect(facts.getByRole("link", {name: /ведомость/})).toHaveCount(0);
});
