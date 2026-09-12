import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const linkSources = [
  "app/(overview)/page.tsx",
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
  for (const source of linkSources) {
    const contents = await readFile(new URL(`../${source}`, import.meta.url), "utf8");
    assert.doesNotMatch(contents, /from "next\/link"/, `${source} must use full-page navigation`);
    const links = contents.match(/<Link\b(?:(?!>).)*>/gs) ?? [];
    assert.ok(links.length > 0, `${source} must still contain a Link`);
    for (const link of links) {
      assert.match(link, /\bprefetch=\{false\}/, `${source}: ${link}`);
    }
  }
});
