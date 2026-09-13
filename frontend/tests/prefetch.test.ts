import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Обзор сам по себе ссылок не содержит — навигация уходит через карточку,
// поэтому страница проверяется только на отсутствие next/link.
const linkFreeSources = ["app/(overview)/page.tsx"];
const linkSources = [
  "app/manage/page.tsx",
  "app/not-found.tsx",
  "app/rating/page.tsx",
  "components/account-detail.tsx",
  "components/institution-detail.tsx",
  "components/overview-card.tsx",
  "components/platform-pending.tsx",
  "components/publication-detail.tsx",
  "components/site-header.tsx",
  "components/ui.tsx",
];

test("dynamic navigation never fans out API work through automatic prefetch", async () => {
  for (const source of [...linkSources, ...linkFreeSources]) {
    const contents = await readFile(new URL(`../${source}`, import.meta.url), "utf8");
    assert.doesNotMatch(contents, /from "next\/link"/, `${source} must use full-page navigation`);
    const links = contents.match(/<Link\b(?:(?!>).)*>/gs) ?? [];
    assert.ok(links.length > 0 || linkFreeSources.includes(source), `${source} must still contain a Link`);
    for (const link of links) {
      assert.match(link, /\bprefetch=\{false\}/, `${source}: ${link}`);
    }
  }
});
