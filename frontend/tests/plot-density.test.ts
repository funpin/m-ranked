import assert from "node:assert/strict";
import test from "node:test";
import { clusterPixelMarks, mergePixelIntervals } from "../lib/plot-density";

test("nearby publication marks share one icon and separate after zoom", () => {
  const events = [{ x: 100, id: "a" }, { x: 110, id: "b" }, { x: 180, id: "c" }];
  assert.deepEqual(clusterPixelMarks(events, 22).map((group) => group.marks.map((item) => item.id)),
    [["a", "b"], ["c"]]);
  assert.deepEqual(clusterPixelMarks(events.map((event) => ({ ...event, x: event.x * 4 })), 22)
    .map((group) => group.marks.map((item) => item.id)), [["a"], ["b"], ["c"]]);
  assert.deepEqual(clusterPixelMarks([{x:0},{x:20},{x:40},{x:60}], 22).map((group) => group.marks.length),
    [2, 2]);
});

test("nearby gap intervals merge into one block", () => {
  assert.deepEqual(mergePixelIntervals([{ left: 20, right: 22 }, { left: 10, right: 15 }, { left: 17, right: 19 }], 3),
    [{ left: 10, right: 22 }]);
});
