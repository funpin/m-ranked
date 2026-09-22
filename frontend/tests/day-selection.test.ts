import assert from "node:assert/strict";
import test from "node:test";
import { selectedDayHref } from "../lib/day-selection";
import { moscowDay } from "../lib/format";

test("день публикации берётся по московскому времени, а не по UTC", () => {
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

test("выбор дня живёт в URL и не стирает остальные параметры", () => {
  assert.equal(selectedDayHref("/accounts/id", "platform=vk", "2026-09-14"), "/accounts/id?platform=vk&day=2026-09-14&trend=median");
  assert.equal(selectedDayHref("/accounts/id", "platform=vk", "2026-09-14", "total"), "/accounts/id?platform=vk&day=2026-09-14&trend=total");
  assert.equal(selectedDayHref("/accounts/id", "platform=vk", undefined, "total"), "/accounts/id?platform=vk&trend=total");
  assert.equal(selectedDayHref("/accounts/id", "platform=vk&day=2026-09-14&trend=total", undefined, "total"), "/accounts/id?platform=vk&trend=total");
  assert.equal(selectedDayHref("/accounts/id", "platform=vk&day=2026-09-14&trend=median"), "/accounts/id?platform=vk");
});
