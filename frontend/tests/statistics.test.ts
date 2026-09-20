import assert from "node:assert/strict";
import test from "node:test";
import { normalizeStatisticsQuery, statisticsHrefQuery } from "../lib/statistics";

test("statistics defaults to all-platform publications and ERV descending", () => {
  assert.deepEqual(normalizeStatisticsQuery({}), {
    view: "publications", platform: "all", period: "30d", q: "",
    publicationSort: "erv", publicationDirection: "desc",
    entitySort: "erv", entityDirection: "desc",
  });
});

test("all-platform mode normalizes entity view to publications", () => {
  assert.equal(normalizeStatisticsQuery({ platform: "all", view: "entities" }).view, "publications");
  assert.equal(normalizeStatisticsQuery({ platform: "vk", view: "entities" }).view, "entities");
});

test("legacy reactions sorting is merged into interactions", () => {
  assert.equal(normalizeStatisticsQuery({ publication_sort: "reactions" }).publicationSort, "interactions");
});

test("statistics normalizes unknown values and trims bounded search", () => {
  const query = normalizeStatisticsQuery({
    platform: "unknown", period: "forever", q: "  @Университет  ",
    publication_sort: "unknown", entity_sort: "views",
    publication_direction: "asc", entity_direction: "wrong",
  });
  assert.equal(query.platform, "all");
  assert.equal(query.period, "30d");
  assert.equal(query.q, "@Университет");
  assert.equal(query.publicationSort, "erv");
  assert.equal(query.entitySort, "views");
  assert.equal(query.publicationDirection, "asc");
  assert.equal(query.entityDirection, "desc");
});

test("statistics URL state contains every result dimension", () => {
  const query = normalizeStatisticsQuery({ platform: "vk", view: "entities", q: "alpha" });
  assert.deepEqual(statisticsHrefQuery(query), {
    view: "entities", platform: "vk", period: "30d", q: "alpha",
    publication_sort: "erv", publication_direction: "desc",
    entity_sort: "erv", entity_direction: "desc",
  });
});
