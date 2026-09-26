import assert from "node:assert/strict";
import test from "node:test";
import { pageEntries, publicationEntries, sitemapIndex, urlset } from "../lib/sitemap";

const origin = new URL("https://m.funpin.org");

test("индекс карты перечисляет разделы и все файлы постов", () => {
  const index = sitemapIndex(origin, 2);
  assert.match(index, /<sitemapindex /);
  for (const file of ["pages.xml", "publications-0.xml", "publications-1.xml"]) {
    assert.ok(index.includes(`<loc>https://m.funpin.org/sitemaps/${file}</loc>`), file);
  }
});

test("карта отдаёт канонические адреса без параметров и с lastmod", () => {
  const pages = urlset(origin, pageEntries({ accounts: [{ accountId: "ABCDEF00-0000-4000-8000-000000000001", lastModified: null }], institutions: [{ legacyId: 7 }] }));
  assert.ok(pages.includes("<loc>https://m.funpin.org/</loc>"));
  assert.ok(pages.includes("<loc>https://m.funpin.org/institutions/7</loc>"));
  assert.ok(pages.includes("<loc>https://m.funpin.org/accounts/abcdef00-0000-4000-8000-000000000001</loc></url>"));
  assert.doesNotMatch(pages, /<loc>[^<]*\?/);
  const posts = urlset(origin, publicationEntries([{ publicationId: "4af36df4-271d-5408-8f47-512880569523", lastModified: "2026-07-07T15:00:00+00:00" }]));
  assert.ok(posts.includes("<url><loc>https://m.funpin.org/publications/4af36df4-271d-5408-8f47-512880569523</loc><lastmod>2026-07-07T15:00:00.000Z</lastmod></url>"));
});
