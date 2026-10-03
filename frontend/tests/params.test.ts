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
  // умолчанию — количеству аномалий.
  assert.equal(normalizeSort("coverage", "all"), "anomalies");
  assert.equal(normalizeSort("accounts", "all"), "anomalies");
  assert.equal(normalizeSort("coverage", "telegram"), "anomalies");
  assert.equal(normalizeSort("subscribers", "vk"), "subscribers");
  for (const sort of ["views", "reactions", "posts", "subscribers"] as const) {
    assert.equal(normalizeSort(sort, "all"), sort);
  }
  for (const platform of ["all", "telegram", "vk", "max", "rutube"] as const) {
    assert.equal(normalizeSort(undefined, platform), "anomalies");
    assert.equal(normalizeSort("anomalies", platform), "anomalies");
  }
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
