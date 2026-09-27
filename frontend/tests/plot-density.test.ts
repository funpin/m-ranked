import assert from "node:assert/strict";
import test from "node:test";
import { clusterPixelMarks, gapPresentation, mergePixelIntervals } from "../lib/plot-density";

test("nearby publication marks share one icon and separate after zoom", () => {
  const events = [{ x: 100, id: "a" }, { x: 110, id: "b" }, { x: 180, id: "c" }];
  assert.deepEqual(clusterPixelMarks(events, 22).map((group) => group.marks.map((item) => item.id)),
    [["a", "b"], ["c"]]);
  assert.deepEqual(clusterPixelMarks(events.map((event) => ({ ...event, x: event.x * 4 })), 22)
    .map((group) => group.marks.map((item) => item.id)), [["a"], ["b"], ["c"]]);
  assert.deepEqual(clusterPixelMarks([{x:0},{x:20},{x:40},{x:60}], 22).map((group) => group.marks.length),
    [2, 2]);
});

test("dense gaps become a rail while sparse gaps retain full bands", () => {
  const dense = Array.from({ length: 20 }, (_, index) => ({ left: index * 20, right: index * 20 + 3 }));
  assert.equal(gapPresentation(dense, 800), "rail");
  assert.equal(gapPresentation(dense.slice(0, 3), 800), "bands");
  assert.equal(gapPresentation(dense.slice(0, 9), 1400), "rail");
  assert.equal(gapPresentation(dense.slice(0, 3), 300), "rail");
  assert.equal(gapPresentation(dense.slice(0, 2), 300), "bands");
  assert.deepEqual(mergePixelIntervals([{ left: 20, right: 22 }, { left: 10, right: 15 }, { left: 17, right: 19 }], 3),
    [{ left: 10, right: 22 }]);
});
