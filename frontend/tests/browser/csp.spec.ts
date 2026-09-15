import { test, expect } from "@playwright/test";

const strict = (value: string | undefined) => (value ?? "").split(";").map((part) => part.trim());

test("the administrative page enforces a nonce policy without unsafe-inline scripts", async ({ page }) => {
  const response = await page.goto("/manage");
  const header = response?.headers()["content-security-policy"];
  const script = strict(header).find((part) => part.startsWith("script-src"))!;
  expect(script).toContain("'strict-dynamic'");
  expect(script).toMatch(/'nonce-[A-Za-z0-9+/=]{16,}'/);
  expect(script).not.toContain("'unsafe-inline'");
  expect(script).not.toContain("'unsafe-eval'");
  for (const directive of ["object-src 'none'", "base-uri 'none'", "form-action 'self'", "frame-ancestors 'self'"])
    expect(strict(header)).toContain(directive);
  expect(response?.headers()["cache-control"]).toContain("no-store");
});

test("every response carries its own nonce", async ({ page }) => {
  const first = await page.goto("/manage");
  const second = await page.goto("/manage");
  const nonceOf = (value: string | undefined) => /'nonce-([A-Za-z0-9+/=]+)'/.exec(value ?? "")?.[1];
  const one = nonceOf(first?.headers()["content-security-policy"]);
  const two = nonceOf(second?.headers()["content-security-policy"]);
  expect(one).toBeTruthy();
  expect(two).toBeTruthy();
  expect(one).not.toBe(two);
  // Шестнадцать случайных байт в base64 — двадцать четыре символа.
  expect(one!.length).toBeGreaterThanOrEqual(24);
});

test("a forged inbound policy header cannot dictate the nonce", async ({ page }) => {
  await page.setExtraHTTPHeaders({
    "x-nonce": "attacker-nonce",
    "content-security-policy": "script-src 'nonce-attacker-nonce'",
  });
  const response = await page.goto("/manage");
  const header = response?.headers()["content-security-policy"] ?? "";
  expect(header).not.toContain("attacker-nonce");
  expect(header).toMatch(/'nonce-[A-Za-z0-9+/=]{16,}'/);
});

test("public pages keep the baseline policy and receive no nonce", async ({ page }) => {
  const response = await page.goto("/");
  const header = response?.headers()["content-security-policy"] ?? "";
  // Страницы отдаются из кэша, поэтому nonce им не выдаётся: он устарел бы.
  expect(header).not.toContain("nonce-");
  for (const directive of ["object-src 'none'", "base-uri 'none'", "frame-ancestors 'self'"])
    expect(header).toContain(directive);
});

test("injected markup cannot execute while the page\'s own script still runs", async ({ page }) => {
  await page.goto("/manage");
  // Классический вектор внедрения — разметка с обработчиком в атрибуте.
  // Скрипт, созданный уже доверенным кодом, strict-dynamic разрешает намеренно,
  // поэтому проверяется именно то, что закрывает политика.
  const handled = await page.evaluate(() => {
    const host = document.createElement("div");
    host.innerHTML = '<img src="x" onerror="window.__handler = true"><button onclick="window.__handler = true">x</button>';
    document.body.append(host);
    host.querySelector("button")!.click();
    return (window as unknown as Record<string, unknown>).__handler;
  });
  expect(handled).toBeUndefined();
  // Проверить сам eval со стороны драйвера нельзя: его вычисления идут мимо
  // политики страницы. Отсутствие 'unsafe-eval' в заголовке проверено выше.
  // Тема применяется своим инлайн-скриптом: он несёт nonce и обязан выполниться.
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toMatch(/light|dark/);
});

test("administrative html is never stored by a shared cache", async ({ request }) => {
  const response = await request.get("/manage");
  expect(response.headers()["cache-control"]).toContain("no-store");
});
