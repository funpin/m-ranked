import assert from "node:assert/strict";
import { test } from "node:test";
import { overviewPagination } from "../lib/overview-pagination";

test("cursor trail returns to the actual previous 20-card page", () => {
  const first = overviewPagination(undefined, undefined);
  assert.equal(first.page, 1);
  assert.deepEqual(first.nextTrail, ["first"]);
  const second = overviewPagination("cursor-1", first.nextTrail);
  assert.equal(second.page, 2);
  assert.equal(second.previousCursor, undefined);
  const third = overviewPagination("cursor-2", second.nextTrail);
  assert.equal(third.page, 3);
  assert.equal(third.previousCursor, "cursor-1");
  assert.deepEqual(third.previousTrail, ["first"]);
});

test("malformed trail cannot create an unbounded page path", () => {
  assert.deepEqual(overviewPagination("cursor-1", ["bad", "cursor-0"]).trail, ["first"]);
  assert.deepEqual(overviewPagination(undefined, ["first", "cursor-1"]).trail, []);
});
