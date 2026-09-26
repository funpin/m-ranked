import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";
import { API_DIGEST, OPERATION_TEXT, operationAnchor, operationsBySection } from "../lib/api-reference";
import { ARTICLES, editUrl, headingsOf, neighbours, slugify } from "../lib/methodology";

test("у каждой статьи из списка есть файл, и лишних файлов нет", async () => {
  const files = (await readdir(new URL("../content/methodology/", import.meta.url))).filter((name) => name.endsWith(".mdx"));
  assert.deepEqual(files.map((name) => name.replace(/\.mdx$/, "")).sort(), ARTICLES.map((article) => article.slug).sort());
});

test("внутренние ссылки статей ведут на существующие страницы", async () => {
  const known = new Set(["/rating", "/statistics", "/compare", "/methodology", "/methodology/api",
    ...ARTICLES.map((article) => `/methodology/${article.slug}`)]);
  for (const article of ARTICLES) {
    const source = await readFile(new URL(`../content/methodology/${article.slug}.mdx`, import.meta.url), "utf8");
    for (const [, href] of source.matchAll(/\]\((\/[^)#\s]*)/g)) assert.ok(known.has(href!), `${article.slug}: ${href}`);
    assert.ok(headingsOf(source).length >= 3, `${article.slug}: оглавление`);
  }
});

test("якорь заголовка одинаков в статье и оглавлении", () => {
  assert.equal(slugify("Ноль и «нет данных» — разные вещи"), "ноль-и-нет-данных-разные-вещи");
  assert.equal(slugify("Через 30 суток"), "через-30-суток");
  assert.deepEqual(headingsOf("## Раз\n```text\n## не заголовок\n```\n### Два **жирно**\n"), [
    { id: "раз", text: "Раз", level: 2 },
    { id: "два-жирно", text: "Два жирно", level: 3 },
  ]);
});

test("соседние статьи и ссылка на правку", () => {
  assert.equal(neighbours("about").previous, null);
  assert.equal(neighbours("about").next?.slug, "platforms");
  assert.equal(neighbours("openness").next, null);
  assert.match(editUrl("schedule"), /\/edit\/main\/frontend\/content\/methodology\/schedule\.mdx$/);
});

test("справочник API: только публичные чтения, и у каждого — описание по-русски", () => {
  assert.ok(API_DIGEST.operations.length > 0);
  for (const operation of API_DIGEST.operations) {
    assert.doesNotMatch(operation.path, /\/admin\/|\/health\//);
    assert.ok(OPERATION_TEXT[operation.operationId], `нет описания для ${operation.operationId}`);
  }
  for (const id of Object.keys(OPERATION_TEXT)) {
    assert.ok(API_DIGEST.operations.some((operation) => operation.operationId === id), `описание без метода: ${id}`);
  }
  const sections = operationsBySection();
  assert.equal(sections.flatMap((section) => section.operations).length, API_DIGEST.operations.length);
  const anchors = [...sections.map((section) => `section-${section.id}`), ...API_DIGEST.operations.map((operation) => operationAnchor(operation.operationId))];
  assert.equal(new Set(anchors).size, anchors.length);
});
