import assert from "node:assert/strict";
import test from "node:test";
import { qualityHint } from "../lib/format";

test("quality hints hide exact and localize non-exact states", () => {
  assert.equal(qualityHint("exact"), undefined);
  assert.equal(qualityHint("EXACT"), undefined);
  assert.equal(qualityHint(null), undefined);
  assert.equal(qualityHint("rounded"), "округлённые данные");
  assert.equal(qualityHint("estimated"), "оценка");
});
