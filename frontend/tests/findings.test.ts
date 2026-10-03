import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_FINDINGS_QUERY, findingBadge, findingsHrefQuery, formatIndex, normalizeFindingsQuery,
  recallInstitution, rememberInstitution,
} from "../lib/findings";
import type { Finding } from "../lib/types";

test("findings defaults to all institutions, 7 days and interaction index", () => {
  assert.deepEqual(normalizeFindingsQuery({}), {
    mode: "all", institution: null, platform: "all", period: "7d", types: [],
    sort: "interaction_index", direction: "desc", group: "none", q: "",
  });
});

test("institution list reuses the warmed default listing", () => {
  // Прогрев кэша держит /api/v1/findings?period=7d: список вузов берётся из той же записи.
  assert.deepEqual(DEFAULT_FINDINGS_QUERY, normalizeFindingsQuery({ period: "7d" }));
  assert.equal(DEFAULT_FINDINGS_QUERY.mode, "all");
  assert.equal(DEFAULT_FINDINGS_QUERY.group, "none");
});

test("findings normalizes unknown values instead of failing", () => {
  const query = normalizeFindingsQuery({
    mode: "institution", institution: "abc", period: "3h", types: ["gif", "video", "photo", "video"],
    sort: "erv", direction: "up", group: "platform", q: "  мгу ",
  });
  assert.equal(query.mode, "all");
  assert.equal(query.institution, null);
  assert.equal(query.period, "7d");
  assert.deepEqual(query.types, ["photo", "video"]);
  assert.equal(query.sort, "interaction_index");
  assert.equal(query.direction, "desc");
  assert.equal(query.group, "none");
  assert.equal(query.q, "мгу");
});

test("institution mode keeps the id and drops grouping", () => {
  const query = normalizeFindingsQuery({ mode: "institution", institution: "12", group: "institution" });
  assert.equal(query.mode, "institution");
  assert.equal(query.institution, 12);
  assert.equal(query.group, "none");
});

test("href query omits defaults-free empties and repeats types", () => {
  const query = normalizeFindingsQuery({ types: ["photo", "video"], q: "" });
  assert.deepEqual(findingsHrefQuery(query), {
    mode: undefined, institution: undefined, platform: "all", period: "7d",
    types: ["photo", "video"], sort: "interaction_index", direction: "desc", group: undefined, q: undefined,
  });
});

test("formatIndex covers small, large and missing values", () => {
  assert.equal(formatIndex(4.2), "×4,2");
  assert.equal(formatIndex(0.4), "×0,4");
  assert.equal(formatIndex(70.5), "×70,5");
  assert.equal(formatIndex(2), "×2,0");
  assert.equal(formatIndex(null), "—");
});

const base = { ageHours: 24, preliminary: false, anomalyLevel: 0 } as Finding;

test("one badge by priority: preliminary, gap hour, weak signal, unchecked", () => {
  assert.equal(findingBadge({ ...base, ageHours: 6, preliminary: true, anomalyLevel: 1 }, true), "предварительно, 6 ч");
  assert.equal(findingBadge({ ...base, ageHours: 12 }, true), "по 12-му часу");
  assert.equal(findingBadge({ ...base, anomalyLevel: 1 }, true), "слабый сигнал");
  assert.equal(findingBadge({ ...base, anomalyLevel: null }, true), "не проверен");
  assert.equal(findingBadge({ ...base, anomalyLevel: null }, false), null);
  assert.equal(findingBadge(base, true), null);
});

test("rememberInstitution survives throwing storage", () => {
  const broken = { setItem() { throw new Error("denied"); }, getItem() { throw new Error("denied"); } };
  assert.doesNotThrow(() => rememberInstitution(broken, 5));
  assert.equal(recallInstitution(broken), null);
  assert.equal(recallInstitution(null), null);
  const values = new Map<string, string>();
  const storage = { setItem: (key: string, value: string) => void values.set(key, value), getItem: (key: string) => values.get(key) ?? null };
  rememberInstitution(storage, 7);
  assert.equal(recallInstitution(storage), 7);
  values.set("m-ranked-findings-institution", "-3");
  assert.equal(recallInstitution(storage), null);
});
