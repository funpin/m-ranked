import type { components } from "../../contracts/openapi/m-ranked-v1-client";

const date = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", day: "numeric", month: "long", year: "numeric",
});
const integer = new Intl.NumberFormat("ru-RU");
const shortDate = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "numeric",
});

export function compactTrackingDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? null : shortDate.format(parsed);
}

export function trackingDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? null : date.format(parsed);
}

export function studentCount(students: components["schemas"]["InstitutionStudentCount"] | null | undefined): string {
  if (!students || !Number.isSafeInteger(students.value) || students.value < 0) return "Нет данных";
  return `${students.approximate ? "≈ " : ""}${integer.format(students.value)}`;
}
