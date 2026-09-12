import assert from "node:assert/strict";
import test from "node:test";
import { collectPages, uniqueRows } from "../lib/continuation";

test("all 207 comparison candidates and series remain reachable through bounded pages", async () => {
  const pages = await collectPages(async (cursor) => {
    const offset = Number(cursor ?? 0);
    return { datasetRevision: 7, items: Array.from({ length: Math.min(50, 207 - offset) }, (_, index) => ({ id: offset + index + 1 })),
      nextCursor: offset + 50 < 207 ? String(offset + 50) : null };
  }, (page) => page.nextCursor);
  assert.equal(pages.length, 5);
  assert.deepEqual(uniqueRows(pages.flatMap((page) => page.items), (item) => item.id).map((item) => item.id), Array.from({ length: 207 }, (_, index) => index + 1));
});

test("revision changes restart continuation without leaking the incomplete earlier result", async () => {
  let revision = 1;
  const pages = await collectPages(async (cursor) => {
    if (cursor) revision = 2;
    return { datasetRevision: revision, nextCursor: cursor ? null : "next" };
  }, (page) => page.nextCursor);
  assert.deepEqual(pages.map((page) => page.datasetRevision), [2, 2]);
});

test("broken continuation loops and repeated identities fail closed instead of silently dropping entities", async () => {
  await assert.rejects(collectPages(async () => ({ datasetRevision: 1, nextCursor: "loop" }), (page) => page.nextCursor), /repeated continuation/);
  assert.throws(() => uniqueRows([{ id: 1 }, { id: 1 }], (item) => item.id), /duplicate identities/);
});
