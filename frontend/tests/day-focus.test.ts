import assert from "node:assert/strict";
import test from "node:test";
import { moscowDay } from "../lib/format";

test("день публикации берётся по московскому времени, а не по UTC", () => {
  // 21:30 UTC — это уже следующие сутки в Москве, и недельный ряд площадки
  // считается именно по московским суткам.
  assert.equal(moscowDay("2026-09-13T21:30:00Z"), "2026-09-14");
  assert.equal(moscowDay("2026-09-13T20:59:59Z"), "2026-09-13");
  assert.equal(moscowDay("2026-09-13T21:00:00Z"), "2026-09-14");
});

test("день остаётся тем же при любом написании смещения", () => {
  assert.equal(moscowDay("2026-09-14T00:30:00+03:00"), "2026-09-14");
  assert.equal(moscowDay("2026-09-13T23:30:00+02:00"), "2026-09-14");
});

test("отсутствующая и битая дата дня не дают", () => {
  for (const value of [null, undefined, "", "не дата"]) {
    assert.equal(moscowDay(value), null);
  }
});

test("выбор дня переключается повторным нажатием и сбрасывается", async () => {
  const { toggleFocusedDay, clearFocusedDay, focusedDay, subscribeToFocusedDay } = await import("../lib/day-focus");
  const seen: (string | null)[] = [];
  const unsubscribe = subscribeToFocusedDay(() => seen.push(focusedDay()));

  toggleFocusedDay("2026-09-13");
  assert.equal(focusedDay(), "2026-09-13");
  toggleFocusedDay("2026-09-13");
  assert.equal(focusedDay(), null, "повторное нажатие по тому же дню снимает выбор");
  toggleFocusedDay("2026-09-14");
  assert.equal(focusedDay(), "2026-09-14");
  clearFocusedDay();
  assert.equal(focusedDay(), null);

  assert.deepEqual(seen, ["2026-09-13", null, "2026-09-14", null]);
  clearFocusedDay();
  assert.equal(seen.length, 4, "сброс уже сброшенного никого не будит");
  unsubscribe();
  toggleFocusedDay("2026-09-15");
  assert.equal(seen.length, 4, "отписавшийся больше не получает событий");
  clearFocusedDay();
});
