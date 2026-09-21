import assert from "node:assert/strict";
import test from "node:test";
import { deletedPublicationArchiveUrl, qualityHint } from "../lib/format";

test("quality hints hide exact and localize non-exact states", () => {
  assert.equal(qualityHint("exact"), undefined);
  assert.equal(qualityHint("EXACT"), undefined);
  assert.equal(qualityHint(null), undefined);
  assert.equal(qualityHint("rounded"), "округлённые данные");
  assert.equal(qualityHint("estimated"), "оценка");
});

test("deleted publications use their archive without storing post text", () => {
  assert.equal(
    deletedPublicationArchiveUrl("telegram", "2026-09-21T00:00:00Z", "42", "example", null),
    "https://tgstat.ru/channel/@example/42",
  );
  assert.equal(
    deletedPublicationArchiveUrl("max", "2026-09-21T00:00:00Z", "117306438632766444", null, "https://maxstat.ru/channel/-70908719079458/post"),
    "https://maxstat.ru/channel/-70908719079458/post#117306438632766444",
  );
  assert.equal(
    deletedPublicationArchiveUrl("max", null, "117306438632766444", null, "https://maxstat.ru/channel/-70908719079458/post"),
    null,
  );
});
