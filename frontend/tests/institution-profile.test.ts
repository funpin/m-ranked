import assert from "node:assert/strict";
import test from "node:test";
import { trackingDate, compactTrackingDate, studentCount } from "../lib/institution-profile";

const students = { value: 8559, approximate: false, referenceYear: 2024,
  sourceUrl: "https://monitoring.miccedu.ru/iam/2025/_vpo/inst.php?id=161",
  sourceLabel: "Мониторинг Минобрнауки · 2025", scope: "Все формы", verifiedAt: "2026-10-02" };

test("enrollment date uses Moscow's calendar day across UTC midnight", () => {
  assert.equal(trackingDate("2026-09-01T22:30:00Z"), "2 сентября 2026 г.");
  assert.equal(trackingDate(null), null);
  assert.equal(trackingDate("invalid"), null);
  assert.equal(compactTrackingDate("2026-09-01T22:30:00Z"), "02.09.2026");
  assert.equal(compactTrackingDate("2026-09-30"), "30.09.2026");
  assert.equal(compactTrackingDate("invalid"), null);
});

test("student counts distinguish zero, missing data and an estimate", () => {
  assert.equal(studentCount(students).replace(/\s/g, " "), "8 559");
  assert.equal(studentCount({ ...students, value: 4000, approximate: true }).replace(/\s/g, " "), "≈ 4 000");
  assert.equal(studentCount({ ...students, value: 0 }), "0");
  assert.equal(studentCount(null), "Нет данных");
  assert.equal(studentCount({ ...students, value: -1 }), "Нет данных");
});
