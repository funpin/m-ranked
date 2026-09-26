import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Обзор сам по себе ссылок не содержит — навигация уходит через карточку,
// поэтому страница проверяется только на отсутствие next/link.
const linkFreeSources = ["app/rating/page.tsx"];
const linkSources = [
  "app/manage/page.tsx",
  "app/page.tsx",
  "app/not-found.tsx",
  "app/statistics/page.tsx",
  "components/account-detail.tsx",
  "components/compare/compare-dashboard.tsx",
  "components/header-utility-actions.tsx",
  "components/overview-card.tsx",
  "components/publication-detail.tsx",
  "components/site-header.tsx",
  "components/ui.tsx",
];

test("dynamic navigation never fans out API work through automatic prefetch", async () => {
  // Единственное место, где разрешён next/link, — обёртка: она жёстко ставит
  // prefetch в false, поэтому переход остаётся клиентским, а предзагрузки нет.
  const wrapper = await readFile(new URL("../components/native-link.tsx", import.meta.url), "utf8");
  assert.match(wrapper, /prefetch = false/, "обёртка ссылки обязана выключать предзагрузку по умолчанию");
  assert.match(wrapper, /prefetch=\{prefetch\}/, "обёртка ссылки обязана передавать prefetch дальше");

  for (const source of [...linkSources, ...linkFreeSources]) {
    const contents = await readFile(new URL(`../${source}`, import.meta.url), "utf8");
    assert.doesNotMatch(contents, /from "next\/link"/, `${source} must navigate through the wrapper`);
    const links = contents.match(/<Link\b(?:(?!>).)*>/gs) ?? [];
    assert.ok(links.length > 0 || linkFreeSources.includes(source), `${source} must still contain a Link`);
    for (const link of links) {
      assert.match(link, /\bprefetch=\{false\}/, `${source}: ${link}`);
    }
  }
});
