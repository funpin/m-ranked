import { test,expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

function credentials(role:string){return `Basic ${Buffer.from(`${role}:fixture-password`).toString("base64")}`;}
test("manage challenges anonymous requests before rendering any administrative data",async({request})=>{
  const response=await request.get("/manage");expect(response.status()).toBe(401);expect(response.headers()["cache-control"]).toBe("no-store");expect(response.headers()["www-authenticate"]).toContain("Basic");
  expect(await response.json()).toEqual({detail:"Not authenticated"});
});
for(const role of ["viewer","editor","admin"]) test(`manage ${role} receives SSR catalog and correct capabilities`,async({page})=>{
  await page.setExtraHTTPHeaders({authorization:credentials(role)});
  const response=await page.goto("/manage");expect(response?.status()).toBe(200);expect(response?.headers()["cache-control"]).toContain("no-store");
  await expect(page.getByRole("heading",{name:"Управление каналами"})).toBeVisible();
  await expect(page.getByTestId('platform-table').locator('tbody tr')).toHaveCount(8);
  await expect(page.locator('[data-testid="institution-create"] input[name="name"]')).toBeEnabled({enabled:role!=="viewer"});
  await expect(page.getByRole("button",{name:"Удалить",exact:true}).first()).toBeEnabled({enabled:role==="admin"});
  const html=await page.content();expect(html).not.toContain(credentials(role));expect(html).not.toContain("fixture-password");
  await expect(page.locator('#accountMatrix input[name="telegram"]')).toHaveValue("https://example.test/telegram/1");
  const nativeId=page.getByTestId("native-id-editor").first();
  await nativeId.locator("summary").click();
  await expect(nativeId.locator('input[name="native_id"]')).toBeVisible();
  await expect(nativeId.locator('input[name="native_id"]')).toBeEnabled({enabled:role!=="viewer"});
  await expect(nativeId.locator("form")).toHaveAttribute("action","/manage/platform-accounts/12/native-id");
  await expect(nativeId.locator('input[name="expected_row_version"]')).toHaveValue("7");
  await nativeId.locator("summary").click();
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
  await page.setExtraHTTPHeaders({ authorization: credentials("admin") });
  await page.goto("/manage");
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
  const context = await browser.newContext({ javaScriptEnabled: false, extraHTTPHeaders: { authorization: credentials("editor") } });
  try {
    const page = await context.newPage();
    await page.goto("/manage");
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
