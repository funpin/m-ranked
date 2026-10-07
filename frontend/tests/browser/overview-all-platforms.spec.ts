import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("overview defaults to all platforms and coverage does not depend on the page or search", async ({page}) => {
  await page.goto("/review");
  await expect(page.getByRole("radio",{name:"Все",exact:true})).toBeChecked();
  await expect(page.getByRole("heading",{level:1,name:/Обзор вузов/})).toBeVisible();
  await expect(page.getByText("84 из 233 вузов",{exact:true})).toBeVisible();
  await page.getByRole("searchbox",{name:"Поиск вуза",exact:true}).fill("Альфа");
  await page.getByRole("button",{name:"Применить фильтры",exact:true}).click();
  await expect(page.getByText("84 из 233 вузов",{exact:true})).toBeVisible();
  await expect(page.getByRole("meter",{name:"Доля отслеживаемых вузов от М‑Рейтинга"})).toHaveAttribute("aria-valuenow","36");
});

for (const theme of ["light", "dark"] as const) {
  test(`all-platform overview shows totals, compact account links and honest missing values in ${theme} theme`, async ({page}) => {
    await page.addInitScript(value => localStorage.setItem("m-ranked-theme",value),theme);
    await page.goto("/review?platform=all&period=1d");
    const cards = page.getByTestId("platform-overview-card");
    const card = cards.first(), totals = card.getByRole("region",{name:"Прирост за сутки",exact:true});
    await expect(card).toContainText("400 подписчиков всего");
    await expect(totals.locator("b").nth(0)).toHaveText("2\u00a0400");
    await expect(totals.locator("b").nth(1)).toHaveText("84");
    await expect(totals.locator("b").nth(2)).toHaveText("0");
    await expect(totals.locator("b").nth(3)).toHaveText("—");
    await expect(totals.locator("b").nth(3).locator("..").locator("[title*=\"против предыдущего периода\"]")).toHaveCount(0);
    const networks = card.getByRole("group",{name:"Официальные соцсети вуза"});
    await expect(networks.getByRole("link")).toHaveCount(4);
    await expect(networks.getByRole("link").first()).toHaveAttribute("href","https://example.test/telegram/1");
    await expect(networks.getByRole("link").first()).toHaveAttribute("aria-label",/Официальный аккаунт университета с длинным названием/);
    await expect(card.getByTestId("overview-status")).toContainText("4/4 площадки");
    await expect(cards.nth(1).getByTestId("overview-status")).toContainText("1/4 площадки");
    await expect(cards.nth(1).getByRole("group",{name:"Официальные соцсети вуза"}).getByRole("link")).toHaveCount(1);
    await expect(page.getByRole("meter",{name:"Доля отслеживаемых вузов от М‑Рейтинга"})).toHaveAttribute("aria-valuenow","36");
    await expect(page.getByText("84 из 233 вузов",{exact:true})).toBeVisible();
    const layout = await page.evaluate(() => {
      const footers = [...document.querySelectorAll('[data-testid="overview-status"]')];
      return {
        pageOverflow:document.documentElement.scrollWidth > innerWidth,
        footerOverflow:footers.some(footer => footer.scrollWidth > footer.clientWidth),
        footerWrap:footers.some(footer => Math.abs(footer.children[0].getBoundingClientRect().y-footer.children[1].getBoundingClientRect().y) > 1),
      };
    });
    expect(layout).toEqual({pageOverflow:false,footerOverflow:false,footerWrap:false});
    expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
    await totals.getByRole("button",{name:"Как считается: Прирост просмотров за сутки · все соцсети",exact:true}).click();
    await expect(page.getByRole("dialog")).toContainText("недоступные метрики не заменяются нулями");
    await page.keyboard.press("Escape");
    await page.screenshot({path:`test-results/overview-all-${theme}-${test.info().project.name}.png`,fullPage:true});
  });
}

test("all-platform totals can be sorted and monthly values fit narrow cards", async ({page},testInfo) => {
  await page.goto("/review?platform=all&period=1d");
  await page.getByRole("combobox",{name:"Сортировка",exact:true}).selectOption("views");
  await page.getByRole("button",{name:"Применить фильтры",exact:true}).click();
  await expect(page).toHaveURL(/sort=views/);
  await expect(page.getByTestId("platform-overview-card").first()).toContainText("Бета Институт");
  await page.setViewportSize({width:testInfo.project.name === "mobile" ? 320 : 1208,height:900});
  await page.goto("/review?platform=all&period=30d");
  const totals = page.getByTestId("platform-overview-card").first().getByRole("region",{name:"Прирост за месяц",exact:true});
  await expect(totals.locator("b").first()).toHaveText("12,3 млн");
  const overflow = await totals.locator("b").evaluateAll(elements => elements.some(element => element.getBoundingClientRect().right > element.parentElement!.getBoundingClientRect().right+1));
  expect(overflow).toBe(false);
});
