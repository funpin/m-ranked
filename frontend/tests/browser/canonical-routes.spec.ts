import { expect, test } from "@playwright/test";

const uuid = (kind: number, id: number) => `${String(kind).padStart(8,"0")}-0000-4000-8000-${String(id).padStart(12,"0")}`;

test("all account platforms use canonical pages and legacy redirects preserve identity", async ({ page, request }) => {
  for (const [route, id, kind, platform] of [
    ["channels", 1, 1, "telegram"], ["platform-accounts", 1, 2, "vk"],
    ["platform-accounts", 3, 3, "max"], ["platform-accounts", 4, 4, "rutube"],
  ] as const) {
    const path = `/accounts/${uuid(kind,id)}`;
    const response = await request.get(`/${route}/${id}?period=7d`, { maxRedirects: 0 });
    expect(response.status()).toBe(308);
    expect(new URL(response.headers().location!, response.url()).pathname).toBe(path);
    expect(new URL(response.headers().location!, response.url()).search).toBe("?period=7d");
    await page.goto(path);
    await expect(page.getByTestId("brand")).toHaveAttribute("href", `/?platform=${platform}`);
    await expect(page.locator("tbody tr")).toHaveCount(2);
    await expect(page.locator("tbody a").first()).toHaveAttribute("href", /^\/publications\/[0-9a-f-]{36}$/);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", new RegExp(`${path}$`));
  }
});

test("publication redirects retain history limits and navigation uses UUIDs", async ({ page, request }) => {
  for (const [route, kind] of [["posts", 5], ["platform-posts", 6]] as const) {
    const response = await request.get(`/${route}/1?history_limit=500`, { maxRedirects: 0 });
    expect(response.status()).toBe(308);
    expect(new URL(response.headers().location!, response.url()).pathname).toBe(`/publications/${uuid(kind,1)}`);
    expect(new URL(response.headers().location!, response.url()).search).toBe("?history_limit=500");
    await page.goto(`/${route}/1?history_limit=500`);
    await expect(page).toHaveURL(new RegExp(`/publications/${uuid(kind,1)}\\?history_limit=500$`));
    await expect(page.locator("tbody tr")).toHaveCount(160);
    await expect(page.locator('a[rel="next"]')).toHaveAttribute("href", `/publications/${uuid(kind,2)}`);
    await expect(page.locator("h1 a").first()).toHaveAttribute("href", /^\/accounts\/[0-9a-f-]{36}$/);
    await page.locator('a[rel="next"]').click();
    await expect(page).toHaveURL(new RegExp(`/publications/${uuid(kind,2)}$`));
  }
  expect((await request.get(`/publications/${uuid(5,1)}?history_limit=49`)).status()).toBe(422);
  expect((await request.get("/accounts/1")).status()).toBe(404);
  expect((await request.get(`/accounts/${uuid(1,9999)}`)).status()).toBe(404);
  expect((await request.get(`/publications/${uuid(5,9999)}`)).status()).toBe(404);
});

test("sitemap lists canonical pages and publications with lastmod", async ({ request }) => {
  const index = await request.get("/sitemap.xml");
  expect(index.status()).toBe(200);
  expect(index.headers()["content-type"]).toContain("application/xml");
  const body = await index.text();
  expect(body).toContain("/sitemaps/pages.xml</loc>");
  expect(body).toContain("/sitemaps/publications-0.xml</loc>");
  const pages = await (await request.get("/sitemaps/pages.xml")).text();
  expect(pages).toContain("/institutions/1</loc>");
  expect(pages).toContain(`/accounts/${uuid(1,1)}</loc>`);
  const posts = await (await request.get("/sitemaps/publications-0.xml")).text();
  expect(posts).toContain(`/publications/${uuid(5,1)}</loc><lastmod>2026-07-07T15:00:00.000Z</lastmod>`);
  expect((await request.get("/sitemaps/other.xml")).status()).toBe(404);
  expect(await (await request.get("/robots.txt")).text()).toMatch(/Sitemap: https:\/\/[^\s]+\/sitemap\.xml/);
});
