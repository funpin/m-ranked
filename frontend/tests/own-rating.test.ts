import assert from "node:assert/strict";
import test from "node:test";
import { ownStatusLine, partialNote, percent, plain, platformTitle, rawShift, removedNote } from "../lib/own-rating";
import type { OwnRatingPlatform, OwnRatingRow } from "../lib/types";

const metrics = { posts: 60, activeDays: 18, coveredDays: 20.4, avgViews: 1200, students: 8000, reach: 0.15, erv: 0.0213,
  removedViews: 0, removedInteractions: 0, evenCapped: false };
const platform = (patch: Partial<OwnRatingPlatform> = {}): OwnRatingPlatform => ({ source: "formula", score: 70, rawScore: 70,
  subscores: { activity: 100, reach: 60, engagement: 50 }, metrics, ...patch });
const empty = (source: OwnRatingPlatform["source"]): OwnRatingPlatform => ({ source, score: source === "no_data" ? null : 0,
  rawScore: source === "no_data" ? null : 0, subscores: null, metrics: null });

test("статус месяца — по-русски, с датой по Москве", () => {
  assert.equal(ownStatusLine({ status: "running", asOf: "2026-11-20T22:47:00Z" }), "Месяц не закончен, данные на 21.11");
  assert.equal(ownStatusLine({ status: "published", asOf: "2026-12-08T00:00:00Z" }), "Итог месяца");
});

test("пороги формулы печатаются без лишних нулей", () => {
  assert.equal(plain(0.065), "0,065");
  assert.equal(plain(1.33), "1,33");
  assert.equal(percent(0.0085), "0,85 %");
  assert.equal(percent(0.036), "3,6 %");
});

test("«*» объясняет, какой площадки не хватает", () => {
  const row = { platforms: { telegram: empty("no_data"), vk: platform(), max: platform({ source: "partial" }), rutube: empty("no_account") } };
  assert.equal(partialNote(row as Pick<OwnRatingRow, "platforms">),
    "Telegram: собрано слишком мало дней, в среднее не входит; MAX: собрана часть месяца");
  assert.equal(partialNote({ platforms: { telegram: platform(), vk: platform(), max: platform(), rutube: empty("no_account") } }), null);
});

test("подсказка площадки называет части балла и причину нуля", () => {
  assert.equal(platformTitle(empty("no_posts")), "За месяц ни одной публикации — 0 баллов");
  assert.match(platformTitle(platform()), /регулярность 100, охват 60, вовлечённость 50; публикаций 60, дней с публикациями 18 из 20/);
});

test("вычтенное описано осторожно, без слова «накрутка»", () => {
  assert.equal(removedNote(platform()), null);
  const note = removedNote(platform({ metrics: { ...metrics, removedInteractions: 1500, evenCapped: true } }));
  assert.match(note!, /не засчитано реакций и комментариев: 1\s500, вовлечённость засчитана не выше медианы площадки/);
  assert.doesNotMatch(note!, /накрутк/);
});

test("сдвиг без очистки: плюс — без очистки вуз был бы выше", () => {
  assert.equal(rawShift({ rank: 38, rawRank: 4 }), 34);
  assert.equal(rawShift({ rank: 4, rawRank: 6 }), -2);
});
