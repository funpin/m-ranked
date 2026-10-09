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
  // Формы каталога открываются кнопками в модальных окнах.
  await expect(page.getByTestId("institution-create")).toHaveCount(0);
  await page.getByTestId("open-institution-create").click();
  await expect(page.getByRole("dialog",{name:"Новый вуз"})).toBeVisible();
  await expect(page.locator('[data-testid="institution-create"] input[name="name"]')).toBeEnabled({enabled:role!=="viewer"});
  await page.getByRole("button",{name:"Отмена"}).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Удалить",exact:true}).first()).toBeEnabled({enabled:role==="admin"});
  const html=await page.content();expect(html).not.toContain("fixture-password");
  await page.getByTestId("open-account-matrix").click();
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
  } else await page.keyboard.press("Escape");
  // Окно закрывается анимацией: axe проверяет страницу после неё.
  await expect(page.getByRole("dialog")).toHaveCount(0);
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
  // Панель обновляет данные сама: при возвращении на вкладку — сразу.
  const refreshed=page.waitForRequest((request)=>request.url().includes("/manage?tab=visitors")&&request.headers()["rsc"]==="1");
  await page.evaluate(()=>{window.dispatchEvent(new Event("focus"));});
  await page.waitForTimeout(2100);
  await page.evaluate(()=>{window.dispatchEvent(new Event("focus"));});
  await refreshed;
  await expect(page.getByTestId("live-refresh")).toContainText("Обновлено");
  await expect(page.locator('[data-slot="chart"]')).toHaveCount(1);
  await page.getByRole("link",{name:"Месяц"}).click();
  await expect(page).toHaveURL(/tab=visitors&range=month/);

  // В проде /api/v1/admin раздаёт nginx; здесь живой буфер берётся у фикстуры API.
  await page.route("**/api/v1/admin/system/live**",async(route)=>{
    const url=new URL(route.request().url());
    await route.fulfill({response:await route.fetch({url:`http://127.0.0.1:18091${url.pathname}${url.search}`})});
  });
  await page.getByRole("link",{name:"Система"}).click();
  await expect(page.getByRole("heading",{name:"Состояние системы"})).toBeVisible();
  await expect(page.getByTestId("live-refresh")).toBeVisible();
  await expect(page.getByTestId("system-checks").locator("li")).toHaveCount(11);
  await expect(page.getByText("1 требует внимания")).toBeVisible();
  // Ресурсы — кольца и живые спарклайны из буфера API, хранилище — сразу под ними.
  const host=page.getByTestId("host-cards");
  for(const label of ["CPU","RAM","Disk","Network","Services"]) await expect(host.locator(`[data-metric="${label}"]`)).toBeVisible();
  await expect(host.locator('[data-metric="CPU"] [data-slot="chart"]')).toHaveCount(2);
  await expect(host.locator('[data-metric="Network"]')).toContainText("/с");
  await expect(page.getByTestId("storage-cards")).toContainText("релизы");
  await expect(page.getByTestId("storage-cards")).toContainText("1.0 ГБ");
  await expect(page.getByTestId("pipeline-stages").locator("li")).toHaveCount(6);
  await expect(page.getByTestId("collection-platforms").locator("li")).toHaveCount(4);
  await page.getByRole("link",{name:"1 час"}).click();
  await expect(page).toHaveURL(/tab=system&range=1h/);
  await expect(page.getByText("Дисковый ввод-вывод")).toBeVisible();
  // Резервные копии: список с отметкой проверки; кнопка обновления — только ADMIN.
  await expect(page.getByTestId("backup-state")).toHaveText("готова");
  await expect(page.getByText("проверена восстановлением")).toHaveCount(1);
  await expect(page.getByRole("button",{name:"Обновить резервную копию"})).toBeDisabled();
});

for(const tab of ["visitors","system"]) test(`admin ${tab} tab passes accessibility checks`,async({page})=>{
  await signIn(page,"admin");
  await page.goto(`/manage?tab=${tab}`);
  await expect(page.locator('[data-slot="chart"]').first()).toBeVisible();
  expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
});

test("the catalog table filters, pages by institution and pauses selected accounts in bulk",async({page})=>{
  await signIn(page,"editor");
  const table=page.getByTestId("platform-table");
  await page.getByLabel("Площадка").selectOption("vk");
  await expect(table.locator("tbody tr")).toHaveCount(2);
  await page.getByLabel("Поиск по вузам и аккаунтам").fill("бета");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("button",{name:"Сбросить"}).click();
  await expect(table.locator("tbody tr")).toHaveCount(8);
  await expect(page.getByTestId("catalog-pagination")).toContainText("Страница 1 из 1");

  const posted:{path:string;body:string;mode:string|undefined}[]=[];
  await page.route("**/manage/platform-accounts/*/disable",async(route)=>{
    const request=route.request();
    posted.push({path:new URL(request.url()).pathname,body:request.postData()??"",mode:request.headers()["x-mranked-response"]});
    await route.fulfill({json:{location:"/manage?platform_status=account-disabled"}});
  });
  await page.getByLabel("Площадка").selectOption("telegram");
  await page.getByRole("checkbox",{name:"Выбрать все аккаунты на странице"}).click();
  await expect(page.getByTestId("bulk-actions")).toContainText("Выбрано 2");
  await page.getByRole("button",{name:"Остановить сбор"}).click();
  await expect(page.getByRole("status").filter({hasText:"Готово: 2"})).toBeVisible();
  expect(posted.map((item)=>item.path).sort()).toEqual(["/manage/platform-accounts/10/disable","/manage/platform-accounts/20/disable"]);
  for(const item of posted){
    const form=new URLSearchParams(item.body);
    expect(item.mode).toBe("json");
    expect(form.get("expected_row_version")).toBe("7");
    expect(form.get("csrf_token")).toBe("fixture-csrf-token");
    expect(form.get("correlation_id")).toMatch(/^[0-9a-f-]{36}$/);
  }
});
