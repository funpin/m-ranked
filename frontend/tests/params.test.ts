import assert from "node:assert/strict";
import test from "node:test";
import {
  comparePeriod,
  comparisonPlatformIsPending,
  comparisonSelectionIsExplicit,
  defaultComparisonSelection,
  legacyPlatformDecision,
  normalizeHistoryLimit,
  normalizePeriod,
  normalizePlatform,
  normalizeSort,
  parseComparisonSelection,
  parseComparisonQuerySelection,
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
  assert.equal(normalizeSort("coverage", "all"), "coverage");
  assert.equal(normalizeSort("coverage", "telegram"), "median_reactions");
  assert.equal(normalizeSort("subscribers", "vk"), "subscribers");
  assert.equal(normalizeSort("subscribers", "all"), "m_rating");
});

test("comparison horizons map explicitly to bounded API periods", () => {
  assert.deepEqual(comparePeriod("24"), { hours: 24, apiPeriod: "1d" });
  assert.deepEqual(comparePeriod("72"), { hours: 72, apiPeriod: "7d" });
  assert.deepEqual(comparePeriod("336"), { hours: 336, apiPeriod: "30d" });
  assert.deepEqual(comparePeriod("bad"), { hours: 72, apiPeriod: "7d" });
  assert.deepEqual(comparePeriod(undefined), { hours: 72, apiPeriod: "7d" });
});

test("comparison selection preserves order and reports invalid bounded input", () => {
  assert.deepEqual(parseComparisonSelection(["91", "7", "34"]), {
    ids: [91, 7, 34],
    issue: null,
  });
  assert.deepEqual(parseComparisonSelection(["7", "7", "9"]), {
    ids: [7, 9],
    issue: null,
  });
  assert.equal(parseComparisonSelection(["0"]).issue, "invalid");
  assert.equal(parseComparisonSelection(["not-a-number"]).issue, "invalid");
  assert.deepEqual(
    parseComparisonSelection(Array.from({ length: 51 }, (_, index) => String(index + 1))).issue,
    "too_many",
  );
  assert.deepEqual(
    defaultComparisonSelection(Array.from({ length: 75 }, (_, index) => index + 1)),
    Array.from({ length: 50 }, (_, index) => index + 1),
  );
});

test("legacy comparison selection is applied only when submitted is true", () => {
  assert.equal(comparisonSelectionIsExplicit(undefined), false);
  assert.equal(comparisonSelectionIsExplicit("false"), false);
  assert.equal(comparisonSelectionIsExplicit("true"), true);
  assert.deepEqual(
    parseComparisonQuerySelection(
      "telegram", "false", ["920002"], ["910001"],
    ),
    { explicit: false, type: "channels", ids: [], issue: null },
  );
  assert.deepEqual(
    parseComparisonQuerySelection("telegram", undefined, ["920002"], undefined),
    { explicit: false, type: "channels", ids: [], issue: null },
  );
});

test("legacy comparison leaves MAX and all-platform requests on the pending branch", () => {
  assert.equal(comparisonPlatformIsPending("max"), true);
  assert.equal(comparisonPlatformIsPending("all"), true);
  assert.equal(comparisonPlatformIsPending("telegram"), false);
  assert.equal(comparisonPlatformIsPending("vk"), false);
  assert.equal(comparisonPlatformIsPending("rutube"), false);
  assert.equal(comparisonPlatformIsPending(normalizePlatform("unknown")), false);
});

test("comparison parameters use only the legacy namespace for the selected platform", () => {
  assert.deepEqual(
    parseComparisonQuerySelection("telegram", "true", ["920002", "920001"], undefined),
    { explicit: true, type: "channels", ids: [920002, 920001], issue: null },
  );
  assert.deepEqual(
    parseComparisonQuerySelection("telegram", "true", undefined, ["910001"]),
    { explicit: true, type: "channels", ids: [], issue: null },
  );
  assert.deepEqual(
    parseComparisonQuerySelection("vk", "true", ["920001"], undefined),
    { explicit: true, type: "institutions", ids: [], issue: null },
  );
  assert.deepEqual(
    parseComparisonQuerySelection("rutube", "true", ["920001"], ["910001"]),
    { explicit: true, type: "institutions", ids: [910001], issue: null },
  );
  assert.equal(
    parseComparisonQuerySelection("telegram", "true", ["bad"], ["also-bad"]).issue,
    "invalid",
  );
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
  assert.equal(normalizeHistoryLimit("49"), 100);
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
