import assert from "node:assert/strict";
import test from "node:test";
import { normalizeSearchText, prepareTargets, searchInstitutions, type SearchTarget } from "../lib/institution-search";

// Реальные названия из каталога: на них поиск и ломался.
const CATALOG: SearchTarget[] = [
  { shortName: "Академический университет им. Ж.И. Алфёрова", name: "Санкт-Петербургский национальный исследовательский Академический университет имени Ж.И. Алфёрова" },
  { shortName: "МГУ им. А.И. Куинджи", name: "Мариупольский государственный университет имени А.И. Куинджи", weight: 5 },
  { shortName: "МГУ им. М.В. Ломоносова", name: "Московский государственный университет имени М.В. Ломоносова", weight: 90 },
  { shortName: "НИУ «МЭИ»", name: "Национальный исследовательский университет «МЭИ»" },
  { shortName: "ОмГУ", name: "Омский государственный университет им. Ф.М. Достоевского", weight: 1000 },
  { shortName: "СПбГУ", name: "Санкт-Петербургский государственный университет" },
  { shortName: null, name: "Государственный университет «Дубна»" },
];
const prepared = prepareTargets(CATALOG, (item) => item);
const find = (query: string) => searchInstitutions(prepared, query).map((item) => item.shortName ?? item.name);

test("normalisation folds case, ё, quotes, dots and dashes", () => {
  assert.equal(normalizeSearchText("  НИУ «МЭИ»  "), "ниу мэи");
  assert.equal(normalizeSearchText("Ж.И. Алфёрова"), "ж и алферова");
  assert.equal(normalizeSearchText("Санкт-Петербургский"), "санкт петербургский");
  assert.equal(normalizeSearchText("…—«»"), "");
});

test("words match in any order and across short and full names", () => {
  assert.deepEqual(find("мгу ломоносова"), ["МГУ им. М.В. Ломоносова"]);
  assert.deepEqual(find("ломоносова МГУ"), ["МГУ им. М.В. Ломоносова"]);
  assert.deepEqual(find("МГУ им Ломоносова"), ["МГУ им. М.В. Ломоносова"]);
  assert.deepEqual(find("Алферова"), ["Академический университет им. Ж.И. Алфёрова"]);
  assert.deepEqual(find("ниу мэи"), ["НИУ «МЭИ»"]);
  assert.deepEqual(find("дубна"), ["Государственный университет «Дубна»"]);
});

test("exact and prefix matches outrank a match inside a word; weight breaks ties", () => {
  // ОмГУ содержит «мгу» внутри слова — ниже обоих МГУ, несмотря на вес.
  assert.deepEqual(find("мгу"), ["МГУ им. М.В. Ломоносова", "МГУ им. А.И. Куинджи", "ОмГУ"]);
  assert.deepEqual(find("спбгу"), ["СПбГУ"]);
  assert.deepEqual(find("санкт петербургский").sort(), ["Академический университет им. Ж.И. Алфёрова", "СПбГУ"].sort());
});

test("empty or punctuation-only query keeps the original order", () => {
  const all = CATALOG.map((item) => item.shortName ?? item.name);
  assert.deepEqual(find(""), all);
  assert.deepEqual(find(" «» "), all);
  assert.deepEqual(find("несуществующий"), []);
});
