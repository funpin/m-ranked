import assert from "node:assert/strict";
import test from "node:test";
import {
  legacyPlatformDecision,
  normalizeHistoryLimit,
  normalizePeriod,
  normalizePlatform,
  normalizeSort,
  parsePositiveLegacyId,
  queryHref,
} from "../lib/params";

test("legacy platform and period aliases normalize to the public API vocabulary", () => {
  assert.equal(normalizePlatform("tg"), "telegram");
  assert.equal(normalizePlatform("общий"), "all");
  assert.equal(normalizePlatform("unexpected", "vk"), "vk");
  assert.equal(normalizePeriod("1d"), "1d");
  assert.equal(normalizePeriod("month", "30d"), "30d");
});

test("overview sort keys normalize per platform before the API request", () => {
  // Сортировки по числу площадок и аккаунтов убраны из набора: прежние
  // ссылки на них должны не ломаться, а приводиться к сортировке по
  // умолчанию — месту в общем М-Рейтинге.
  assert.equal(normalizeSort("coverage", "all"), "m_rating");
  assert.equal(normalizeSort("accounts", "all"), "m_rating");
  assert.equal(normalizeSort("coverage", "telegram"), "median_reactions");
  assert.equal(normalizeSort("subscribers", "vk"), "subscribers");
  assert.equal(normalizeSort("subscribers", "all"), "m_rating");
});

test("queryHref preserves repeated values and omits empty fields", () => {
  assert.equal(
    queryHref("/compare", {
      submitted: "true", channels: [7, 9], q: "", platform: "telegram",
    }),
    "/compare?submitted=true&channels=7&channels=9&platform=telegram",
  );
});

test("legacy detail IDs and Telegram history limits are bounded", () => {
  assert.equal(parsePositiveLegacyId("71"), 71);
  assert.equal(parsePositiveLegacyId("0"), null);
  assert.equal(parsePositiveLegacyId("3.5"), null);
  assert.equal(parsePositiveLegacyId("9007199254740992"), null);
  assert.equal(normalizeHistoryLimit(undefined), 100);
  assert.equal(normalizeHistoryLimit("50"), 50);
  assert.equal(normalizeHistoryLimit("1000"), 1000);
  assert.equal(normalizeHistoryLimit("3000"), 3000);
  assert.throws(() => normalizeHistoryLimit("49"), /history_limit/);
});

test("legacy platform query either redirects canonically or rejects mismatches", () => {
  assert.equal(legacyPlatformDecision(undefined, "telegram"), "absent");
  assert.equal(legacyPlatformDecision("tg", "telegram"), "redirect");
  assert.equal(legacyPlatformDecision("nonsense", "telegram"), "redirect");
  assert.equal(legacyPlatformDecision("all", "telegram"), "not_found");
  assert.equal(legacyPlatformDecision("vk", "rutube", true), "not_found");
  assert.equal(legacyPlatformDecision("all", "rutube", true), "redirect");
  assert.equal(legacyPlatformDecision("rutube", "rutube", true), "redirect");
});
