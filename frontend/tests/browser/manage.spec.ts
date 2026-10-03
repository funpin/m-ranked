import { test,expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/** Вход идёт настоящей формой: куку ставит фасад, как и в браузере пользователя. */
async function signIn(page:import("@playwright/test").Page,role:string){
  await page.goto("/manage");
  await page.locator('[data-testid="admin-login"] input[name="username"]').fill(role);
  await page.locator('[data-testid="admin-login"] input[name="password"]').fill("fixture-password");
  await page.locator('[data-testid="admin-login"] input[name="otp"]').fill("123456");
  await page.getByRole("button",{name:"Войти"}).click();
  await expect(page.getByTestId("platform-table")).toBeVisible();
}
test("manage shows a sign-in form and no administrative data without a session",async({page})=>{
  const response=await page.goto("/manage");
  expect(response?.status()).toBe(200);
  expect(response?.headers()["cache-control"]).toContain("no-store");
  await expect(page.getByTestId("admin-login")).toBeVisible();
  await expect(page.getByTestId("platform-table")).toHaveCount(0);
  // Пароль и код — разные поля: код не дописывается к паролю.
  await expect(page.locator('[data-testid="admin-login"] input[name="password"]')).toHaveAttribute("type","password");
  await expect(page.locator('[data-testid="admin-login"] input[name="otp"]')).toHaveAttribute("inputmode","numeric");
});
test("the sign-in form opens a session and the catalog appears",async({page})=>{
  await page.goto("/manage");
  await page.locator('[data-testid="admin-login"] input[name="username"]').fill("admin");
  await page.locator('[data-testid="admin-login"] input[name="password"]').fill("fixture-password");
  await page.locator('[data-testid="admin-login"] input[name="otp"]').fill("123456");
  await page.getByRole("button",{name:"Войти"}).click();
  await expect(page.getByTestId("platform-table")).toBeVisible();
  await expect(page.getByRole("button",{name:"Выйти"})).toBeVisible();
  const cookies=await page.context().cookies();
  const session=cookies.find((cookie)=>cookie.name==="__Host-mranked-admin");
  expect(session?.httpOnly).toBe(true);expect(session?.secure).toBe(true);expect(session?.sameSite).toBe("Strict");
  expect(await page.content()).not.toContain("fixture-password");
});
for(const role of ["viewer","editor","admin"]) test(`manage ${role} receives SSR catalog and correct capabilities`,async({page})=>{
  await signIn(page,role);
  const response=await page.goto("/manage");expect(response?.status()).toBe(200);expect(response?.headers()["cache-control"]).toContain("no-store");
  await expect(page.getByRole("heading",{name:"Управление каналами"})).toBeVisible();
  await expect(page.getByTestId('platform-table').locator('tbody tr')).toHaveCount(8);
  await expect(page.locator('[data-testid="institution-create"] input[name="name"]')).toBeEnabled({enabled:role!=="viewer"});
  await expect(page.getByRole("button",{name:"Удалить",exact:true}).first()).toBeEnabled({enabled:role==="admin"});
  const html=await page.content();expect(html).not.toContain("fixture-password");
  await expect(page.locator('#accountMatrix input[name="telegram"]')).toHaveValue("https://example.test/telegram/1");
  // Раскрывающийся chat_id MAX из таблицы убран: идентификатор виден подписью.
  await expect(page.getByTestId("native-id-editor")).toHaveCount(0);
  await expect(page.getByTestId("platform-table")).toContainText("chat_id");
  if(role!=="viewer") {
    await page.locator("#matrixInstitution").selectOption("2");
    await expect(page.locator("#accountMatrix")).toHaveAttribute("action","/manage/institutions/2/accounts");
    await expect(page.locator('#accountMatrix input[name="vk"]')).toHaveValue("https://example.test/vk/2");
    const versions=JSON.parse(await page.locator('#accountMatrix input[name="expected_account_versions"]').inputValue());expect(Object.keys(versions)).toHaveLength(4);expect(new Set(Object.values(versions))).toEqual(new Set([7]));
    let posted:URLSearchParams|undefined;
    await page.route("**/manage/institutions/2/accounts",async(route)=>{posted=new URLSearchParams(route.request().postData()??"");await route.fulfill({status:200,contentType:"text/html",body:"<h1>Fixture received form</h1>"});});
    await page.getByRole("button",{name:"Сохранить аккаунты"}).click();
    await expect.poll(()=>posted?.get("csrf_token")).toBe("fixture-csrf-token");expect(posted?.get("expected_row_version")).toBe("4");expect(posted?.get("correlation_id")).toMatch(/^[0-9a-f-]{36}$/);expect(posted?.get("telegram")).toBe("https://example.test/telegram/2");
    await page.goto("/manage");
  }
  expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
});

test("catalog deletion requires dialog confirmation and preserves the native payload", async ({ page }) => {
  await signIn(page, "admin");
  const form = page.locator('form[action$="/delete"]').first();
  const trigger = form.getByRole("button", { name: "Удалить", exact: true });
  const action = await form.getAttribute("action");
  let posted: URLSearchParams | undefined;
  await page.route(`**${action}`, async (route) => {
    posted = new URLSearchParams(route.request().postData() ?? "");
    await route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Fixture received deletion</h1>" });
  });
  await trigger.click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Восстановить их будет нельзя.");
  await dialog.getByRole("button", { name: "Отмена" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  expect(posted).toBeUndefined();
  await trigger.click();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  expect(posted).toBeUndefined();
  await trigger.click();
  await dialog.getByRole("button", { name: "Удалить", exact: true }).click();
  await expect.poll(() => posted?.get("csrf_token")).toBe("fixture-csrf-token");
  expect(posted?.get("expected_row_version")).toBe("7");
  expect(posted?.get("correlation_id")).toMatch(/^[0-9a-f-]{36}$/);
});

test("catalog forms submit with JavaScript disabled", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    // Форма входа тоже обычная: без скриптов она отправляется так же.
    await signIn(page, "editor");
    const form = page.getByTestId("institution-create");
    await form.getByRole("textbox", { name: "Полное название" }).fill("Тестовый университет");
    let posted: URLSearchParams | undefined;
    await page.route("**/manage/institutions", async (route) => {
      posted = new URLSearchParams(route.request().postData() ?? "");
      await route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Fixture received institution</h1>" });
    });
    await form.getByRole("button", { name: "Добавить вуз" }).click();
    await expect.poll(() => posted?.get("name")).toBe("Тестовый университет");
    expect(posted?.get("csrf_token")).toBe("fixture-csrf-token");
    expect(posted?.get("expected_row_version")).toBe("0");
  } finally { await context.close(); }
});

test("admin tabs show visitors and system state and the table scrolls inside its card",async({page})=>{
  await signIn(page,"viewer");
  const scroll=page.getByTestId("platform-table-scroll");
  await expect(scroll).toHaveCSS("overflow-y","auto");
  await expect(page.getByTestId("platform-table").locator("thead")).toHaveCSS("position","sticky");
  await expect(page.getByRole("button",{name:"Отключить",exact:true}).first()).toBeVisible();

  await page.getByRole("link",{name:"Посетители"}).click();
  await expect(page.getByRole("heading",{name:"Посетители сайта"})).toBeVisible();
  await expect(page.getByTestId("online-now")).toContainText("3");
  await expect(page.locator('[data-slot="chart"]')).toHaveCount(1);
  await page.getByRole("link",{name:"Месяц"}).click();
  await expect(page).toHaveURL(/tab=visitors&range=month/);

  await page.getByRole("link",{name:"Система"}).click();
  await expect(page.getByRole("heading",{name:"Состояние системы"})).toBeVisible();
  await expect(page.getByTestId("system-checks").locator("li")).toHaveCount(11);
  await expect(page.getByText("1 требует внимания")).toBeVisible();
  await expect(page.locator('[data-slot="chart"]')).toHaveCount(5);
  await expect(page.locator('[data-storage="project"]')).toContainText("релизы 1.0 ГБ");
});

for(const tab of ["visitors","system"]) test(`admin ${tab} tab passes accessibility checks`,async({page})=>{
  await signIn(page,"admin");
  await page.goto(`/manage?tab=${tab}`);
  await expect(page.locator('[data-slot="chart"]').first()).toBeVisible();
  expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
});
